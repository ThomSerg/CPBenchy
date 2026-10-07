"""The `cpbenchy` command line: `cpbenchy COMMAND ...`."""

import sys
from collections.abc import Callable, Sequence

import cpbenchy
from cpbenchy.config import UsageError

USAGE = """\
usage: cpbenchy COMMAND [options]

commands:
  run       run solvers on instances:  cpbenchy run data/*.opb -s ortools -s exact -t 60
  solve     solve one instance here, printing competition output: cpbenchy solve x.xml -s ortools --rules xcsp3-2025
  submission  build a competition submission: cpbenchy submission build submission.toml
  show      show stored results:       cpbenchy show cpbenchy-results
  check     check stored solutions again: cpbenchy check cpbenchy-results
  rules     list the built-in rules, or show one:  cpbenchy rules xcsp3-2025
  plugins   list plugins and the hooks they implement
  doctor    check what this machine supports: runexec limits, CPUs, memory, solvers

`cpbenchy COMMAND --help` shows a command's options (`run` includes those added by plugins).
"""


def cmd_run(args: Sequence[str]) -> int:
    from cpbenchy.config import make_config, read_config_file
    from cpbenchy.session import Session

    session = Session(make_config(args, defaults=read_config_file()))
    try:
        results = session.run()
    except KeyboardInterrupt:
        return 130
    return 1 if any(r.status == "error" for r in results) else 0


def cmd_solve(args: Sequence[str]) -> int:
    from cpbenchy.worker.terminate import block_signals

    block_signals()  # first: solve stops on SIGTERM, and importing CPMpy starts threads
    from cpbenchy.solve import solve

    return solve(args)


def cmd_submission(args: Sequence[str]) -> int:
    from cpbenchy.submission import main

    return main(args)


def cmd_show(args: Sequence[str]) -> int:
    import argparse
    import csv
    import json

    from rich.console import Console

    from cpbenchy.result import Results
    from cpbenchy.terminal import format_result, summary_table

    parser = argparse.ArgumentParser(prog="cpbenchy show", description="Show the results in an output directory.")
    parser.add_argument("out", nargs="?", default="cpbenchy-results", help="output directory (default: %(default)s)")
    parser.add_argument("--by", default="solver", help="comma-separated fields to group by (default: %(default)s)")
    parser.add_argument("--par", type=float, metavar="K", help="add the PAR-K score per group to the summary")
    parser.add_argument("--runs", action="store_true", help="list every run")
    parser.add_argument("--csv", action="store_true", help="print all results as CSV")
    options = parser.parse_args(args)
    results = Results.load(options.out)
    if not results:
        raise UsageError(f"no results in {options.out}")
    if options.csv:
        records = results.to_records()
        fields = list(dict.fromkeys(k for r in records for k in r))
        writer = csv.DictWriter(sys.stdout, fields)
        writer.writeheader()
        for record in records:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in record.items()})
        return 0
    console = Console(highlight=False)
    if options.runs:
        for result in results:
            console.print(format_result(result))
    console.print(summary_table(results, by=options.by.split(","), par=options.par))
    return 0


def cmd_check(args: Sequence[str]) -> int:
    import argparse

    from cpbenchy import refs
    from cpbenchy.check import SOLUTION_FILES, recheck
    from cpbenchy.result import Results
    from cpbenchy.store import Store

    parser = argparse.ArgumentParser(
        prog="cpbenchy check",
        description="Check the solutions of finished runs against their models: each model is loaded again, "
        f"and each solution read from what the run wrote ({', '.join(SOLUTION_FILES)}).",
    )
    parser.add_argument("out", nargs="?", default="cpbenchy-results", help="output directory (default: %(default)s)")
    parser.add_argument("--loader", metavar="REF", help="load the models with this loader instead of the runs' own")
    parser.add_argument("--write", action="store_true", help='store each verdict in results.jsonl, as extra["check"]')
    parser.add_argument("-v", "--verbose", action="store_true", help="list every run, and every violation")
    options = parser.parse_args(args)
    results = Results.load(options.out)
    if not results:
        raise UsageError(f"no results in {options.out}")
    loader = refs.load(options.loader) if options.loader else None

    counts = {"valid": 0, "invalid": 0, "skipped": 0}
    for result, check in recheck(options.out, results, loader):
        verdict = "skipped" if check.skipped is not None else "valid" if check.valid else "invalid"
        counts[verdict] += 1
        if options.verbose or verdict == "invalid":
            print(
                f"{result.run_id}  {result.solver}  {result.instance}: {check if options.verbose else check.summary()}"
            )
        if options.write and check.skipped is None:
            result.extra["check"] = check.to_dict()
    if options.write:
        Store(options.out).rewrite(results)
    print(f"{counts['valid']} valid, {counts['invalid']} invalid, {counts['skipped']} not checked")
    return 1 if counts["invalid"] else 0


def cmd_rules(args: Sequence[str]) -> int:
    import argparse
    from pathlib import Path

    from cpbenchy.rules import Rules, builtin

    parser = argparse.ArgumentParser(
        prog="cpbenchy rules",
        description="List the built-in rules, or show one: copy it to a .toml file to make your own.",
    )
    parser.add_argument("name", nargs="?", help="a built-in name or a .toml file")
    options = parser.parse_args(args)
    if options.name is None:
        for rules in builtin():
            print(f"{rules.name:24} {rules.description}")
        print("\n`cpbenchy rules NAME` shows one; `cpbenchy run ... --rules NAME` (or FILE.toml) follows it.")
        return 0
    rules = Rules.load(options.name)
    print(Path(rules.path).read_text() if rules.path else rules.to_dict(), end="")
    return 0


def cmd_plugins(args: Sequence[str]) -> int:
    from cpbenchy.config import make_config
    from cpbenchy.worker.runtime import plugin_manager as worker_plugin_manager

    config = make_config(args)
    pm = config.pluginmanager
    print("parent:")
    for name, plugin in pm.list_name_plugin():
        hooks = sorted(c.name for c in pm.get_hookcallers(plugin) or [])
        print(f"  {name}: {', '.join(hooks) or '-'}")
    print("worker:")
    wpm = worker_plugin_manager(config.worker_plugins(), config.blocked)
    for name, plugin in wpm.list_name_plugin():
        hooks = sorted(c.name for c in wpm.get_hookcallers(plugin) or [])
        print(f"  {name}: {', '.join(hooks) or '-'}")
    return 0


def cmd_doctor(args: Sequence[str]) -> int:
    from importlib.metadata import version

    from cpmpy import SolverLookup

    from cpbenchy.executors import runexec_problem
    from cpbenchy.scheduling import topology, total_memory_mib

    print(f"cpbenchy {cpbenchy.__version__}, cpmpy {version('cpmpy')}, python {sys.version.split()[0]}")
    problem = runexec_problem()
    if problem is None:
        print("runexec:  ok, runs get cgroup limits and measurements (executor: runlimit)")
    else:
        print(f"runexec:  NOT usable: {problem}")
        print("          runs fall back to the subprocess executor: no memory limit, unreliable measurements.")
        print("          BenchExec needs cgroups v2 with delegation, see")
        print("          https://github.com/sosy-lab/benchexec/blob/main/doc/INSTALL.md")
    siblings, node_of = topology()
    physical = len({tuple(s) for s in siblings.values()})
    print(
        f"machine:  {len(siblings)} CPUs, {physical} physical cores, {len(set(node_of.values()))} NUMA node(s), "
        f"{total_memory_mib()} MiB memory"
    )
    installed, missing = [], []
    for name, cls in SolverLookup.base_solvers():
        try:
            ok = cls.supported()
        except Exception:
            ok = False
        if ok:
            installed.append(f"{name} {cls.version() if hasattr(cls, 'version') else ''}".strip())
        else:
            missing.append(name)
    print(f"solvers:  {', '.join(installed) or 'none'}")
    print(f"          not installed: {', '.join(missing)}")
    return 0 if problem is None else 1


COMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "run": cmd_run,
    "solve": cmd_solve,
    "submission": cmd_submission,
    "show": cmd_show,
    "check": cmd_check,
    "rules": cmd_rules,
    "plugins": cmd_plugins,
    "doctor": cmd_doctor,
}


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    if argv[0] == "--version":
        print(f"cpbenchy {cpbenchy.__version__}")
        return 0
    command = COMMANDS.get(argv[0])
    if command is None:
        print(f"cpbenchy: unknown command {argv[0]!r}\n\n{USAGE}", end="", file=sys.stderr)
        return 2
    try:
        return command(argv[1:])
    except UsageError as e:
        print(f"cpbenchy: error: {e}", file=sys.stderr)
        return 2
