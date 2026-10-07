import shutil

import pytest

from cpbenchy.config import UsageError
from cpbenchy.testing import DATA


def test_rerunning_skips_finished_runs(benchtester):
    first = benchtester.run(DATA / "knapsack.opb", DATA / "sat.opb")
    assert len(first) == 2
    assert benchtester.run(DATA / "knapsack.opb", DATA / "sat.opb") == []
    assert len(benchtester.run(DATA / "knapsack.opb", rerun=True)) == 1


def test_runs_left_out_by_selection_are_not_counted_as_done(benchtester):
    # 4 instances; with --limit 1 one of them runs, then --limit 2 runs the next and skips the first
    first = benchtester.run_cli("run", str(DATA), "-s", "ortools", "-t", "10", "-o", "out", "--limit", "1")
    assert first.ret == 0 and "1 runs" in first.stdout and "already in" not in first.stdout
    second = benchtester.run_cli("run", str(DATA), "-s", "ortools", "-t", "10", "-o", "out", "--limit", "2")
    assert "1 runs (1 already in out" in second.stdout
    assert len(second.results) == 2


def test_solvers_and_seeds_multiply_runs(benchtester):
    results = benchtester.run(DATA / "knapsack.opb", solvers=["ortools", "exact"], seeds=[1, 2])
    assert sorted((r.solver, r.seed) for r in results) == [("exact", 1), ("exact", 2), ("ortools", 1), ("ortools", 2)]
    assert len({r.run_id for r in results}) == 4


def test_collect_from_glob_with_selection(benchtester):
    results = benchtester.run(str(DATA / "*.opb"), args=["-k", "sat"])
    assert sorted(r.instance for r in results) == ["sat", "unsat"]
    assert len(benchtester.run(DATA, args=["--limit", "1"], rerun=True)) == 1


def test_collect_from_cpmpy_dataset(benchtester):
    from cpmpy.tools.datasets.core import from_files

    shutil.copytree(DATA, benchtester.path / "tiny")  # the dataset writes metadata sidecars next to the files
    dataset = from_files(benchtester.path / "tiny", extension=".opb")
    results = benchtester.run(dataset)
    assert sorted(r.instance for r in results) == ["knapsack", "sat", "unsat"]
    assert {r.dataset for r in results} == {"tiny"}
    assert all(r.status != "error" for r in results)


def test_inline_executor(benchtester):
    [result] = benchtester.run(DATA / "knapsack.opb", executor="inline")
    assert result.status == "optimal" and result.executor == "inline"


def test_usage_errors(benchtester):
    with pytest.raises(UsageError, match="no such file"):
        benchtester.run("does-not-exist.opb")
    with pytest.raises(UsageError, match="unknown executor"):
        benchtester.run(DATA / "knapsack.opb", executor="nope")


def test_cli_run(benchtester):
    outcome = benchtester.run_cli("run", str(DATA / "knapsack.opb"), "-s", "ortools", "-t", "10", "-o", "out")
    assert outcome.ret == 0, outcome.stderr
    assert [r.status for r in outcome.results] == ["optimal"]
    assert (benchtester.out / "run.json").exists()


def test_cli_missing_solver_is_a_usage_error(benchtester):
    outcome = benchtester.run_cli("run", str(DATA / "knapsack.opb"), "-t", "10")
    assert outcome.ret == 2
    assert "no solver" in outcome.stderr


def test_cli_prints_runs_and_summary(benchtester):
    outcome = benchtester.run_cli("run", str(DATA / "knapsack.opb"), "-s", "ortools", "-t", "10", "-o", "out")
    assert "optimal" in outcome.stdout and "knapsack" in outcome.stdout
    assert "results" in outcome.stdout and "1 runs in" in outcome.stdout


def test_config_file_sets_defaults_and_cli_overrides(benchtester):
    benchtester.makefile(
        "cpbenchy.toml",
        f"""
        sources = ["{DATA / "knapsack.opb"}"]
        solvers = ["ortools"]
        time-limit = 10
        mem-limit = 2048
        out = "out"
        """,
    )
    assert [(r.solver, r.mem_limit_mib) for r in benchtester.run_cli("run").results] == [("ortools", 2048)]
    outcome = benchtester.run_cli("run", "-s", "exact", "-q")
    assert sorted(r.solver for r in outcome.results) == ["exact", "ortools"]


def test_config_file_unknown_key(benchtester):
    benchtester.makefile("pyproject.toml", "[tool.cpbenchy]\nsolverz = 'ortools'\n")
    outcome = benchtester.run_cli("run")
    assert outcome.ret == 2 and "unknown option 'solverz'" in outcome.stderr


def test_cli_show(benchtester):
    benchtester.run(DATA / "knapsack.opb", DATA / "unsat.opb")
    table = benchtester.run_cli("show", "out", "--by", "solver,status").stdout
    assert "optimal" in table and "unsat" in table
    csv_out = benchtester.run_cli("show", "out", "--csv").stdout
    assert csv_out.splitlines()[0].startswith("run_id,instance,dataset,solver")
    assert len(csv_out.splitlines()) == 3
