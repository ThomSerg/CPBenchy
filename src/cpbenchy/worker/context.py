import json
import threading
import time
from pathlib import Path
from typing import IO, Any

from cpbenchy.spec import RunSpec


class WorkerContext:
    """The state of one run inside the worker, shared by all worker hooks."""

    def __init__(
        self,
        spec: RunSpec,
        events: IO[str],
        options: dict[str, Any] | None = None,
        artifacts: Path | None = None,
        start: float | None = None,
    ):
        self.spec = spec
        self.options = options or {}  # the session's options (JSON-safe ones), plugin options included
        self.model: Any = None
        self.solver: Any = None
        self.solver_args: dict[str, Any] = {}
        self.status: str | None = None
        self.objective: float | None = None
        self.error: str | None = None
        self.times: dict[str, float] = {}
        self.extra: dict[str, Any] = {}
        self.hook: Any = None  # set by the runtime; calls the worker hooks
        self.terminated: str | None = None  # why the run was stopped at a limit (`--terminate`): walltime, ...
        # With --terminate: the last solution reported while solving, (objective, values of `_variables`),
        # so a stopped run still reports it. `lock` guards it, and the switch from solving to finishing.
        self.best: tuple[float | None, list] | None = None
        self.finishing = False
        self.solve_started: float | None = None  # perf_counter() when solving started
        self.lock = threading.Lock()
        self._variables: list | None = None
        self._events = events
        self._artifacts = artifacts or Path.cwd()
        self._start = time.perf_counter() if start is None else start  # perf_counter() when the run started
        self._cpu_start = time.process_time() if start is None else 0.0  # a worker process: all its CPU time

    def elapsed(self) -> float:
        return time.perf_counter() - self._start

    def cputime(self) -> float:
        """CPU time this run used so far (of this process: all its threads, not its child processes)."""
        return time.process_time() - self._cpu_start

    def time_left(self) -> float:
        """What is left of the run's time limit, and of its CPU time limit if it has one; the solver gets
        this."""
        left = self.spec.limits.time_s - self.elapsed()
        if self.spec.limits.cputime_s is not None:
            left = min(left, self.spec.limits.cputime_s - self.cputime())
        return left

    def emit(self, kind: str, **data: Any) -> None:
        """Send an event to the parent (`cpbenchy_run_event`), live."""
        line = {"t": round(self.elapsed(), 6), "kind": kind, "data": data}
        self._events.write(json.dumps(line, default=str) + "\n")
        self._events.flush()

    def record(self, key: str, value: Any) -> None:
        """Add a JSON-safe value to the run's result, under `extra`."""
        self.extra[key] = value

    def artifact(self, name: str) -> Path:
        """A file of this run's own, next to its log (`<run_id>.<name>`), e.g. for competition output.
        The parent finds it as `run.artifact(name)`."""
        return self._artifacts / f"{self.spec.run_id}.{name}"

    def report_solution(self, objective: float | None = None) -> None:
        """For solver callbacks: a new solution was found (the model's variables have its values)."""
        if self.options.get("terminate"):
            self.keep_solution(objective)
        self.emit("solution", objective=objective)
        self.hook.cpbenchy_worker_solution(ctx=self, objective=objective)

    def keep_solution(self, objective: float | None) -> None:
        """Copy the current solution, to report if the run is stopped before the solver returns."""
        if self._variables is None:
            from cpmpy.transformations.get_variables import get_variables_model

            self._variables = get_variables_model(self.model)
        with self.lock:
            self.best = (objective, [v._value for v in self._variables])

    def restore_best(self) -> bool:
        """Give the model's variables the values of the kept solution; False if there is none."""
        if self.best is None or self._variables is None:
            return False
        for var, val in zip(self._variables, self.best[1], strict=True):
            var._value = val
        return True

    def log(self, message: str) -> None:
        """A progress line in the run's log, so a killed run shows how far it got. With the `stdout` option
        (`cpbenchy solve`), a comment line (`c ...`), as competition output allows."""
        prefix = "c " if self.options.get("stdout") else ""
        print(f"{prefix}[cpbenchy {self.elapsed():8.2f}s] {message}", flush=True)

    def report(self) -> dict[str, Any]:
        has_objective = self.model.has_objective() if self.model is not None else None
        return {
            "status": self.status,
            "objective": self.objective,
            "has_objective": has_objective,
            **self.times,
            "error": self.error,
            "terminated": self.terminated,
            "extra": self.extra,
        }
