"""Run measurements for an external experiment runner.

The runner submits what to measure and receives the stats. It keeps its own notion of a batch, of
resume, and of where results are stored. Two submissions that describe the same measurement run once,
and both get the stats.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cpbenchy.experiment import Experiment
from cpbenchy.result import RunResult
from cpbenchy.spec import RunSpec
from cpbenchy.store import Store

OnBackendResult = Callable[["BackendResult"], Any]


@dataclass(frozen=True)
class Submission:
    """One run an external runner wants measured.

    `key` is the runner's own id. `metadata` is returned with the stats. Neither is part of
    `RunSpec.run_id`, so they do not change which measurement runs.
    """

    spec: RunSpec
    key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendResult:
    """The stats for one submission.

    `result` is the measurement. `log` is the worker's stdout and stderr, or None if the executor
    wrote no log.
    """

    key: str
    metadata: dict[str, Any]
    result: RunResult
    log: str | None


def run(
    submissions: Iterable[Submission],
    *,
    jobs: int = 1,
    executor: str = "auto",
    plugins: Iterable[Any] = (),
    args: Iterable[str] = (),
    out: str | Path | None = None,
    quiet: bool = False,
    on_result: OnBackendResult | None = None,
) -> list[BackendResult]:
    """Measure `submissions` in one session, and return one `BackendResult` per submission.

    `jobs`, `executor`, `plugins` and `args` are the session settings of `Experiment`. The runner
    submits only what it wants done: runs already stored in `out` are measured again. `out` is a
    fresh temporary directory when not given. `on_result` is called as each measurement finishes,
    once per submission that shares it.
    """
    pending = list(submissions)
    if not pending:
        return []
    by_id: dict[str, list[Submission]] = {}
    for submission in pending:
        by_id.setdefault(submission.spec.run_id, []).append(submission)
    experiment = Experiment(out, jobs=jobs, executor=executor, rerun=True, quiet=quiet, plugins=plugins, args=args)
    experiment.add_runs(submission.spec for submission in _one_per_measurement(by_id))
    tagged: list[BackendResult] = []

    def report(result: RunResult) -> None:
        log = _log_text(experiment.out, result.run_id)
        for submission in by_id.get(result.run_id, []):
            item = BackendResult(submission.key, dict(submission.metadata), result, log)
            tagged.append(item)
            if on_result is not None:
                on_result(item)

    experiment.run(on_result=report)
    return tagged


def _one_per_measurement(by_id: dict[str, list[Submission]]) -> list[Submission]:
    return [group[0] for group in by_id.values()]


def _log_text(out: Path, run_id: str) -> str | None:
    path = Store(out).log_file(run_id)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")
