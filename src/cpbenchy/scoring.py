"""Scores for comparing solvers on results, as competitions rank them.

PAR-k (penalised average runtime) scores a solved run with its time, and any other run (a timeout, an
error, a solution not proven optimal) with k times the time limit. Lower is better. The SAT competitions
rank by PAR-2.

    from cpbenchy.scoring import par, par_totals

    par(result)                    # one run's PAR-2
    par_totals(results, factor=10)  # {("ortools",): 412.3, ("exact",): 538.9}

`--par K` adds the score to the summary of `cpbenchy run` and `cpbenchy show`.
"""

from collections.abc import Iterable, Sequence
from typing import Literal

from cpbenchy.result import RunResult

Time = Literal["walltime", "cputime"]


def par(result: RunResult, factor: float = 2, time: Time | None = None) -> float:
    """The PAR-`factor` score of one run: its time if solved, else `factor` times its time limit.

    `time` is "walltime" or "cputime". Without it, a run with a CPU time limit is scored by CPU time
    against that limit, as competitions with CPU time limits do, and any other run by wall time.
    """
    if time is None:
        time = "cputime" if result.cputime_limit_s is not None else "walltime"
    if time == "cputime":
        used, limit = result.cputime_s, result.cputime_limit_s or result.time_limit_s
    elif time == "walltime":
        used, limit = result.walltime_s, result.time_limit_s
    else:
        raise ValueError(f"time is 'walltime' or 'cputime', not {time!r}")
    if result.solved and used is not None:
        return used
    return factor * limit


def par_totals(
    results: Iterable[RunResult], factor: float = 2, time: Time | None = None, by: Sequence[str] = ("solver",)
) -> dict[tuple, float]:
    """The total PAR-`factor` score per group of results, by the fields `by` (by default per solver).

    Compare totals over the same runs only: a solver with fewer runs has a lower total.
    """
    totals: dict[tuple, float] = {}
    for result in results:
        key = tuple(getattr(result, field) for field in by)
        totals[key] = totals.get(key, 0.0) + par(result, factor, time)
    return totals
