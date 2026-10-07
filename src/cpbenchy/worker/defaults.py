"""The built-in worker steps. All `trylast`, so plugins can replace any of them."""

from cpbenchy import hookimpl, refs
from cpbenchy.loader import Loader

DEFAULT_LOADER = Loader()


@hookimpl(trylast=True)
def cpbenchy_worker_load(ctx):
    loader = refs.load(ctx.spec.loader) if ctx.spec.loader else DEFAULT_LOADER
    return loader.load(ctx.spec.instance)


@hookimpl(trylast=True)
def cpbenchy_worker_solver(ctx):
    from cpmpy import SolverLookup

    return SolverLookup.get(ctx.spec.solver, ctx.model)


@hookimpl(trylast=True)
def cpbenchy_worker_solve(ctx):
    # Never pass a non-positive limit; the executor's hard limit is the backstop.
    ctx.solver.solve(time_limit=max(ctx.time_left(), 0.1), **ctx.solver_args)
    return True
