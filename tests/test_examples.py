"""The examples in examples/ keep working."""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

import cpbenchy
from cpbenchy.testing import DATA

EXAMPLES = Path(__file__).parents[1] / "examples"
PLUGINS = EXAMPLES / "plugins"


def plugin_args(*refs):
    return [arg for ref in refs for arg in ("-p", str(ref))]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # as importing it would, so its classes can be found from their module
    spec.loader.exec_module(module)
    return module


def test_sqlite_store(benchtester):
    benchtester.run(
        DATA / "knapsack.opb", DATA / "unsat.opb", args=plugin_args(PLUGINS / "sqlite_store.py"), quiet=True
    )
    db = sqlite3.connect(benchtester.path / "results.db")  # the default path, in the current directory
    rows = db.execute("select instance, status, objective from runs order by instance").fetchall()
    assert rows == [("knapsack", "optimal", -9), ("unsat", "unsat", None)]


def test_formulations_script(benchtester, capsys):
    formulations = load_script("formulations")
    formulations.main(["--sizes", "6", "8", "--out", str(benchtester.out), "--time-limit", "10"])
    results = cpbenchy.load(benchtester.out)
    assert sorted((r.instance, r.loader) for r in results) == [
        ("nqueens-6", "NQueens('alldifferent')"),
        ("nqueens-6", "NQueens('pairwise')"),
        ("nqueens-8", "NQueens('alldifferent')"),
        ("nqueens-8", "NQueens('pairwise')"),
    ]
    assert all(r.solved for r in results)
    assert "nqueens-8" in capsys.readouterr().out


def test_knapsack_json_loader(benchtester):
    loader = f"{EXAMPLES / 'loaders' / 'knapsack_json.py'}:KnapsackJSON"
    outcome = benchtester.run_cli(
        "run",
        str(EXAMPLES / "data" / "knapsack_small.json"),
        "-s",
        "ortools",
        "-t",
        "10",
        "-o",
        "out",
        "--loader",
        loader,
    )
    assert outcome.ret == 0, outcome.stderr
    [result] = outcome.results
    assert (result.status, result.objective, result.loader) == ("optimal", 90, "KnapsackJSON")


def test_param_sweep_script(benchtester, capsys):
    sweep = load_script("param_sweep")
    sweep.main([str(DATA / "knapsack.opb"), str(DATA / "sat.opb"), "--out", str(benchtester.out), "--time-limit", "10"])
    out = capsys.readouterr().out
    assert "8 runs" in out
    assert "4 workers            solved   2/2" in out


def test_analyze_script(benchtester, capsys):
    pytest.importorskip("matplotlib")
    benchtester.run(DATA, solvers=["ortools", "exact"], quiet=True)
    analyze = load_script("analyze")
    analyze.main([str(benchtester.out), "--plot", str(benchtester.path / "cactus.png")])
    out = capsys.readouterr().out
    assert "Virtual best solver: 4 solved" in out
    assert (benchtester.path / "cactus.png").stat().st_size > 1000


def test_every_example_is_tested():
    tested = Path(__file__).read_text()
    for path in EXAMPLES.rglob("*.py"):
        assert path.stem in tested, f"{path.relative_to(EXAMPLES)} has no test"
