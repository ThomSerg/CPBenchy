"""PAR-k scores: `cpbenchy.scoring` and `--par` in the summaries."""

import pytest

from cpbenchy.config import make_config
from cpbenchy.result import RunResult
from cpbenchy.scoring import par, par_totals
from cpbenchy.testing import DATA


def result(solver="ortools", status="optimal", walltime_s=3.0, cputime_s=2.0, time_limit_s=60, cputime_limit_s=None):
    return RunResult(
        run_id="x", instance="i", dataset=None, solver=solver, loader=None, params={}, seed=None, cores=1,
        time_limit_s=time_limit_s, mem_limit_mib=None, status=status, has_objective=True,
        walltime_s=walltime_s, cputime_s=cputime_s, cputime_limit_s=cputime_limit_s,
    )  # fmt: skip


def test_a_solved_run_scores_its_time_and_others_a_penalty():
    assert par(result()) == 3.0
    assert par(result(status="unsat")) == 3.0
    for status in ("feasible", "timeout", "memout", "error", "unknown"):  # feasible: not proven optimal
        assert par(result(status=status)) == 120
    assert par(result(status="timeout"), factor=10) == 600


def test_cpu_time_limited_runs_score_cpu_time():
    limited = result(cputime_limit_s=30)
    assert par(limited) == 2.0 and par(result(status="timeout", cputime_limit_s=30)) == 60
    assert par(limited, time="walltime") == 3.0
    assert par(result(), time="cputime") == 2.0  # without a CPU time limit, against the time limit
    with pytest.raises(ValueError):
        par(limited, time="cpu")


def test_totals_per_solver():
    results = [result("a"), result("a", status="timeout"), result("b", walltime_s=1.0)]
    assert par_totals(results) == {("a",): 123.0, ("b",): 1.0}
    assert par_totals(results, factor=1, by=("solver", "status")) == {
        ("a", "optimal"): 3.0, ("a", "timeout"): 60.0, ("b", "optimal"): 1.0,
    }  # fmt: skip


def test_par_in_the_summaries(benchtester):
    outcome = benchtester.run_cli(
        "run", str(DATA / "knapsack.opb"), "-s", "ortools", "-t", "10", "-o", "out", "--par", "10"
    )
    assert outcome.ret == 0, outcome.stderr
    assert "PAR-10" in outcome.stdout
    shown = benchtester.run_cli("show", "out", "--par", "2")
    [run] = shown.results
    assert "PAR-2" in shown.stdout and f"{run.walltime_s:.1f}" in shown.stdout
    assert "PAR" not in benchtester.run_cli("show", "out").stdout


def test_rules_can_set_par_and_changing_it_keeps_them_followed(benchtester):
    path = benchtester.makefile("my.toml", 'name = "sat-like"\n[settings]\ntime-limit = 60\npar = 2\n')
    config = make_config(["--rules", str(path)])
    assert config.getoption("par") == 2 and config.rules_label == "sat-like"
    config = make_config(["--rules", str(path), "--par", "10"])
    assert config.getoption("par") == 10 and config.rules_label == "sat-like"
