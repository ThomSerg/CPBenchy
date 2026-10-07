"""The ready-made observers (`cpbenchy.observers`) and solution formats (`cpbenchy.formats`)."""

import importlib.util
import json
import os
import shutil
from pathlib import Path

import cpmpy as cp
import pytest

from cpbenchy import formats, observers
from cpbenchy.testing import DATA

EXAMPLE_DATA = Path(__file__).parents[1] / "examples" / "data"


def output(benchtester, result, name):
    return (benchtester.out / "logs" / f"{result.run_id}.{name}").read_text()


# --- formats ---


def test_literals_bits_and_dimacs_lines():
    assignment = {1: True, 3: False, 4: True}
    assert formats.literals(assignment, prefix="x") == ["x1", "-x2", "-x3", "x4"]
    assert formats.literals(assignment, 5) == ["1", "-2", "-3", "4", "-5"]
    assert formats.bits(assignment) == "1001"
    assert formats.dimacs_values(assignment, width=3) == ["1 -2 -3", "4 0"]


def test_status_lines():
    assert formats.status_line("optimal", True) == "s OPTIMUM FOUND"
    assert formats.status_line("optimal", False) == "s SATISFIABLE"
    assert formats.status_line("feasible", True) == "s SATISFIABLE"
    assert formats.status_line("unsat", None) == "s UNSATISFIABLE"
    assert formats.status_line("timeout", None) == "s UNKNOWN"


def test_xcsp3_instantiation_and_solution_dict():
    x, b = cp.intvar(0, 5, name="x"), cp.boolvar(name="b")
    aux = cp.intvar(0, 5)  # unnamed: a generated name, as auxiliary variables have
    model = cp.Model(x == 3, b, aux == x)
    assert model.solve()
    variables = formats.instance_variables(model)
    assert [v.name for v in variables] == ["x", "b"]
    assert formats.solution_dict(variables) == {"x": 3, "b": True}
    xml = formats.xcsp3_instantiation(variables, cost=7.0)
    assert '<instantiation type="optimum" cost="7">' in xml
    assert "<list>x b</list>" in xml and "<values>3 1</values>" in xml
    assert 'type="solution"' in formats.xcsp3_instantiation(variables)


def test_header_size():
    assert formats.header_size(str(EXAMPLE_DATA / "tiny.cnf")) == 4
    assert formats.header_size(str(EXAMPLE_DATA / "tiny.wcnf")) == 3
    assert formats.header_size(str(DATA / "knapsack.opb")) == 4


def test_load_cnf_names_variables_by_number():
    model = formats.load_cnf(str(EXAMPLE_DATA / "tiny.cnf"))
    assert sorted(v.name for v in formats.instance_variables(model)) == ["x1", "x2", "x3"]
    assert model.solve()
    assignment = formats.assignment(formats.instance_variables(model))
    assert (assignment[1], assignment[2]) == (False, True)


# --- competition output ---


def test_pb_output(benchtester):
    results = benchtester.run(DATA / "knapsack.opb", DATA / "unsat.opb", plugins=[observers.PBOutput()], quiet=True)
    out = {r.instance: output(benchtester, r, "pb.out") for r in results}
    assert out["knapsack"].splitlines()[-2:] == ["s OPTIMUM FOUND", "v x1 x2 -x3 x4"]
    assert "o -9" in out["knapsack"]
    assert out["unsat"] == "s UNSATISFIABLE\n"


def test_maxsat_output(benchtester):
    [result] = benchtester.run(EXAMPLE_DATA / "tiny.wcnf", args=["-p", "cpbenchy.observers:MaxSATOutput"])
    assert output(benchtester, result, "maxsat.out").splitlines()[-3:] == ["o 2", "s OPTIMUM FOUND", "v 010"]


def test_sat_output_numbers_every_variable(benchtester):
    [result] = benchtester.run(EXAMPLE_DATA / "tiny.cnf", plugins=[observers.SATOutput()], quiet=True)
    assert result.status == "feasible"
    lines = output(benchtester, result, "sat.out").splitlines()
    assert lines[0] == "s SATISFIABLE"
    literals = " ".join(line.removeprefix("v ") for line in lines[1:]).split()
    assert literals[:2] == ["-1", "2"] and literals[3:] == ["-4", "0"]


def test_competition_output_only_for_its_format(benchtester):
    [result] = benchtester.run(DATA / "knapsack.opb", plugins=[observers.SATOutput()], quiet=True)
    assert not (benchtester.out / "logs" / f"{result.run_id}.sat.out").exists()


@pytest.mark.skipif(importlib.util.find_spec("pycsp3") is None, reason="needs pycsp3 to load XCSP3")
def test_xcsp3_output(benchtester):
    [result] = benchtester.run(EXAMPLE_DATA / "tiny_cop.xml", plugins=[observers.XCSP3Output()], quiet=True)
    out = output(benchtester, result, "xcsp3.out")
    assert "s OPTIMUM FOUND" in out and 'v <instantiation type="optimum" cost="3">' in out


@pytest.mark.skipif(
    not (os.environ.get("XCSP3_CHECKER") and shutil.which("java")),
    reason="set XCSP3_CHECKER to the XCSP3 checker jar (and have java) to test the official check",
)
def test_xcsp3_official_checker(benchtester):
    plugin = observers.XCSP3Output(checker=os.environ["XCSP3_CHECKER"])
    [result] = benchtester.run(EXAMPLE_DATA / "tiny_cop.xml", plugins=[plugin], quiet=True)
    assert result.extra["xcsp3_check"] == "OK"


# --- solutions and models ---


def test_save_solution(benchtester):
    [result] = benchtester.run(DATA / "knapsack.opb", plugins=[observers.SaveSolution(record=True)], quiet=True)
    saved = json.loads(output(benchtester, result, "solution.json"))
    assert saved["status"] == "optimal" and saved["objective"] == -9
    assert saved["solution"] == {"x1": True, "x2": True, "x3": False, "x4": True} == result.extra["solution"]


def test_model_size(benchtester):
    [result] = benchtester.run(DATA / "knapsack.opb", args=["-p", "cpbenchy.observers:ModelSize"], quiet=True)
    assert (result.extra["n_variables"], result.extra["n_boolvars"], result.extra["n_constraints"]) == (4, 4, 1)


def test_check_solutions_catches_a_wrong_answer_before_other_observers(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        @cpbenchy.hookimpl(wrapper=True)
        def cpbenchy_worker_solve(ctx):
            result = yield
            if ctx.spec.seed == 666:  # a "buggy solver": flip a variable in its solution
                var = next(v for v in ctx.solver.user_vars if v.name == "x3")
                var._value = not var.value()
            return result
        """
    )
    plugins = [observers.PBOutput(), observers.CheckSolutions()]
    good, bad = sorted(
        benchtester.run(DATA / "knapsack.opb", seeds=[1, 666], plugins=plugins, quiet=True), key=lambda r: r.seed
    )
    assert good.status == "optimal" and good.extra["check"]["valid"] is True
    assert bad.status == "error" and bad.extra["check"]["valid"] is False
    assert "wrong solution: [constraint] violated" in bad.error
    assert output(benchtester, bad, "pb.out").splitlines()[-1] == "s UNKNOWN"  # it saw the corrected status
