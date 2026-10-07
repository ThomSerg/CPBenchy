import pytest
from cpmpy import SolverLookup

from cpbenchy.testing import DATA

SOLVERS = ["ortools", "exact", "gurobi", "highs", "choco"]


def installed(solver):
    try:
        return SolverLookup.lookup(solver).supported()
    except Exception:
        return False


@pytest.mark.parametrize(
    "solver",
    [pytest.param(s, marks=pytest.mark.skipif(not installed(s), reason=f"{s} not installed")) for s in SOLVERS],
)
def test_solver_with_cores_and_seed(benchtester, solver):
    results = benchtester.run(DATA / "knapsack.opb", DATA / "unsat.opb", solvers=[solver], seeds=[7], cores=1)
    statuses = {r.instance: (r.status, r.objective) for r in results}
    assert statuses == {"knapsack": ("optimal", -9), "unsat": ("unsat", None)}, results[0].error


def test_solution_trajectory_is_recorded(benchtester):
    [result] = benchtester.run(DATA / "knapsack.opb")
    times, objectives = zip(*result.extra["solutions"], strict=True)
    assert objectives[-1] == result.objective == -9
    assert list(times) == sorted(times)


def test_no_solutions_option(benchtester):
    [result] = benchtester.run(DATA / "knapsack.opb", args=["--no-solutions"])
    assert "solutions" not in result.extra


def test_params_take_precedence_over_built_in_settings(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        @cpbenchy.hookimpl
        def cpbenchy_worker_finish(ctx):
            ctx.record("args", {k: v for k, v in ctx.solver_args.items() if k != "display"})
        """
    )
    [result] = benchtester.run(DATA / "knapsack.opb", params={"num_search_workers": 2}, seeds=[3])
    assert result.extra["args"] == {"num_search_workers": 2, "random_seed": 3}
