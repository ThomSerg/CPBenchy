"""Experiments from Python: say what to run, then run it (blocking or streaming, with callbacks).

exp = cpbenchy.Experiment("results/x", time_limit=60, jobs=8)
exp.add(dataset, solver="ortools", params={"num_search_workers": 1})
exp.add(dataset, solver="gurobi", seeds=[1, 2, 3])
for result in exp.iter_results():
    ...

exp = cpbenchy.Experiment("results/xcsp3", rules="xcsp3-2025", jobs=4)  # limits and output from the rules
"""

import asyncio
import tempfile
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cpbenchy import hookimpl, refs
from cpbenchy.config import Config, UsageError, make_config
from cpbenchy.loader import Loader
from cpbenchy.result import Results, RunResult
from cpbenchy.session import Session, collect_instances, grid, make_limits
from cpbenchy.spec import RunSpec

OnResult = Callable[[RunResult], Any]
OnSolution = Callable[[RunSpec, float, Any], Any]  # (run, seconds since the worker started, objective)


@dataclass
class _Entry:
    sources: tuple[Any, ...]
    solvers: list[str]
    time_limit: float | None = None  # unset: the experiment's, else the options' (e.g. from rules)
    mem_limit_mib: int | None = None
    cpu_time_limit: float | None = None
    params: dict[str, Any] = field(default_factory=dict)
    seeds: list[int | None] = field(default_factory=lambda: [None])
    cores: int | None = None
    loader: str | None = None


class Experiment:
    """A set of runs with a shared output directory and session settings.

    `out` is where results go (a fresh temporary directory if None); runs already stored there are skipped
    unless `rerun`. `time_limit`, `cpu_time_limit`, `mem_limit_mib`, `cores` and `loader` are defaults for
    what is added. `rules` (a built-in name, a .toml file or a `Rules`) set the limits, cores and other
    options that aren't given explicitly, as `--rules` does. `quiet` turns off the terminal output.
    `plugins` are plugin objects or references; `args` are extra command-line arguments, e.g. for options
    that plugins add.
    """

    def __init__(
        self,
        out: str | Path | None = None,
        *,
        time_limit: float | None = None,
        mem_limit_mib: int | None = None,
        cpu_time_limit: float | None = None,
        cores: int | None = None,
        loader: Any = None,
        rules: Any = None,
        jobs: int = 1,
        executor: str = "auto",
        rerun: bool = False,
        quiet: bool = False,
        plugins: Iterable[Any] = (),
        args: Iterable[str] = (),
    ):
        self.out = Path(out) if out is not None else Path(tempfile.mkdtemp(prefix="cpbenchy-"))
        self.time_limit = time_limit
        self.mem_limit_mib = mem_limit_mib
        self.cpu_time_limit = cpu_time_limit
        self.cores = cores
        self.loader = loader
        self.rules = rules
        self.jobs = jobs
        self.executor = executor
        self.rerun = rerun
        self.quiet = quiet
        self.plugins = list(plugins)
        self.args = list(args)
        self._entries: list[_Entry] = []
        self._runs: list[RunSpec] = []

    def add(
        self,
        *sources: Any,
        solver: str | None = None,
        solvers: Iterable[str] = (),
        params: dict[str, Any] | None = None,
        seeds: Iterable[int] | None = None,
        time_limit: float | None = None,
        mem_limit_mib: int | None = None,
        cpu_time_limit: float | None = None,
        cores: int | None = None,
        loader: Any = None,
    ) -> "Experiment":
        """Run each solver (with each seed) on every instance of the sources: cpmpy datasets, instance files,
        directories, glob patterns, or lists of these. Unset limits, cores and loader come from the
        experiment. `loader` is a `Loader` (object or class) or a reference like "loaders.py:MyLoader(k=1)";
        None means CPMpy's loader for each instance's format."""
        all_solvers = [solver] if solver else list(solvers)
        if not all_solvers:
            raise UsageError("add() needs solver= or solvers=")
        if not sources:
            raise UsageError("add() needs at least one source")
        seed_list: list[int | None] = list(seeds) if seeds else [None]
        loader_ref = loader_reference(loader if loader is not None else self.loader)
        entry = _Entry(
            sources,
            all_solvers,
            time_limit,
            mem_limit_mib,
            cpu_time_limit,
            dict(params or {}),
            seed_list,
            cores,
            loader_ref,
        )
        self._entries.append(entry)
        return self

    def add_runs(self, runs: Iterable[RunSpec]) -> "Experiment":
        """Add runs as they are, for full control."""
        self._runs.extend(runs)
        return self

    @property
    def runs(self) -> list[RunSpec]:
        """Everything this experiment runs (including what `out` already has results for)."""
        return self._build_runs(self._config())

    def iter_results(
        self, *, on_result: OnResult | None = None, on_solution: OnSolution | None = None
    ) -> Iterator[RunResult]:
        """Run, yielding each result as its run finishes. Stopping early stops the runs still going; running
        again picks up what is missing."""
        callbacks = [_Callbacks(on_result, on_solution)] if on_result or on_solution else []
        config = self._config(callbacks)
        yield from Session(config, self._build_runs(config)).iter_results()

    def run(self, *, on_result: OnResult | None = None, on_solution: OnSolution | None = None) -> Results:
        """Run, and return the results of this session when all runs are done (see `results()` for
        everything stored in `out`)."""
        return Results(self.iter_results(on_result=on_result, on_solution=on_solution))

    async def iter_results_async(
        self, *, on_result: OnResult | None = None, on_solution: OnSolution | None = None
    ) -> AsyncIterator[RunResult]:
        """`iter_results` for asyncio. The runs go on, and new ones start, while the `async for` body
        awaits; the callbacks are called in the event loop."""
        callbacks = [_Callbacks(on_result, on_solution)] if on_result or on_solution else []
        config = self._config(callbacks)
        runs = await asyncio.to_thread(self._build_runs, config)  # collecting instances may take a while
        async for result in Session(config, runs).iter_results_async():
            yield result

    async def run_async(self, *, on_result: OnResult | None = None, on_solution: OnSolution | None = None) -> Results:
        """`run` for asyncio: `results = await exp.run_async()`."""
        return Results([r async for r in self.iter_results_async(on_result=on_result, on_solution=on_solution)])

    def results(self) -> Results:
        """All results stored in `out`, also those of earlier sessions."""
        return Results.load(self.out)

    def _config(self, plugins: Iterable[Any] = ()) -> Config:
        args = [*self.args, *(["-p", "no:terminal"] if self.quiet else [])]
        given = {  # the experiment's own settings, over the rules'
            "time_limit": self.time_limit,
            "mem_limit_mib": self.mem_limit_mib,
            "cputime_limit_s": self.cpu_time_limit,
            "cores": self.cores,
        }
        return make_config(
            args,
            plugins=[*self.plugins, *plugins],
            rules=self.rules,
            jobs=self.jobs,
            out=str(self.out),
            executor=self.executor,
            rerun=self.rerun,
            **{k: v for k, v in given.items() if v is not None},
        )

    def _build_runs(self, config: Config) -> list[RunSpec]:
        runs = []
        get = config.getoption
        for entry in self._entries:
            time_limit = entry.time_limit if entry.time_limit is not None else get("time_limit")
            if time_limit is None:
                raise UsageError("no time limit: pass time_limit= to add() or to the Experiment, or rules=")
            limits = make_limits(
                config,
                time_limit,
                entry.mem_limit_mib if entry.mem_limit_mib is not None else get("mem_limit_mib"),
                entry.cpu_time_limit if entry.cpu_time_limit is not None else get("cputime_limit_s"),
            )
            cores = entry.cores if entry.cores is not None else get("cores")
            instances = collect_instances(config, entry.sources)
            runs.extend(grid(instances, entry.solvers, limits, entry.params, entry.seeds, cores, entry.loader))
        runs.extend(self._runs)
        return list({run.run_id: run for run in runs}.values())  # the same run added twice runs once


def loader_reference(loader: Any) -> str | None:
    """A reference for the worker to create `loader` with: from a `Loader` object or class, or as given."""
    if loader is None or isinstance(loader, str):
        return loader
    if isinstance(loader, Loader) or (isinstance(loader, type) and issubclass(loader, Loader)):
        return refs.ref_for(loader)[0]
    raise UsageError(f"loader must be a cpbenchy.Loader (object or class) or a reference, not {loader!r}")


class _Callbacks:
    """The `on_result` and `on_solution` functions, as a plugin."""

    def __init__(self, on_result: OnResult | None, on_solution: OnSolution | None):
        self.on_result = on_result
        self.on_solution = on_solution

    @hookimpl
    def cpbenchy_run_event(self, run, event):
        if event.kind == "solution" and self.on_solution:
            self.on_solution(run.spec, event.t, event.data["objective"])

    @hookimpl
    def cpbenchy_run_finished(self, run, result):
        if self.on_result:
            self.on_result(result)
