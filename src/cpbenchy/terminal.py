"""Built-in plugin: progress and results in the terminal.

On a terminal, a live view shows progress and the active runs with their latest objective; finished runs
are printed above it with `-v` (errors always). Elsewhere (logs, CI) each finished run is one line. At the
end: a summary per solver. `-q` shows only the summary.
"""

import time
from collections import Counter
from collections.abc import Iterable, Sequence

from rich.console import Console, Group
from rich.live import Live
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from cpbenchy import hookimpl, scoring
from cpbenchy.result import STATUSES, RunResult

STYLES = {
    "optimal": "green",
    "unsat": "green",
    "feasible": "cyan",
    "unknown": "yellow",
    "timeout": "magenta",
    "memout": "magenta",
    "error": "bold red",
}


@hookimpl
def cpbenchy_addoption(parser):
    group = parser.getgroup("output")
    group.addoption("-v", "--verbose", action="count", default=0, help="print every finished run")
    group.addoption("-q", "--quiet", action="count", default=0, help="only print the summary")
    group.addoption(
        "--par",
        type=float,
        metavar="K",
        help="add each solver's PAR-K score to the summary: the time of solved runs, K times the limit for others",
    )


@hookimpl
def cpbenchy_configure(config):
    config.pluginmanager.register(TerminalReporter(config), "terminalreporter")


class TerminalReporter:
    def __init__(self, config, console: Console | None = None):
        self.config = config
        self.console = console or Console(highlight=False)
        self.verbosity = config.getoption("verbose", 0) - config.getoption("quiet", 0)
        self.active: dict[str, list] = {}  # run_id -> [run, start time, latest objective]
        self.live: Live | None = None
        self.progress = Progress(
            TextColumn("[bold]running"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.console,
        )
        self.task = self.progress.add_task("runs", total=0)
        self.started = time.monotonic()

    @hookimpl
    def cpbenchy_sessionstart(self, session):
        executor = session.executor
        skipped = session.already_done
        line = f"[bold]cpbenchy[/] {len(session.runs)} runs"
        if skipped:
            line += f" ({skipped} already in {session.store.out}, --rerun to run them again)"
        self.console.print(line)
        self.console.print(
            f"executor {executor.name}, {self.config.getoption('jobs')} in parallel, results in {session.store.out}",
            style="dim",
        )
        rules = self.config.rules
        if rules is not None:
            line = f"rules {rules.name}" + (f": {rules.description}" if rules.description else "")
            self.console.print(line, style="dim")
            if self.config.deviations:
                changed = ", ".join(f"{k}={v}" for k, v in self.config.deviations.items())
                self.console.print(f"not following the rules for: {changed}", style="yellow")
        if not executor.reliable:
            self.console.print(
                f"warning: the {executor.name} executor does not enforce memory limits and measurements are "
                "not reliable; see `cpbenchy doctor`",
                style="yellow",
            )
        self.progress.update(self.task, total=len(session.runs))
        if self.console.is_terminal and self.verbosity >= 0 and session.runs:
            self.live = Live(get_renderable=self._render, console=self.console, transient=True)
            self.live.start()

    @hookimpl
    def cpbenchy_run_start(self, run):
        self.active[run.run_id] = [run, time.monotonic(), None]

    @hookimpl
    def cpbenchy_run_event(self, run, event):
        if event.kind == "solution" and run.run_id in self.active:
            self.active[run.run_id][2] = event.data["objective"]

    @hookimpl(trylast=True)
    def cpbenchy_run_finished(self, run, result):
        self.active.pop(run.run_id, None)
        self.progress.advance(self.task)
        if result.status == "error" or self.verbosity > 0 or (self.live is None and self.verbosity == 0):
            self.console.print(format_result(result))
        if result.status == "error":
            self.console.print(f"  {result.error}\n  log: {run.log_file}", style="red", markup=False)

    @hookimpl
    def cpbenchy_sessionfinish(self, session):
        if self.live is not None:
            self.live.stop()
        if session.results:
            self.console.print(summary_table(session.results, par=self.config.getoption("par")))
        took = time.monotonic() - self.started
        interrupted = " (interrupted)" if session.interrupted else ""
        self.console.print(f"{len(session.results)} runs in {took:.1f}s{interrupted}", style="bold")

    def _render(self):
        now = time.monotonic()
        table = Table.grid(padding=(0, 2))
        for run, start, objective in self.active.values():
            spec = run.spec
            table.add_row(
                spec.instance.name,
                spec.solver,
                f"{now - start:.0f}s / {spec.limits.time_s:g}s",
                "" if objective is None else f"obj {objective}",
                style="dim",
            )
        return Group(self.progress, table)


def format_result(result: RunResult) -> str:
    style = STYLES.get(result.status, "")
    objective = "" if result.objective is None else f"  obj {result.objective}"
    walltime = "" if result.walltime_s is None else f"  {result.walltime_s:.2f}s"
    seed = "" if result.seed is None else f" seed {result.seed}"
    return f"[{style}]{result.status:>8}[/]  {result.solver}{seed}  {result.instance}{walltime}{objective}"


def summary_table(results: Iterable[RunResult], by: Sequence[str] = ("solver",), par: float | None = None) -> Table:
    """Per group (by default per solver): how many runs ended in each status, how many are solved, the
    total wall time of the solved ones, and with `par`, the total PAR-`par` score."""
    groups: dict[tuple, list[RunResult]] = {}
    for result in results:
        groups.setdefault(tuple(_value(result, key) for key in by), []).append(result)
    present = [s for s in STATUSES if any(r.status == s for rs in groups.values() for r in rs)]
    table = Table(title="results", title_justify="left")
    for key in by:
        table.add_column(key)
    table.add_column("runs", justify="right")
    table.add_column("solved", justify="right", style="bold")
    for status in present:
        table.add_column(status, justify="right", style=STYLES.get(status))
    table.add_column("time solved", justify="right")
    if par is not None:
        table.add_column(f"PAR-{par:g}", justify="right", style="bold")
    for key, rs in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0]))):
        counts = Counter(r.status for r in rs)
        solved = [r for r in rs if r.solved]
        time_solved = sum(r.walltime_s or 0 for r in solved)
        table.add_row(
            *map(str, key),
            str(len(rs)),
            str(len(solved)),
            *(str(counts[s] or "") for s in present),
            f"{time_solved:.1f}s",
            *([f"{sum(scoring.par(r, par) for r in rs):.1f}"] if par is not None else []),
        )
    return table


def _value(result: RunResult, key: str):
    if key.startswith("extra."):
        return result.extra.get(key[len("extra.") :])
    value = getattr(result, key)
    return str(value) if isinstance(value, (dict, list)) else value
