"""Rules: a named, shareable experiment setup, such as a competition track's.

A rules file is TOML: what the rules are, and the settings they fix, by the long names of `cpbenchy run`'s
options (as in `cpbenchy.toml`):

    name = "xcsp3-2025"
    description = "XCSP3 Competition 2025, sequential tracks"
    url = "https://arxiv.org/abs/2511.06918"

    [settings]
    time-limit = 2700          # wall clock, seconds
    cpu-time-limit = 1800
    mem-limit = 65536          # MiB
    terminate = true           # stopped at the limit: report the best solution ...
    grace = 1                  # ... and SIGKILL 1 s later
    plugins = ["cpbenchy.observers:XCSP3Output"]

    [interface]                # how the competition calls a solver: `cpbenchy submission` builds launchers
    arguments = ["BENCHNAME", "RANDOMSEED", "TIMELIMIT", "MEMLIMIT", "NBCORE", "TMPDIR"]

Run with them as `cpbenchy run DIR -s ortools --rules xcsp3-2025` (a built-in name, see `cpbenchy
rules`) or `--rules my-setup.toml`, `rules=` in Python, or `rules = "..."` in `cpbenchy.toml`. Options given
explicitly still win, but the run then records its rules as "<name> (modified)", and `run.json` says what
differs.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # the same parser, as a package
    import tomli as tomllib

from cpbenchy.errors import UsageError

BUILTIN = Path(__file__).parent
"""Where the built-in rules are: `<name>.toml`."""


@dataclass
class Rules:
    name: str
    settings: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    url: str | None = None
    path: str | None = None  # the file they came from
    interface: dict[str, Any] = field(default_factory=dict)  # how a competition calls a solver; see submission

    @classmethod
    def load(cls, ref: "str | Path | Rules") -> "Rules":
        """Rules from a built-in name (`xcsp3-2025-cop`) or a `.toml` file."""
        if isinstance(ref, Rules):
            return ref
        path = Path(ref)
        if path.suffix != ".toml":
            path = BUILTIN / f"{ref}.toml"
            if not path.exists():
                known = ", ".join(r.name for r in builtin())
                raise UsageError(f"no rules named {ref!r}; built in: {known} (or give a .toml file)")
        elif not path.exists():
            raise UsageError(f"no rules file {ref}")
        return cls.from_toml(path.read_text(), str(path))

    @classmethod
    def from_toml(cls, text: str, path: str | None = None) -> "Rules":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise UsageError(f"can't read the rules in {path or 'the text'}: {e}") from e
        unknown = set(data) - {"name", "description", "url", "settings", "interface"}
        if unknown or "name" not in data:
            raise UsageError(
                f"rules {path or ''} need a `name`, and may have `description`, `url`, and [settings] and "
                f"[interface] tables; unknown: {', '.join(sorted(unknown)) or '-'}"
            )
        return cls(
            data["name"],
            dict(data.get("settings", {})),
            data.get("description", ""),
            data.get("url"),
            path,
            dict(data.get("interface", {})),
        )

    def label(self, deviations: dict[str, Any]) -> str:
        """What results record as their rules."""
        return f"{self.name} (modified)" if deviations else self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "settings": self.settings,
            "interface": self.interface,
        }


def builtin() -> list[Rules]:
    """The rules that come with cpbenchy."""
    return sorted((Rules.load(path) for path in BUILTIN.glob("*.toml")), key=lambda r: r.name)
