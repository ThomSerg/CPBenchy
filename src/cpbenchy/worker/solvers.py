"""Built-in solver settings: the run's cores and seed as native parameters, and reporting each solution.

Settings are otherwise the solver's defaults; pass anything else as the run's `params` (`-P key=value`),
which take precedence. To support another solver, add it to `NATIVE`, or write a plugin with a
`cpbenchy_worker_solver_args` hook.
"""

import inspect

from cpbenchy import hookimpl

# solver -> (parameter for the number of cores, parameter for the seed), as `solve()` keyword arguments
NATIVE = {
    "ortools": ("num_search_workers", "random_seed"),
    "gurobi": ("Threads", "Seed"),
    "cpo": ("Workers", "RandomSeed"),
    "cplex": ("threads", "randomseed"),
    "highs": ("threads", "random_seed"),
    "hexaly": ("nb_threads", "seed"),
    "exact": (None, "seed"),
    "minizinc": ("processes", "random_seed"),
}


@hookimpl
def cpbenchy_worker_solver_args(ctx):
    args = {}
    cores_param, seed_param = NATIVE.get(ctx.spec.solver.split(":")[0], (None, None))
    if cores_param:
        args[cores_param] = ctx.spec.cores
    if seed_param and ctx.spec.seed is not None:
        args[seed_param] = ctx.spec.seed % 2**31  # competitions' seeds go up to 2**32 - 1; solvers take int32
    if ctx.options.get("solutions", True) and ctx.model.has_objective() and _accepts(ctx.solver.solve, "display"):
        # CPMpy calls `display` on each solution, with the variables set to it
        objective = ctx.model.objective_
        args["display"] = lambda: ctx.report_solution(objective.value())
    return args


def _accepts(function, name: str) -> bool:
    try:
        return name in inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
