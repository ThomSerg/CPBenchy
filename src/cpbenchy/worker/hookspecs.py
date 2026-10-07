"""Hooks called inside the worker, in this order: start, load, solver, solver_args, solve (with solution
during solving), finish.

Each takes the `WorkerContext` as `ctx`. The built-in implementations (`cpbenchy.worker.defaults`) are
`trylast`, so a plugin returning a value from a `firstresult` hook replaces them.
"""

from cpbenchy import hookspec


@hookspec
def cpbenchy_worker_start(ctx):
    """First thing in the worker, before the worker imports CPMpy (e.g. to patch a solver package)."""


@hookspec(firstresult=True)
def cpbenchy_worker_load(ctx):
    """Load `ctx.spec.instance` and return a `cpmpy.Model`. Timed as `parse_s`."""


@hookspec(firstresult=True)
def cpbenchy_worker_solver(ctx):
    """Create the solver for `ctx.model` and return it. CPMpy transforms and posts the model here, so this
    is timed as `transform_s`."""


@hookspec
def cpbenchy_worker_solver_args(ctx):
    """Return a dict of keyword arguments for `solver.solve()`, or None.

    The dicts are merged; on conflicts, the implementation called first (e.g. `tryfirst`) wins, and the
    run's own `params` win over all of them. This is where solver plugins translate `ctx.spec.cores` and
    `ctx.spec.seed` into native parameters and install solution callbacks.
    """


@hookspec(firstresult=True)
def cpbenchy_worker_solve(ctx):
    """Solve `ctx.solver` with `ctx.solver_args` within `ctx.time_left()`. Timed as `solve_s`."""


@hookspec
def cpbenchy_worker_solution(ctx, objective):
    """A solution was found during solving (reported with `ctx.report_solution`)."""


@hookspec
def cpbenchy_worker_finish(ctx):
    """Last thing in the worker, always called, also after an error (`ctx.status == "error"`).

    `ctx.status` and `ctx.objective` are final; use `ctx.record(key, value)` to add to the result.
    """
