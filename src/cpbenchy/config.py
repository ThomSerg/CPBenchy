"""Setting up a session: plugins, options, and which plugins the worker needs.

Plugins come from, in this order:
  1. the built-in ones (`BUILTIN_PLUGINS`; the worker has its own, see `cpbenchy.worker.runtime`)
  2. installed packages, through the `cpbenchy` entry-point group (unless CPBENCHY_DISABLE_PLUGIN_AUTOLOAD)
  3. `cpbenchy_conf.py` in the current directory
  4. `-p REF` on the command line and `plugins=` in the API (a module, `module:Class`, `file.py`, or an object)
`-p no:NAME` blocks a plugin by name, built-in ones included (in the worker too).
"""

import argparse
import inspect
import json
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pluggy
from rich_argparse import RichHelpFormatter

if sys.version_info >= (3, 11):
    import tomllib
else:  # the same parser, as a package
    import tomli as tomllib

from cpbenchy import hookspecs, refs
from cpbenchy.errors import UsageError
from cpbenchy.observer import WORKER_CALLBACKS, Observer, ObserverPlugin, overrides
from cpbenchy.rules import Rules
from cpbenchy.worker import hookspecs as worker_hookspecs

BUILTIN_PLUGINS = {
    "session": "cpbenchy.session",
    "collect": "cpbenchy.collect",
    "executors": "cpbenchy.executors",
    "solutions": "cpbenchy.solutions",
    "terminal": "cpbenchy.terminal",
}
CORE_GROUPS = {"run": "what to run", "execution": None, "selection": "which instances to run", "output": None}
CONF_FILE = "cpbenchy_conf.py"
CONFIG_FILE = "cpbenchy.toml"
ENTRY_POINT_GROUP = "cpbenchy"


__all__ = ["Config", "Parser", "UsageError", "make_config"]


class Parser:
    """What `cpbenchy_addoption` gets: argparse, with options grouped per plugin in the help."""

    def __init__(self, argparser: argparse.ArgumentParser):
        self._argparser = argparser
        self._groups: dict[str, Any] = {}

    def getgroup(self, name: str, description: str | None = None) -> "OptionGroup":
        if name not in self._groups:
            self._groups[name] = OptionGroup(self._argparser.add_argument_group(name, description))
        return self._groups[name]

    def addoption(self, *args: Any, **kwargs: Any) -> None:
        self.getgroup("plugins").addoption(*args, **kwargs)


class OptionGroup:
    def __init__(self, group: Any):
        self._group = group

    def addoption(self, *args: Any, **kwargs: Any) -> None:
        self._group.add_argument(*args, **kwargs)


class Config:
    """The parsed options and the plugin manager, shared by all hooks of a session."""

    def __init__(
        self,
        pluginmanager: pluggy.PluginManager,
        options: argparse.Namespace,
        sources: list[Any],
        rules: Rules | None = None,
        deviations: dict[str, Any] | None = None,
    ):
        self.pluginmanager = pluginmanager
        self.hook = pluginmanager.hook
        self.options = options
        self.sources = sources
        self.rules = rules  # the rules the session follows (`--rules`), if any
        self.deviations = deviations or {}  # the rules' settings that options changed: {key: value used}

    @property
    def rules_label(self) -> str | None:
        """What results record as their rules: the name, "<name> (modified)" if options changed them."""
        return self.rules.label(self.deviations) if self.rules else None

    def getoption(self, name: str, default: Any = None) -> Any:
        return getattr(self.options, name, default)

    @property
    def blocked(self) -> list[str]:
        return list(self.options.blocked)

    def worker_plugins(self) -> list[str]:
        """References for the worker to load: every registered plugin with a worker hook."""
        return [ref for ref, _ in self._worker_plugin_refs()]

    def worker_pythonpath(self) -> list[str]:
        """Directories the worker needs on its path to import the worker plugins by name."""
        return list(dict.fromkeys(root for _, root in self._worker_plugin_refs() if root))

    def worker_options(self) -> dict[str, Any]:
        """The options the worker gets as `ctx.options`: all JSON-safe ones."""
        options = {}
        for key, value in vars(self.options).items():
            try:
                json.dumps(value)
            except TypeError:
                continue
            options[key] = value
        return options

    def _worker_plugin_refs(self) -> list[tuple[str, str | None]]:
        refs_ = []
        for name, plugin in self.pluginmanager.list_name_plugin():
            if isinstance(plugin, ObserverPlugin):
                if overrides(plugin.observer, WORKER_CALLBACKS):
                    refs_.append(refs.ref_for(plugin.observer))
            elif name not in BUILTIN_PLUGINS:
                callers = self.pluginmanager.get_hookcallers(plugin) or []
                if any(c.name.startswith("cpbenchy_worker_") for c in callers):
                    refs_.append(refs.ref_for(plugin))
        return refs_


def _preparse(args: Sequence[str]) -> tuple[list[str], list[str]]:
    """The `-p` options, needed before the full parser exists: (plugins to load, names to block)."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("-p", dest="plugins", action="append", default=[])
    known, _ = pre.parse_known_args(list(args))
    load = [p for p in known.plugins if not p.startswith("no:")]
    return load, [p[3:] for p in known.plugins if p.startswith("no:")]


def _preparse_rules(args: Sequence[str]) -> str | None:
    """The `--rules` option, needed before the full parser exists: rules may add plugins."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--rules")
    known, _ = pre.parse_known_args(list(args))
    return known.rules


def register(pm: pluggy.PluginManager, plugin: Any, name: str | None = None) -> None:
    """Register a plugin: a module (with its Observer classes, each with default arguments), an observer
    (or an Observer class), or any other object with hook functions."""
    if inspect.isclass(plugin) and issubclass(plugin, Observer):
        plugin = plugin()
    if isinstance(plugin, Observer):
        name = name or type(plugin).__name__
        if pm.is_blocked(name) or pm.is_blocked(type(plugin).__name__):
            return
        unique, n = name, 1
        while pm.has_plugin(unique):
            n += 1
            unique = f"{name}#{n}"
        pm.register(ObserverPlugin(plugin), unique)
        return
    if name and pm.is_blocked(name):
        return
    if not pm.is_registered(plugin):
        pm.register(plugin, name)
    if inspect.ismodule(plugin):
        for cls in _observer_classes(plugin):
            register(pm, cls)


def _observer_classes(module: Any) -> list[type]:
    """The Observer subclasses a module defines (not those it imports), except those starting with `_`."""
    return [
        cls
        for cls in vars(module).values()
        if inspect.isclass(cls)
        and issubclass(cls, Observer)
        and cls.__module__ == module.__name__
        and not cls.__name__.startswith("_")
    ]


def plugin_manager(plugins: Iterable[Any] = (), blocked: Iterable[str] = (), autoload: bool = True):
    pm = pluggy.PluginManager("cpbenchy")
    pm.add_hookspecs(hookspecs)
    pm.add_hookspecs(worker_hookspecs)  # so plugins implementing worker hooks validate in the parent too
    for name in blocked:
        pm.set_blocked(name)
    for name, module in BUILTIN_PLUGINS.items():
        if not pm.is_blocked(name):
            pm.register(refs.load(module), name)
    if autoload and not os.environ.get("CPBENCHY_DISABLE_PLUGIN_AUTOLOAD"):
        pm.load_setuptools_entrypoints(ENTRY_POINT_GROUP)
        for plugin, _ in pm.list_plugin_distinfo():
            if inspect.ismodule(plugin):
                for cls in _observer_classes(plugin):
                    register(pm, cls)
    conf = Path.cwd() / CONF_FILE
    if conf.exists() and not pm.is_blocked(CONF_FILE):
        register(pm, refs.load(str(conf)), CONF_FILE)
    for plugin in plugins:
        if isinstance(plugin, str):
            if not pm.is_blocked(plugin):
                register(pm, refs.load(plugin), plugin if refs.parse(plugin)[1] == "" else None)
        else:
            register(pm, plugin)
    return pm


def make_parser(pm: pluggy.PluginManager, prog: str = "cpbenchy run") -> argparse.ArgumentParser:
    argparser = argparse.ArgumentParser(prog=prog, formatter_class=RichHelpFormatter)
    argparser.add_argument(
        "-p",
        dest="plugins",
        action="append",
        default=[],
        metavar="PLUGIN",
        help="load a plugin (module, module:Class, or file.py); -p no:NAME disables plugin NAME",
    )
    argparser.add_argument(
        "--rules",
        metavar="RULES",
        help="follow these rules: a built-in name (see `cpbenchy rules`) or a .toml file; options you give "
        "explicitly still win",
    )
    parser = Parser(argparser)
    for name, description in CORE_GROUPS.items():  # so they come first in the help
        parser.getgroup(name, description)
    pm.hook.cpbenchy_addoption.call_historic(kwargs={"parser": parser})
    return argparser


def read_config_file(directory: Path | None = None) -> dict[str, Any]:
    """Option defaults from `cpbenchy.toml`, or else `[tool.cpbenchy]` in `pyproject.toml`."""
    directory = directory or Path.cwd()
    if (directory / CONFIG_FILE).exists():
        return tomllib.loads((directory / CONFIG_FILE).read_text())
    if (directory / "pyproject.toml").exists():
        return tomllib.loads((directory / "pyproject.toml").read_text()).get("tool", {}).get("cpbenchy", {})
    return {}


def _dests(parser: argparse.ArgumentParser) -> dict[str, str]:
    """Config file key -> option dest: long option names (`time-limit`) and dests (`time_limit`) both work."""
    dests = {}
    for action in parser._actions:
        dests[action.dest] = action.dest
        for option in action.option_strings:
            if option.startswith("--"):
                dests[option[2:]] = action.dest
    return dests


def make_config(
    args: Sequence[str] = (),
    *,
    sources: Sequence[Any] = (),
    plugins: Iterable[Any] = (),
    defaults: dict[str, Any] | None = None,
    prog: str = "cpbenchy run",
    **overrides: Any,
) -> Config:
    """Set up plugins and options: `overrides` (the API's keyword arguments) over `args` (command line) over
    `defaults` (from a config file, where `plugins` is a list of `-p` values) over the options' defaults."""
    defaults = dict(defaults or {})
    rules_ref = overrides.pop("rules", None) or _preparse_rules(args) or defaults.pop("rules", None)
    defaults.pop("rules", None)
    rules = Rules.load(rules_ref) if rules_ref else None
    if rules:  # over the config file's defaults; plugins add up
        settings = dict(rules.settings)
        defaults["plugins"] = [*defaults.get("plugins", []), *settings.pop("plugins", [])]
        defaults.update(settings)
    load, blocked = _preparse([*(f"-p{p}" for p in defaults.pop("plugins", [])), *args])
    pm = plugin_manager([*load, *plugins], blocked)
    parser = make_parser(pm, prog)
    options = parser.parse_args(list(args))
    dests = _dests(parser)
    for key, value in defaults.items():
        dest = dests.get(key)
        if dest is None:
            where = f"the rules {rules.path or rules.name}" if rules and key in rules.settings else CONFIG_FILE
            raise UsageError(f"unknown option {key!r} in {where} (or [tool.cpbenchy])")
        if getattr(options, dest) == parser.get_default(dest):  # not given on the command line
            setattr(options, dest, value)
    options.blocked = blocked
    for key, value in overrides.items():
        if not hasattr(options, key):
            raise UsageError(f"unknown option {key!r}")
        setattr(options, key, value)
    deviations = _deviations(rules, options, dests, blocked) if rules else {}
    options.rules = rules.name if rules else None
    config = Config(pm, options, [*getattr(options, "sources", []), *sources], rules, deviations)
    pm.hook.cpbenchy_configure.call_historic(kwargs={"config": config})
    return config


# Settings that change how results are reported, not what runs measure: changing them leaves the rules followed.
REPORTING = ("par",)


def _deviations(rules: Rules, options: argparse.Namespace, dests: dict[str, str], blocked: list[str]) -> dict:
    """The rules' settings that the options don't follow: {key: the value used instead}."""
    deviations = {}
    for key, value in rules.settings.items():
        if key in REPORTING:
            continue
        if key == "plugins":
            off = [ref for ref in value if ref in blocked or ref.rpartition(":")[2].split("(")[0] in blocked]
            if off:
                deviations["plugins"] = f"disabled {', '.join(off)}"
        elif getattr(options, dests[key]) != value:
            deviations[key] = getattr(options, dests[key])
    if getattr(options, "scale", 1) != 1:
        deviations["scale"] = options.scale
    return deviations
