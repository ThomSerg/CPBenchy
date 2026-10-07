"""The one-call API: `cpbenchy.run(...)` and `cpbenchy.load(...)`. See `cpbenchy.Experiment` for more control."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from cpbenchy.experiment import Experiment, OnResult, OnSolution
from cpbenchy.result import Results


def run(
    *sources: Any,
    solvers: Iterable[str],
    time_limit: float | None = None,
    mem_limit_mib: int | None = None,
    cpu_time_limit: float | None = None,
    rules: Any = None,
    params: Mapping[str, Any] | None = None,
    seeds: Iterable[int] | None = None,
    cores: int | None = None,
    loader: Any = None,
    jobs: int = 1,
    out: str | Path | None = None,
    executor: str = "auto",
    rerun: bool = False,
    quiet: bool = False,
    plugins: Iterable[Any] = (),
    args: Iterable[str] = (),
    on_result: OnResult | None = None,
    on_solution: OnSolution | None = None,
) -> Results:
    """Run every solver (with every seed) on every instance of the sources, and return the results.

    Sources are cpmpy datasets, instance files, directories, glob patterns, `Instance`s, or lists of these.
    Results are also stored in `out` (a fresh temporary directory if not given); runs already stored there
    are skipped unless `rerun`. `rules` set the limits, cores and options not given (`--rules`). The other
    arguments are those of `Experiment` and `Experiment.add`.
    """
    experiment, add = _experiment(locals())
    return experiment.add(*sources, **add).run(on_result=on_result, on_solution=on_solution)


async def run_async(
    *sources: Any,
    solvers: Iterable[str],
    time_limit: float | None = None,
    mem_limit_mib: int | None = None,
    cpu_time_limit: float | None = None,
    rules: Any = None,
    params: Mapping[str, Any] | None = None,
    seeds: Iterable[int] | None = None,
    cores: int | None = None,
    loader: Any = None,
    jobs: int = 1,
    out: str | Path | None = None,
    executor: str = "auto",
    rerun: bool = False,
    quiet: bool = False,
    plugins: Iterable[Any] = (),
    args: Iterable[str] = (),
    on_result: OnResult | None = None,
    on_solution: OnSolution | None = None,
) -> Results:
    """`run` for asyncio: `results = await cpbenchy.run_async(...)`, with the same arguments. The event loop
    stays free while the runs go on, and the callbacks are called in it."""
    experiment, add = _experiment(locals())
    return await experiment.add(*sources, **add).run_async(on_result=on_result, on_solution=on_solution)


def _experiment(a: dict[str, Any]) -> tuple[Experiment, dict[str, Any]]:
    """The `Experiment` that `run` (or `run_async`) with arguments `a` is, and the arguments of its `add`."""
    experiment = Experiment(
        a["out"],
        cores=a["cores"],
        rules=a["rules"],
        jobs=a["jobs"],
        executor=a["executor"],
        rerun=a["rerun"],
        quiet=a["quiet"],
        plugins=a["plugins"],
        args=a["args"],
    )
    add = {
        "solvers": a["solvers"],
        "params": dict(a["params"] or {}),
        "seeds": a["seeds"],
        "time_limit": a["time_limit"],
        "mem_limit_mib": a["mem_limit_mib"],
        "cpu_time_limit": a["cpu_time_limit"],
        "loader": a["loader"],
    }
    return experiment, add


def load(out: str | Path) -> Results:
    """The results stored in an output directory."""
    return Results.load(out)
