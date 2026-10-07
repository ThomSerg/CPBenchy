"""Checking solutions: `cpbenchy.check.check_solution`, and rechecking stored runs (`cpbenchy check`)."""

import importlib.util
import json
import shutil
from pathlib import Path

import cpmpy as cp
import pytest

from cpbenchy import observers
from cpbenchy.check import check_solution, recheck
from cpbenchy.result import Results
from cpbenchy.testing import DATA

EXAMPLE_DATA = Path(__file__).parents[1] / "examples" / "data"


@pytest.fixture
def model():
    x, y = cp.intvar(0, 5, name="x"), cp.intvar(0, 5, name="y")
    return cp.Model(x + y == 7, minimize=x)


def kinds(result):
    return [v.kind for v in result.violations]


# --- check_solution ---


def test_a_valid_solution(model):
    result = check_solution(model, {"x": 3, "y": 4}, objective=3)
    assert result.valid and result.objective == 3 and not result.warnings
    assert result.summary() == "VALID, objective 3"


def test_each_kind_of_violation(model):
    assert kinds(check_solution(model, {"x": 3})) == ["unassigned"]
    assert kinds(check_solution(model, {"x": 3, "y": 5}, objective=3)) == ["constraint"]
    assert kinds(check_solution(model, {"x": 1, "y": 6}, objective=1)) == ["domain"]
    assert kinds(check_solution(model, {"x": 3, "y": 4}, objective=2)) == ["objective_mismatch"]
    assert check_solution(model, {"x": 3, "y": 5}).summary() == "INVALID (constraint: 1)"


def test_without_a_declared_objective_it_warns(model):
    result = check_solution(model, {"x": 3, "y": 4})
    assert result.valid and result.warnings


def test_the_model_keeps_its_values(model):
    assert model.solve()
    before = {v.name: v.value() for v in model.constraints[0].args[0].args}
    check_solution(model, {"x": 0, "y": 0})
    assert {v.name: v.value() for v in model.constraints[0].args[0].args} == before


def test_auxiliary_variables_may_be_missing():
    x, aux = cp.intvar(0, 5, name="x"), cp.intvar(0, 5)  # unnamed: an auxiliary name
    model = cp.Model(aux == x + 1, x >= 2)
    result = check_solution(model, {"x": 3})
    assert result.valid and "auxiliary" in result.warnings[0]
    assert kinds(check_solution(model, {"x": 3}, ignore_aux=False)) == ["unassigned"]


def test_to_dict_is_json_safe(model):
    record = check_solution(model, {"x": 3, "y": 5}).to_dict()
    assert json.loads(json.dumps(record))["valid"] is False
    assert record["violations"] == ["[constraint] violated: (x) + (y) == 7"]


# --- rechecking stored runs ---


def run_and_recheck(benchtester, *sources, plugins):
    benchtester.run(*sources, plugins=plugins, quiet=True)
    return {r.instance: check for r, check in recheck(benchtester.out)}


def test_recheck_from_saved_solutions(benchtester):
    checks = run_and_recheck(benchtester, DATA, plugins=[observers.SaveSolution()])
    assert checks["knapsack"].valid and checks["knapsack"].source == "solution.json"
    assert checks["knapsack"].objective == -9
    assert checks["unsat"].skipped == "status unsat"


@pytest.mark.parametrize(
    ("instance", "observer", "source"),
    [
        (DATA / "knapsack.opb", observers.PBOutput(), "pb.out"),
        (EXAMPLE_DATA / "tiny.wcnf", observers.MaxSATOutput(), "maxsat.out"),
        (EXAMPLE_DATA / "tiny.cnf", observers.SATOutput(), "sat.out"),
        pytest.param(
            EXAMPLE_DATA / "tiny_cop.xml",
            observers.XCSP3Output(),
            "xcsp3.out",
            marks=pytest.mark.skipif(importlib.util.find_spec("pycsp3") is None, reason="needs pycsp3"),
        ),
    ],
)
def test_recheck_from_competition_output(benchtester, instance, observer, source):
    [check] = run_and_recheck(benchtester, instance, plugins=[observer]).values()
    assert check.valid, str(check)
    assert check.source == source


def test_recheck_without_a_solution_file_skips(benchtester):
    [check] = run_and_recheck(benchtester, DATA / "knapsack.opb", plugins=[]).values()
    assert "no solution file" in check.skipped


def test_cli_finds_a_tampered_solution_and_writes_verdicts(benchtester, monkeypatch, tmp_path):
    # a relative instance path, rechecked from another directory: relative to where the run started
    shutil.copy(DATA / "knapsack.opb", benchtester.path / "knapsack.opb")
    shutil.copy(DATA / "sat.opb", benchtester.path / "sat.opb")
    benchtester.run("knapsack.opb", "sat.opb", plugins=[observers.SaveSolution()], quiet=True)
    knapsack = next(r for r in Results.load(benchtester.out) if r.instance == "knapsack")
    saved = benchtester.out / "logs" / f"{knapsack.run_id}.solution.json"
    data = json.loads(saved.read_text())
    data["solution"]["x3"] = True  # over capacity
    saved.write_text(json.dumps(data))

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    outcome = benchtester.run_cli("check", str(benchtester.out), "--write")
    assert outcome.ret == 1
    assert "knapsack: INVALID (constraint: 1" in outcome.stdout
    assert "1 valid, 1 invalid, 0 not checked" in outcome.stdout
    stored = {r.instance: r.extra["check"] for r in Results.load(benchtester.out)}
    assert stored["knapsack"]["valid"] is False and stored["sat"]["valid"] is True
