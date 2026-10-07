"""Limits as in competitions: CPU time limits, and stopping runs at their limit (`--terminate`) so they still
report the best solution they found."""

import pytest

from cpbenchy.testing import DATA

KNAPSACK = DATA / "knapsack.opb"

# A "solver" that finds a solution, reports it, then keeps searching past its limit: sleeping (releasing
# the GIL, as native solvers do while they search) or busy (using CPU time).
OVERRUNNING_SOLVER = """
import time

import cpbenchy


@cpbenchy.hookimpl(tryfirst=True)
def cpbenchy_worker_solve(ctx):
    if ctx.spec.seed in (1, 3):  # a solution first
        ctx.solver.solve()
        ctx.report_solution(ctx.model.objective_.value())
    if ctx.spec.seed in (1, 2):
        time.sleep(60)
    else:
        while True:
            pass
"""
SLEEPS_AFTER_A_SOLUTION, SLEEPS_WITHOUT, BUSY_AFTER_A_SOLUTION = 1, 2, 3

EXECUTORS = ["subprocess", pytest.param("runlimit", marks=pytest.mark.runexec)]


def run(benchtester, executor, seed, *args):
    benchtester.makeconf(OVERRUNNING_SOLVER)
    outcome = benchtester.run_cli(
        "run", str(KNAPSACK), "-s", "ortools", "-o", "out", "--executor", executor, "--seed", str(seed),
        "-p", "cpbenchy.observers:PBOutput", *args,
    )  # fmt: skip
    [result] = outcome.results
    pb_out = benchtester.out / "logs" / f"{result.run_id}.pb.out"
    return result, pb_out.read_text() if pb_out.exists() else ""


@pytest.mark.parametrize("executor", EXECUTORS)
def test_terminate_reports_the_best_solution_at_the_time_limit(benchtester, executor):
    result, output = run(benchtester, executor, SLEEPS_AFTER_A_SOLUTION, "-t", "2", "--terminate", "--grace", "20")
    assert (result.status, result.objective, result.termination) == ("feasible", -9, "walltime")
    assert result.walltime_s < 10  # stopped at the limit, not killed after the grace period
    assert output.splitlines()[-2:] == ["s SATISFIABLE", "v x1 x2 -x3 x4"]


@pytest.mark.parametrize("executor", EXECUTORS)
def test_terminate_without_a_solution_is_a_timeout(benchtester, executor):
    result, output = run(benchtester, executor, SLEEPS_WITHOUT, "-t", "2", "--terminate", "--grace", "20")
    assert (result.status, result.termination) == ("timeout", "walltime")
    assert output.splitlines()[-1] == "s UNKNOWN"


@pytest.mark.parametrize("executor", EXECUTORS)
def test_terminate_at_the_cpu_time_limit(benchtester, executor):
    args = ["-t", "30", "--cpu-time-limit", "2", "--terminate", "--grace", "20"]
    result, output = run(benchtester, executor, BUSY_AFTER_A_SOLUTION, *args)
    assert (result.status, result.objective) == ("feasible", -9)
    assert result.termination in ("cputime", "cputime-soft")
    assert result.cputime_limit_s == 2 and result.walltime_s < 15
    assert "v x1 x2 -x3 x4" in output


@pytest.mark.parametrize("executor", EXECUTORS)
def test_without_terminate_a_cpu_limit_kills_the_run(benchtester, executor):
    result, output = run(
        benchtester, executor, BUSY_AFTER_A_SOLUTION, "-t", "30", "--cpu-time-limit", "1", "--grace", "1"
    )
    assert (result.status, result.termination) == ("timeout", "cputime")
    assert result.walltime_s < 15
    assert "s " not in output  # killed: no answer


def test_without_terminate_runs_are_killed_after_the_grace_period(benchtester):
    result, output = run(benchtester, "subprocess", SLEEPS_AFTER_A_SOLUTION, "-t", "1", "--grace", "1")
    assert (result.status, result.termination) == ("timeout", "walltime")
    assert "o -9" in output and "s " not in output


def test_a_solver_that_stops_in_time_reports_by_itself(benchtester):
    outcome = benchtester.run_cli(
        "run", str(KNAPSACK), "-s", "ortools", "-o", "out", "--executor", "subprocess", "-t", "10", "--terminate"
    )
    [result] = outcome.results
    assert (result.status, result.termination) == ("optimal", None)
