"""Observers: the simple way to change how runs work. Subclass `Observer` and override what you need.

    class SolverTime(cpbenchy.Observer):
        def __init__(self, warn_below=None):
            self.warn_below = warn_below

        def on_finish(self, ctx):  # in the worker
            ctx.record("solver_time_s", ctx.solver.status().runtime)

        def on_result(self, run, result):  # in the parent
            if self.warn_below and result.extra["solver_time_s"] < self.warn_below * result.solve_s:
                print(f"{result.instance}: little of the solve time was the solver's")

Use it with `-p "file.py:SolverTime(warn_below=0.5)"` (or just `-p file.py` for the defaults),
`plugins=[SolverTime(0.5)]` in Python, or define it in `cpbenchy_conf.py`. The docs' "Writing an
observer" builds it step by step.

Some callbacks run in the measured worker process, the others in the parent. An observer with worker
callbacks is created again in the worker, with the same constructor arguments, so those must be Python
literals. `self` is therefore not shared between the two sides; pass data from the worker to the parent
with `ctx.record(...)` (into the result) or `ctx.emit(...)` (an event).

Imported inside the measured worker process: Python 3.10 compatible.
"""

from typing import Any

from cpbenchy import hookimpl
from cpbenchy.refs import Shippable

WORKER_CALLBACKS = ("on_load", "on_solver", "solver_args", "on_solution", "on_finish")
PARENT_CALLBACKS = ("on_session_start", "on_start", "on_event", "on_result", "on_session_end")


class Observer(Shippable):
    """Override any of these. `ctx` is the run in the worker (`WorkerContext`), `run` and `result` the run
    and its record in the parent; see the docs' hook reference for what they hold."""

    formats: tuple[str, ...] | None = None
    """Only observe runs on instances of these formats (e.g. `("xcsp3",)`); None: all runs."""

    # --- in the worker, in this order ---

    def on_load(self, ctx) -> Any:
        """Return a `cpmpy.Model` to load the instance yourself (timed as parse_s), or None."""

    def on_solver(self, ctx) -> Any:
        """Return a solver for `ctx.model` to create it yourself (timed as transform_s), or None."""

    def solver_args(self, ctx) -> dict | None:
        """Return keyword arguments for `solve()`; the run's own `params` take precedence."""

    def on_solution(self, ctx, objective) -> None:
        """A solution was found, while solving (optimization problems, solvers with a callback)."""

    def on_finish(self, ctx) -> None:
        """The run ended, also after an error; `ctx.status` and `ctx.objective` are final. The place to
        check, record (`ctx.record`) or write out (`ctx.artifact`) results."""

    # --- in the parent, in this order ---

    def on_session_start(self, session) -> None:
        """Before the first run; `session.runs` are the runs to do."""

    def on_start(self, run) -> None:
        """A run is about to start."""

    def on_event(self, run, event) -> None:
        """An event from the run's worker: `event.kind` (loaded, transformed, solving, solution, result, or
        your own from `ctx.emit`), `event.data`, `event.t` (seconds)."""

    def on_result(self, run, result) -> None:
        """A run ended; `result` is about to be stored, so you can add to `result.extra`."""

    def on_session_end(self, session) -> None:
        """All runs are done, or the session was interrupted; `session.results` are its results."""


def overrides(observer: Observer, callbacks: tuple[str, ...]) -> bool:
    return any(getattr(type(observer), name) is not getattr(Observer, name) for name in callbacks)


class ObserverPlugin:
    """An observer as a plugin: forwards cpbenchy's hooks to the observer's callbacks."""

    def __init__(self, observer: Observer):
        self.observer = observer

    def __repr__(self) -> str:
        return f"ObserverPlugin({type(self.observer).__name__})"

    def _observes(self, spec) -> bool:
        formats = self.observer.formats
        return formats is None or spec.instance.format in formats

    @hookimpl
    def cpbenchy_worker_load(self, ctx):
        return self.observer.on_load(ctx) if self._observes(ctx.spec) else None

    @hookimpl
    def cpbenchy_worker_solver(self, ctx):
        return self.observer.on_solver(ctx) if self._observes(ctx.spec) else None

    @hookimpl
    def cpbenchy_worker_solver_args(self, ctx):
        return self.observer.solver_args(ctx) if self._observes(ctx.spec) else None

    @hookimpl
    def cpbenchy_worker_solution(self, ctx, objective):
        if self._observes(ctx.spec):
            self.observer.on_solution(ctx, objective)

    @hookimpl
    def cpbenchy_worker_finish(self, ctx):
        if self._observes(ctx.spec):
            self.observer.on_finish(ctx)

    @hookimpl
    def cpbenchy_sessionstart(self, session):
        self.observer.on_session_start(session)

    @hookimpl
    def cpbenchy_run_start(self, run):
        if self._observes(run.spec):
            self.observer.on_start(run)

    @hookimpl
    def cpbenchy_run_event(self, run, event):
        if self._observes(run.spec):
            self.observer.on_event(run, event)

    @hookimpl
    def cpbenchy_run_finished(self, run, result):
        if self._observes(run.spec):
            self.observer.on_result(run, result)

    @hookimpl
    def cpbenchy_sessionfinish(self, session):
        self.observer.on_session_end(session)
