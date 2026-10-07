"""The outcome of a run: one flat record, stored as one line of `results.jsonl`.

A record joins three sources: the `RunSpec` (what was run), the worker's report (what the solver said, and
how long each stage took), and the executor's `Measurement` (what the process used, and whether it was
killed). Plugins add their own fields under `extra`.
"""

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from cpbenchy.refs import short
from cpbenchy.spec import RunSpec

# optimal/feasible/unsat/unknown come from the solver; the rest from how the process ended. A run stopped at
# its limit (`--terminate`) that reported a solution by then is feasible, else timeout.
STATUSES = ("optimal", "feasible", "unsat", "unknown", "timeout", "memout", "error")


@dataclass(frozen=True)
class Measurement:
    """What an executor measured about one worker process."""

    walltime_s: float | None
    cputime_s: float | None
    memory_mib: float | None
    termination: str | None  # None if the process exited by itself, else e.g. "walltime", "memory"
    exitcode: int | None
    executor: str
    reliable: bool  # False if limits and measurements are best effort (no cgroups)


@dataclass
class RunResult:
    run_id: str
    instance: str
    dataset: str | None
    solver: str
    loader: str | None
    params: dict[str, Any]
    seed: int | None
    cores: int
    time_limit_s: float
    mem_limit_mib: int | None
    status: str
    cputime_limit_s: float | None = None
    rules: str | None = None  # the rules the run followed (`--rules`), "<name> (modified)" if not exactly
    cpus: list[int] | None = None  # what the run was pinned to
    objective: float | None = None
    has_objective: bool | None = None
    parse_s: float | None = None
    transform_s: float | None = None
    solve_s: float | None = None
    walltime_s: float | None = None
    cputime_s: float | None = None
    memory_mib: float | None = None
    termination: str | None = None
    exitcode: int | None = None
    executor: str | None = None
    reliable: bool | None = None
    error: str | None = None
    started: str | None = None
    host: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def solved(self) -> bool:
        """Optimal or unsat; for satisfaction problems, any solution."""
        return self.status in ("optimal", "unsat") or (self.status == "feasible" and self.has_objective is False)

    @classmethod
    def build(cls, spec: RunSpec, report: dict | None, measurement: Measurement, **kwargs: Any) -> "RunResult":
        """Combine the spec, the worker's report (None if it never finished) and the measurement."""
        report = report or {}
        terminated = report.get("terminated")  # the worker stopped at a limit and reported (`--terminate`)
        if terminated:
            status = "feasible" if report.get("status") == "feasible" else "timeout"
            kwargs.setdefault("termination", measurement.termination or terminated)
        elif measurement.termination in ("walltime", "cputime", "cputime-soft"):
            status = "timeout"
        elif measurement.termination == "memory":
            status = "memout"
        elif not report:
            status = "error"
            kwargs.setdefault("error", f"worker exited without a result (exit code {measurement.exitcode})")
        else:
            status = report["status"]
        # An empty worker report sets kwargs["error"], and the report may set it too.
        reported_error = report.get("error")
        if reported_error is None:
            reported_error = kwargs.pop("error", None)
        else:
            kwargs.pop("error", None)
        return cls(
            run_id=spec.run_id,
            instance=spec.instance.name,
            dataset=spec.instance.dataset,
            solver=spec.solver,
            loader=short(spec.loader) if spec.loader else None,
            params=spec.params,
            seed=spec.seed,
            cores=spec.cores,
            time_limit_s=spec.limits.time_s,
            mem_limit_mib=spec.limits.mem_mib,
            cputime_limit_s=spec.limits.cputime_s,
            status=status,
            objective=report.get("objective") if status in ("optimal", "feasible") else None,
            has_objective=report.get("has_objective"),
            parse_s=report.get("parse_s"),
            transform_s=report.get("transform_s"),
            solve_s=report.get("solve_s"),
            error=reported_error,
            extra=dict(report.get("extra", {})),
            **{k: v for k, v in asdict(measurement).items() if k not in kwargs},
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunResult":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class Results(list[RunResult]):
    """A list of results, with conversions for analysis."""

    @classmethod
    def load(cls, out: str | Path) -> "Results":
        """The results stored in an output directory (or a `results.jsonl` file)."""
        path = Path(out)
        if path.is_dir():
            path = path / "results.jsonl"
        lines = path.read_text().splitlines() if path.exists() else []
        return cls(RunResult.from_dict(json.loads(line)) for line in lines if line.strip())

    def to_records(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self]

    def to_pandas(self):
        """A DataFrame with one row per run, with a `solved` column; `extra` fields become `extra.<name>`
        columns. Needs pandas (`pip install cpbenchy[pandas]`)."""
        import pandas as pd

        df = pd.json_normalize(self.to_records(), max_level=1)
        df["solved"] = [r.solved for r in self]
        return df

    def where(self, **conditions: Any) -> "Results":
        return Results(r for r in self if all(getattr(r, k) == v for k, v in conditions.items()))
