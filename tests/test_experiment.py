import pytest

import cpbenchy
from cpbenchy.config import UsageError
from cpbenchy.spec import Instance, Limits, RunSpec
from cpbenchy.testing import DATA

KNAPSACK, SAT, UNSAT = DATA / "knapsack.opb", DATA / "sat.opb", DATA / "unsat.opb"


def test_entries_have_their_own_solvers_params_and_limits(benchtester):
    exp = cpbenchy.Experiment(benchtester.out, time_limit=10, quiet=True)
    exp.add(KNAPSACK, SAT, solver="ortools", params={"num_search_workers": 1})
    exp.add(KNAPSACK, solver="exact", seeds=[1, 2], time_limit=5)
    runs = exp.runs
    assert sorted((r.solver, r.instance.name, r.seed, r.limits.time_s) for r in runs) == [
        ("exact", "knapsack", 1, 5),
        ("exact", "knapsack", 2, 5),
        ("ortools", "knapsack", None, 10),
        ("ortools", "sat", None, 10),
    ]
    results = exp.run()
    assert len(results) == 4 and all(r.solved for r in results)
    assert {r.params["num_search_workers"] for r in results if r.solver == "ortools"} == {1}


def test_iter_results_streams_and_resumes(benchtester):
    exp = cpbenchy.Experiment(benchtester.out, time_limit=10, quiet=True).add(KNAPSACK, SAT, UNSAT, solver="ortools")
    for result in exp.iter_results():
        assert result.instance == "knapsack"
        break  # stops the session; nothing else is stored
    assert [r.instance for r in exp.results()] == ["knapsack"]
    assert sorted(r.instance for r in exp.run()) == ["sat", "unsat"]
    assert len(exp.results()) == 3


def test_callbacks(benchtester):
    finished, solutions = [], []
    cpbenchy.run(
        KNAPSACK,
        UNSAT,
        solvers=["ortools"],
        time_limit=10,
        out=benchtester.out,
        quiet=True,
        on_result=lambda result: finished.append(result.instance),
        on_solution=lambda run, t, objective: solutions.append((run.instance.name, objective)),
    )
    assert sorted(finished) == ["knapsack", "unsat"]
    assert solutions[-1] == ("knapsack", -9)


def test_add_runs_as_they_are(benchtester):
    spec = RunSpec(Instance.from_path(KNAPSACK), "ortools", Limits(10), seed=5)
    exp = cpbenchy.Experiment(benchtester.out, quiet=True).add_runs([spec, spec])
    [result] = exp.run()
    assert result.run_id == spec.run_id and result.seed == 5


def test_quiet_prints_nothing(benchtester, capsys):
    cpbenchy.run(KNAPSACK, solvers=["ortools"], time_limit=10, out=benchtester.out, quiet=True)
    assert capsys.readouterr().out == ""


def test_add_needs_a_solver_and_a_time_limit():
    exp = cpbenchy.Experiment()
    with pytest.raises(UsageError, match="solver"):
        exp.add(KNAPSACK, time_limit=10)
    exp.add(KNAPSACK, solver="ortools")  # the time limit may still come from rules
    with pytest.raises(UsageError, match="time limit"):
        _ = exp.runs


UNGUARDED_SCRIPT = """
import cpbenchy

class Count(cpbenchy.Observer):
    def on_finish(self, ctx):
        ctx.record("n_constraints", len(ctx.model.constraints))

results = cpbenchy.run({instance!r}, solvers=["ortools"], time_limit=10, out="out", quiet=True, plugins=[Count()])
print("status:", results[0].status, results[0].error)
"""


def test_a_script_that_runs_again_in_the_worker_gets_a_clear_error(benchtester):
    import subprocess
    import sys

    script = benchtester.makefile("script.py", UNGUARDED_SCRIPT.format(instance=str(DATA / "knapsack.opb")))
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120)
    assert "status: error" in done.stdout, done.stderr
    assert 'if __name__ == "__main__":' in done.stdout
