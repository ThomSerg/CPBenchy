"""Competition submissions: a self-contained directory (or archive) that a competition runs as a solver.

    cpbenchy submission init --rules xcsp3-2025 --rules xcsp3-2025-fast -s ortools   # writes submission.toml
    cpbenchy submission build submission.toml --archive zip --test

A submission is described in TOML:

    name = "cpmpy-{solver}"                 # {solver} is replaced, so one file serves several solvers
    description = "CPMpy, with {solver} as its backend"
    authors = ["..."]
    solver = "ortools"
    params = {}                             # solver parameters, as -P
    plugins = []                            # extra plugins: module references, or .py files (bundled)
    loader = "..."                          # optional, as --loader (a .py file is bundled)
    requirements = ["pycsp3"]               # extra packages; unpinned ones get the version installed here
    include = ["doc/description.pdf"]       # files or directories to copy in, relative to this file

    [[tracks]]
    name = "COP"
    rules = "xcsp3-2025"                    # limits, output and how the competition calls the solver
    test = ["instances/small.xml"]          # instances for `build --test`
    # solver, params, arguments: to override the above or the rules' [interface] for this track

What it builds:

    <name>/
      bin/run_<track>   launchers: take the competition's placeholders (the rules' [interface] arguments,
                        e.g. BENCHNAME RANDOMSEED TIMELIMIT ...), and exec `python -m cpbenchy solve`
      install.sh        run once where it will run: makes .venv with requirements.txt (from wheels/ if bundled)
      requirements.txt  the packages, pinned to the versions this was built and tested with
      code/             cpbenchy itself (and CPMpy if installed from a local source), and bundled plugins
      rules/            the rules of each track, so the submission does not depend on this cpbenchy
      README.md         what to register with the competition: the command line of each track
      build.json        how it was built: versions, the submission file, the rules
      ...               the included files

Launchers exec Python, so the competition's signals reach the solver process directly, and `solve` prints
its output to stdout and stops at its limit or on SIGTERM with the best solution found (`--terminate`).
"""

import argparse
import importlib.metadata as metadata
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # the same parser, as a package
    import tomli as tomllib

import cpbenchy
from cpbenchy.config import UsageError
from cpbenchy.rules import Rules
from cpbenchy.worker import THREAD_ENV

# placeholder -> how `cpbenchy solve` takes it: an option, "instance" (the positional argument), or "env:NAME"
PLACEHOLDERS = {
    "BENCHNAME": "instance",
    "RANDOMSEED": "--seed",
    "TIMELIMIT": "time",  # --cpu-time-limit if the rules limit CPU time, else --time-limit
    "TIMEOUT": "time",
    "WALLTIMELIMIT": "--time-limit",
    "MEMLIMIT": "--mem-limit",
    "NBCORE": "--cores",
    "NBCORES": "--cores",
    "TMPDIR": "env:TMPDIR",
}
"""The placeholders competitions (XCSP3, PB, ...) substitute in a solver's command line. A track's
`arguments` may map others, or these differently, as "NAME=--option" (or "NAME=" to ignore one)."""

# CPMpy solver name -> the packages it needs
SOLVER_PACKAGES = {
    "ortools": ["ortools"],
    "exact": ["exact"],
    "gurobi": ["gurobipy"],
    "highs": ["highspy"],
    "pindakaas": ["pindakaas"],
    "choco": ["pychoco"],
    "z3": ["z3-solver"],
    "cpo": ["docplex"],
    "cplex": ["docplex", "cplex"],
    "scip": ["pyscipopt"],
    "pysat": ["python-sat"],
    "minizinc": ["minizinc"],
    "hexaly": ["hexaly"],
    "pumpkin": ["pumpkin-solver"],
    "pysdd": ["pysdd"],
}

RUNTIME_PACKAGES = ["pluggy", "rich", "rich-argparse", "packaging"]
"""What `cpbenchy solve` needs besides CPMpy (not BenchExec: the competition measures the runs)."""

TOMLI = 'tomli>=1.1; python_version < "3.11"'
MARKER = "build.json"
DEFAULT_TEST_TIME = 20


@dataclass
class Track:
    name: str
    rules: Rules
    solver: str
    params: dict[str, Any] = field(default_factory=dict)
    arguments: list[str] = field(default_factory=list)
    test: list[Path] = field(default_factory=list)


@dataclass
class Submission:
    name: str
    description: str
    authors: list[str]
    solver: str
    tracks: list[Track]
    plugins: list[str] = field(default_factory=list)
    loader: str | None = None
    requirements: list[str] = field(default_factory=list)
    include: list[Path] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)  # the submission file, as read
    base: Path = Path(".")  # what relative paths in it are relative to

    @classmethod
    def load(cls, path: str | Path, solver: str | None = None) -> "Submission":
        """From a submission file; `solver` replaces its `solver` (for one file, several submissions)."""
        path = Path(path)
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise UsageError(f"can't read the submission {path}: {e}") from e
        return cls.from_dict(data, path.parent, solver)

    @classmethod
    def from_dict(cls, data: dict[str, Any], base: Path, solver: str | None = None) -> "Submission":
        known = {"name", "description", "authors", "solver", "params", "plugins", "loader", "requirements"}
        unknown = set(data) - known - {"include", "tracks"}
        if unknown:
            raise UsageError(f"unknown keys in the submission: {', '.join(sorted(unknown))}")
        solver = solver or data.get("solver")
        if not solver or not data.get("name") or not data.get("tracks"):
            raise UsageError("a submission needs a `name`, a `solver` and at least one [[tracks]]")
        tracks = []
        for t in data["tracks"]:
            if "name" not in t or "rules" not in t:
                raise UsageError("each [[tracks]] needs a `name` and `rules`")
            rules_ref = t["rules"]
            rules = Rules.load(base / rules_ref if str(rules_ref).endswith(".toml") else rules_ref)
            arguments = list(t.get("arguments", rules.interface.get("arguments", [])))
            if not arguments:
                raise UsageError(
                    f"track {t['name']}: its rules {rules.name} don't say how the competition calls a solver; "
                    'give the track `arguments`, e.g. ["BENCHNAME", "TIMELIMIT"]'
                )
            track_solver = t.get("solver", solver)
            params = {**data.get("params", {}), **t.get("params", {})}
            tests = [base / p for p in t.get("test", [])]
            tracks.append(Track(t["name"], rules, track_solver, params, arguments, tests))
        fmt = {"solver": solver}
        return cls(
            name=data["name"].format(**fmt),
            description=data.get("description", "").format(**fmt),
            authors=list(data.get("authors", [])),
            solver=solver,
            tracks=tracks,
            plugins=list(data.get("plugins", [])),
            loader=data.get("loader"),
            requirements=list(data.get("requirements", [])),
            include=[base / p for p in data.get("include", [])],
            source=data,
            base=base,
        )


# --- building ---


def build(sub: Submission, out: Path, *, wheels: bool = False, force: bool = False) -> Path:
    """Write the submission to `out`, and return it."""
    if out.exists() and any(out.iterdir()):
        if not force:
            raise UsageError(f"{out} exists; pass --force to replace it")
        if not (out / MARKER).exists():
            raise UsageError(f"{out} is not a submission built by cpbenchy ({MARKER} missing); not replacing it")
        shutil.rmtree(out)
    for d in ("bin", "code", "rules"):
        (out / d).mkdir(parents=True, exist_ok=True)

    vendored = _vendor(out / "code")
    bundled = {ref: _bundle(sub.base, ref, out / "code") for ref in [*sub.plugins, sub.loader] if ref}
    for track in sub.tracks:
        rules_file = out / "rules" / f"{track.rules.name}.toml"
        if not rules_file.exists():
            _copy_rules(track.rules, rules_file, sub.base, out / "code", bundled)
        launcher = out / "bin" / f"run_{track.name}"
        launcher.write_text(_launcher(sub, track, rules_file.name, bundled))
        launcher.chmod(0o755)
    for path in sub.include:
        if not path.exists():
            raise UsageError(f"can't include {path}: it doesn't exist")
        target = out / path.relative_to(sub.base) if path.is_relative_to(sub.base) else out / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if path.is_dir() else shutil.copy2)(path, target)

    pins, warnings = requirements(sub, vendored)
    (out / "requirements.txt").write_text("".join(f"{p}\n" for p in pins))
    if wheels:
        _download_wheels(out / "requirements.txt", out / "wheels")
    install = out / "install.sh"
    install.write_text(INSTALL.format(name=sub.name))
    install.chmod(0o755)
    (out / "README.md").write_text(_readme(sub, pins))
    info = {
        "name": sub.name,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cpbenchy": cpbenchy.__version__,
        "python": sys.version.split()[0],
        "vendored": vendored,
        "requirements": pins,
        "submission": sub.source,
        "tracks": {
            t.name: {"rules": t.rules.to_dict(), "solver": t.solver, "arguments": t.arguments} for t in sub.tracks
        },
    }
    (out / MARKER).write_text(json.dumps(info, indent=2, default=str) + "\n")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return out


def requirements(sub: Submission, vendored: list[str]) -> tuple[list[str], list[str]]:
    """The packages to install, pinned to the versions installed here, dependencies included (like a lock
    file): what `cpbenchy solve` needs, the solvers', and the submission's own. And warnings, about what is
    not installed here."""
    roots = list(RUNTIME_PACKAGES)
    if "cpmpy" in vendored:  # its dependencies, not itself
        roots += [_requirement(r).name for r in metadata.requires("cpmpy") or [] if _applies(r)]
    else:
        roots.append("cpmpy")
    for track in sub.tracks:
        roots += SOLVER_PACKAGES.get(track.solver.split(":")[0], [])
    warnings = []
    unknown = {t.solver for t in sub.tracks if t.solver.split(":")[0] not in SOLVER_PACKAGES}
    if unknown:
        warnings.append(f"don't know the packages of solver(s) {', '.join(sorted(unknown))}: add them to requirements")
    pins: dict[str, str] = {}
    raw = []
    for req in sub.requirements:  # as given, if not installed here
        name = _requirement(req).name
        if _installed(name):
            roots.append(name)
        else:
            raw.append(req)
            warnings.append(f"{req} is not installed here: not pinned, and not tested with")
    stack = list(roots)
    while stack:
        name = stack.pop()
        key = _canonical(name)
        if key in pins or key in vendored:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            raw.append(name)
            warnings.append(f"{name} is not installed here: not pinned, and not tested with")
            continue
        pins[key] = f"{dist.metadata['Name']}=={dist.version}"
        stack += [_requirement(r).name for r in dist.requires or [] if _applies(r)]
    if "tomli" not in pins:  # what cpbenchy reads TOML with on Python 3.10, wherever this is built
        raw.append(TOMLI)
    return sorted(pins.values(), key=str.lower) + sorted(set(raw)), warnings


def _requirement(text: str):
    from packaging.requirements import Requirement  # a dependency of CPMpy

    return Requirement(text)


def _applies(text: str) -> bool:
    """Whether a dependency applies here (its environment marker holds), extras aside."""
    marker = _requirement(text).marker
    return marker is None or marker.evaluate({"extra": ""})


def _installed(name: str) -> bool:
    try:
        metadata.distribution(name)
        return True
    except metadata.PackageNotFoundError:
        return False


def _canonical(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _vendor(code: Path) -> list[str]:
    """Copy cpbenchy into `code`, and CPMpy if it is installed from a local source (a fork, a checkout)."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "testing")
    shutil.copytree(Path(cpbenchy.__file__).parent, code / "cpbenchy", ignore=ignore)
    vendored = ["cpbenchy"]
    try:
        direct = metadata.distribution("cpmpy").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        direct = None
    if direct and json.loads(direct).get("url", "").startswith("file:"):
        import cpmpy

        shutil.copytree(Path(cpmpy.__file__).parent, code / "cpmpy", ignore=ignore)
        vendored.append("cpmpy")
    return vendored


def _bundle(base: Path, ref: str, code: Path) -> str:
    """A plugin or loader reference that works in the submission: .py files are copied into `code`, and
    referred to from the launcher's root ($ROOT)."""
    target, sep, attr = ref.partition(":")
    if not target.endswith(".py"):
        return ref
    path = (base / target).resolve()
    if not path.exists():
        raise UsageError(f"can't bundle {target}: {path} doesn't exist")
    shutil.copy2(path, code / path.name)
    return f"$ROOT/code/{path.name}{sep}{attr}"


def _copy_rules(rules: Rules, target: Path, base: Path, code: Path, bundled: dict[str, str]) -> None:
    """The rules, for the submission. Plugins from .py files are bundled, and given on the launcher's
    command line instead (rules files can't refer to the submission's directory)."""
    text = Path(rules.path).read_text() if rules.path else ""
    plugins = rules.settings.get("plugins", [])
    files = [p for p in plugins if p.partition(":")[0].endswith(".py")]
    if files:
        for ref in files:
            bundled[ref] = _bundle(base, ref, code)
        data = rules.to_dict()
        data["settings"]["plugins"] = [p for p in plugins if p not in files]
        text = _to_toml(data) + f"\n# plugins from files are given by the launchers: {', '.join(files)}\n"
    target.write_text(text)


def _to_toml(data: dict[str, Any]) -> str:
    def value(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, list):
            return "[" + ", ".join(value(x) for x in v) + "]"
        return json.dumps(str(v))

    lines = [f"{k} = {value(v)}" for k, v in data.items() if not isinstance(v, dict) and v is not None]
    for table in ("settings", "interface"):
        if data.get(table):
            lines += ["", f"[{table}]", *(f"{k} = {value(v)}" for k, v in data[table].items())]
    return "\n".join(lines) + "\n"


def _arguments(track: Track) -> list[tuple[str, str]]:
    """(placeholder, how solve takes it) for each launcher argument."""
    result = []
    for arg in track.arguments:
        name, sep, how = arg.partition("=")
        if not sep:
            if name not in PLACEHOLDERS:
                raise UsageError(f"track {track.name}: unknown placeholder {name}; map it as {name}=--option")
            how = PLACEHOLDERS[name]
        if how == "time":
            how = "--cpu-time-limit" if "cpu-time-limit" in track.rules.settings else "--time-limit"
        result.append((name, how))
    if "instance" not in [how for _, how in result]:
        raise UsageError(f"track {track.name}: its arguments need the instance (BENCHNAME)")
    return result


def _launcher(sub: Submission, track: Track, rules_file: str, bundled: dict[str, str]) -> str:
    args = _arguments(track)
    usage = " ".join(name for name, _ in args)
    exports, cmd = [], []
    for i, (_, how) in enumerate(args, start=1):
        if how == "instance":
            cmd.insert(0, f'"${i}"')
        elif how.startswith("env:"):
            exports.append(f'export {how[4:]}="${i}"')
        elif how:
            cmd.append(f'{how} "${i}"')
    cmd += [f'--rules "$ROOT/rules/{rules_file}"', f"-s {shlex.quote(track.solver)}"]
    for key, val in track.params.items():
        cmd.append("-P " + shlex.quote(f"{key}={json.dumps(val) if not isinstance(val, str) else val}"))
    plugins = [*sub.plugins, *(p for p in track.rules.settings.get("plugins", []) if p in bundled)]
    for ref in plugins:
        cmd.append(f'-p "{bundled.get(ref, ref)}"')
    if sub.loader:
        cmd.append(f'--loader "{bundled.get(sub.loader, sub.loader)}"')
    cmd.append("-p no:cpbenchy_conf.py")  # not a cpbenchy_conf.py that happens to be in the working directory
    return LAUNCHER.format(
        name=sub.name,
        track=track.name,
        rules=track.rules.name,
        description=track.rules.description,
        version=cpbenchy.__version__,
        usage=usage,
        n=len(args),
        exports="\n".join(exports),
        threads="\n".join(f'export {k}="${{{k}:-{v}}}"' for k, v in THREAD_ENV.items()),
        cmd=" \\\n    ".join(cmd),
    )


def _readme(sub: Submission, pins: list[str]) -> str:
    rows = []
    for t in sub.tracks:
        args = " ".join(name for name, _ in _arguments(t))
        rows.append(f"| {t.name} | `{t.rules.name}` | {t.solver} | `DIR/bin/run_{t.name} {args}` |")
    authors = f"\nAuthors: {', '.join(sub.authors)}\n" if sub.authors else ""
    return README.format(
        name=sub.name,
        description=sub.description,
        authors=authors,
        tracks="\n".join(rows),
        requirements="\n".join(f"- {p}" for p in pins),
        version=cpbenchy.__version__,
        python=sys.version.split()[0],
    )


def _download_wheels(requirements_file: Path, wheels: Path) -> None:
    cmd = [sys.executable, "-m", "pip", "download", "-r", str(requirements_file), "-d", str(wheels)]
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise UsageError(f"downloading the wheels failed ({e}); does this Python have pip?") from e


# --- testing ---


def test(out: Path, sub: Submission, time_limit: float = DEFAULT_TEST_TIME) -> list[tuple[str, Path, bool, str]]:
    """Run each track's launcher on its test instances, with this Python and the submission's code, as
    the competition would; (track, instance, ok, the output's last lines) for each."""
    outcomes = []
    for track in sub.tracks:
        for instance in track.test:
            values = _test_values(track, instance, time_limit)
            launcher = out / "bin" / f"run_{track.name}"
            env = {**os.environ, "CPBENCHY_PYTHON": sys.executable}
            proc = subprocess.run(
                [str(launcher), *values], capture_output=True, text=True, env=env, timeout=time_limit * 3 + 60
            )
            answers = [line for line in proc.stdout.splitlines() if line.startswith("s ")]
            ok = proc.returncode == 0 and len(answers) == 1
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
            outcomes.append((track.name, instance, ok, tail))
    return outcomes


def _test_values(track: Track, instance: Path, time_limit: float) -> list[str]:
    settings = track.rules.settings
    values = {
        "instance": str(instance),
        "--seed": "1",
        "--cpu-time-limit": str(time_limit),
        "--time-limit": str(time_limit),
        "--mem-limit": str(settings.get("mem-limit", 4096)),
        "--cores": str(settings.get("cores", 1)),
        "env:TMPDIR": tempfile.mkdtemp(prefix="cpbenchy-test-"),
    }
    return [values.get(how, "") for _, how in _arguments(track)]


# --- templates ---

LAUNCHER = """\
#!/bin/bash
# {name}, track {track}: rules {rules} ({description}).
# Generated by cpbenchy {version}. The competition calls it as:
#   run_{track} {usage}
set -euo pipefail
ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
PYTHON="${{CPBENCHY_PYTHON:-$ROOT/.venv/bin/python}}"
if [ "$#" -ne {n} ]; then
    echo "usage: $0 {usage}" >&2
    exit 2
fi
if [ ! -x "$PYTHON" ] && ! command -v "$PYTHON" >/dev/null; then
    echo "c not installed: run $ROOT/install.sh first"
    echo "s UNKNOWN"
    exit 1
fi
export PYTHONPATH="$ROOT/code${{PYTHONPATH:+:$PYTHONPATH}}"
export CPBENCHY_DISABLE_PLUGIN_AUTOLOAD=1
{threads}
{exports}
exec "$PYTHON" -m cpbenchy solve {cmd}
"""

INSTALL = """\
#!/bin/bash
# Install {name}: a Python environment in .venv with requirements.txt (from wheels/ if it is there, else
# from PyPI). Run it once, where the submission will run. PYTHON=... chooses the Python (3.10 or newer).
set -euo pipefail
ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
PYTHON="${{PYTHON:-python3}}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "install.sh: needs Python 3.10 or newer; choose one with PYTHON=..." >&2
    exit 1
fi
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    "$PYTHON" -m venv "$ROOT/.venv" 2>/dev/null || virtualenv -p "$PYTHON" "$ROOT/.venv"
fi
PIP=("$ROOT/.venv/bin/python" -m pip install)
if [ -d "$ROOT/wheels" ]; then
    PIP+=(--no-index --find-links "$ROOT/wheels")
fi
"${{PIP[@]}}" -r "$ROOT/requirements.txt"
echo "{name} is installed; the launchers are in $ROOT/bin"
"""

README = """\
# {name}

{description}
{authors}
## Install

Once, on the machine where it will run (Python 3.10 or newer, `PYTHON=...` to choose one):

```sh
./install.sh
```

## Tracks

Register each track with the command line below, where `DIR` is the directory of this submission and the
other words are the competition's placeholders.

| Track | Rules | Solver | Command line |
|---|---|---|---|
{tracks}

Each launcher runs `python -m cpbenchy solve` on the instance. It prints the competition's output on
stdout: `o` lines for each better solution, then `s` and `v` lines. At the time limit, or on SIGTERM, it
prints the best solution found so far. The rules of each track are in `rules/`.

## Built with

cpbenchy {version}, Python {python}. Packages:

{requirements}

`build.json` records how this submission was built.
"""

TEMPLATE = """\
# A competition submission: `cpbenchy submission build {path}`
name = "cpmpy-{{solver}}"
description = "CPMpy, with {{solver}} as its backend"
authors = []
solver = "{solver}"
params = {{}}
requirements = [{requirements}]
include = []                     # e.g. the solver description: ["doc/description.pdf"]
{tracks}"""


def init(path: Path, rules: Sequence[str], solver: str) -> None:
    if path.exists():
        raise UsageError(f"{path} exists")
    tracks = []
    for ref in rules or ["xcsp3-2025"]:
        r = Rules.load(ref)
        tracks.append(f'\n[[tracks]]\nname = "{r.name}"\nrules = "{ref}"\ntest = []\n')
    xcsp3 = any("XCSP3" in p for ref in rules for p in Rules.load(ref).settings.get("plugins", []))
    path.write_text(
        TEMPLATE.format(
            path=path, solver=solver, requirements='"pycsp3"' if xcsp3 or not rules else "", tracks="".join(tracks)
        )
    )


# --- command line ---


def main(args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="cpbenchy submission", description="Build competition submissions.")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init", help="write a submission file to start from")
    p.add_argument("file", nargs="?", default="submission.toml")
    p.add_argument("--rules", action="append", default=[], help="a track per rules (repeatable)")
    p.add_argument("-s", "--solver", default="ortools")
    p = commands.add_parser("build", help="build a submission")
    p.add_argument("file", nargs="?", default="submission.toml")
    p.add_argument("-s", "--solver", help="build it for this solver instead of the file's")
    p.add_argument("-o", "--out", help="output directory (default: the submission's name)")
    p.add_argument("--archive", choices=["zip", "gztar", "tar"], help="also pack it into an archive")
    p.add_argument("--wheels", action="store_true", help="bundle the packages' wheels, to install offline")
    p.add_argument("--force", action="store_true", help="replace an earlier build")
    p.add_argument("--test", action="store_true", help="then run each track on its test instances")
    p.add_argument("--test-time", type=float, default=DEFAULT_TEST_TIME, help="time limit of the tests")
    options = parser.parse_args(args)

    if options.command == "init":
        init(Path(options.file), options.rules, options.solver)
        print(f"wrote {options.file}; edit it, then: cpbenchy submission build {options.file}")
        return 0
    sub = Submission.load(options.file, options.solver)
    out = build(sub, Path(options.out or sub.name), wheels=options.wheels, force=options.force)
    print(f"built {out}")
    for track in sub.tracks:
        args_ = " ".join(name for name, _ in _arguments(track))
        print(f"  {track.name:20} DIR/bin/run_{track.name} {args_}")
    failed = 0
    if options.test:
        outcomes = test(out, sub, options.test_time)
        if not outcomes:
            print("no test instances: give tracks `test = [...]`")
        for track_name, instance, ok, tail in outcomes:
            print(f"  {'ok  ' if ok else 'FAIL'} {track_name} {instance}")
            if not ok:
                failed += 1
                print("    " + tail.replace("\n", "\n    "))
    if options.archive:
        archive = shutil.make_archive(str(out), options.archive, root_dir=out.parent, base_dir=out.name)
        print(f"archive {archive}")
    return 1 if failed else 0
