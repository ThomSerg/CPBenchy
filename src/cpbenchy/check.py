"""Check solutions against their CPMpy model: during a run (`cpbenchy.observers.CheckSolutions`), or after
it, from what the run wrote (`recheck`, `cpbenchy check OUT`).

    from cpbenchy.check import check_solution

    result = check_solution(model, {"x": 3, "y": 4}, objective=3)
    result.valid        # False if anything is wrong
    print(result)       # INVALID (constraint: 1), and each violation

A solution is a {variable name: value} mapping, so it can come from anywhere: a solver, a JSON file,
competition output. `check_solution` checks, in this order:

  1. assignment   every variable of the model has a value (CPMpy's auxiliary variables may be missing)
  2. domain       every value is within its variable's bounds
  3. constraints  every constraint holds under the solution
  4. objective    the objective's value under the solution is within its bounds, and equals the declared
                  objective (what the solver reported), if given

The model's variables keep the values they had before.

Imported inside the measured worker process: Python 3.10 compatible.
"""

import json
import os
import sys
import warnings
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from cpbenchy import formats, refs
from cpbenchy.loader import Loader

KINDS = ("unassigned", "domain", "constraint", "constraint_error", "objective", "objective_mismatch", "objective_error")
"""What a violation can be, in the order they are checked."""

SOLUTION_STATUSES = ("optimal", "feasible")


@dataclass
class Violation:
    kind: str  # one of KINDS
    message: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.message}"


@dataclass
class CheckResult:
    """What checking one solution found. `skipped` says why nothing was checked, e.g. no solution."""

    violations: list[Violation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # what could not be verified, though not wrong
    objective: float | None = None  # computed from the solution
    skipped: str | None = None
    source: str | None = None  # where the solution came from: "worker", "solution.json", "xcsp3.out", ...

    @property
    def valid(self) -> bool:
        return self.skipped is None and not self.violations

    def summary(self) -> str:
        if self.skipped is not None:
            return f"SKIPPED ({self.skipped})"
        if self.valid:
            objective = f", objective {formats.number(self.objective)}" if self.objective is not None else ""
            notes = f" [{len(self.warnings)} warning(s)]" if self.warnings else ""
            return f"VALID{objective}{notes}"
        counts: dict[str, int] = {}
        for v in self.violations:
            counts[v.kind] = counts.get(v.kind, 0) + 1
        return "INVALID (" + ", ".join(f"{k}: {n}" for k, n in counts.items()) + ")"

    def __str__(self) -> str:
        return "\n".join(
            [self.summary(), *(f"  {v}" for v in self.violations), *(f"  [warning] {w}" for w in self.warnings)]
        )

    def to_dict(self, max_violations: int = 10) -> dict[str, Any]:
        """JSON-safe, for a result's `extra["check"]`; at most `max_violations` violations are kept."""
        return {
            "valid": self.valid,
            "summary": self.summary(),
            "source": self.source,
            "objective": self.objective,
            "violations": [str(v) for v in self.violations[:max_violations]],
            "n_violations": len(self.violations),
            "warnings": list(self.warnings),
        }


def check_solution(
    model: Any,
    solution: Mapping[str, Any],
    objective: float | None = None,
    *,
    ignore_aux: bool = True,
    stop_on_unassigned: bool = True,
) -> CheckResult:
    """Check `solution` ({name: value}) against `model` (a `cpmpy.Model`); see the module's docs.

    objective:           the objective value the solver declared, compared with the computed one
    ignore_aux:          don't require values for CPMpy's auxiliary variables (`IV...`, `BV...`); constraints
                         that can't be evaluated without them are skipped, with a warning
    stop_on_unassigned:  stop after the assignment check if variables have no value, rather than report
                         every constraint they appear in
    """
    from cpmpy.expressions.utils import get_bounds
    from cpmpy.transformations.get_variables import get_variables, get_variables_model

    result = CheckResult()
    variables = get_variables_model(model)

    def is_aux(var: Any) -> bool:
        return var.name.startswith(formats.AUX_PREFIXES)

    def misses_only_aux(expr: Any) -> bool:
        missing = [v for v in get_variables(expr) if v.name not in solution]
        return bool(missing) and ignore_aux and all(is_aux(v) for v in missing)

    # 1. assignment
    for var in variables:
        if var.name not in solution and not (ignore_aux and is_aux(var)):
            result.violations.append(Violation("unassigned", f"{var.name} has no value"))
    if result.violations and stop_on_unassigned:
        return result

    # 2. domain
    for var in variables:
        if var.name not in solution:
            continue
        val, (lb, ub) = solution[var.name], var.get_bounds()
        try:
            if not lb <= int(val) <= ub:
                result.violations.append(Violation("domain", f"{var.name} = {val} is outside its domain {lb}..{ub}"))
        except (TypeError, ValueError) as e:
            result.violations.append(Violation("domain", f"{var.name} = {val!r} is not an integer: {e}"))

    saved = {var: var._value for var in variables}
    try:
        for var in variables:
            var._value = _scalar(solution[var.name]) if var.name in solution else None

        # 3. constraints
        skipped = 0
        for constraint in _flatten(model.constraints):
            if misses_only_aux(constraint):
                skipped += 1
                continue
            try:
                val = _truth(constraint.value())
            except Exception as e:
                result.violations.append(Violation("constraint_error", f"evaluating {constraint}: {e}"))
                continue
            if val is None:
                result.violations.append(Violation("constraint_error", f"{constraint} has no value"))
            elif not val:
                result.violations.append(Violation("constraint", f"violated: {constraint}"))
        if skipped:
            result.warnings.append(f"{skipped} constraint(s) use auxiliary variables without a value: not checked")

        # 4. objective
        if model.has_objective():
            _check_objective(model.objective_, objective, result, misses_only_aux(model.objective_), get_bounds)
    finally:
        for var, val in saved.items():
            var._value = val
    return result


def _check_objective(expr: Any, declared: float | None, result: CheckResult, aux_only: bool, get_bounds) -> None:
    try:
        lb, ub = (_scalar(b) for b in get_bounds(expr))
        if aux_only:  # it can't be computed from the solution: at least check the declared value
            if declared is None:
                result.warnings.append("the objective uses auxiliary variables without a value: not checked")
            elif not lb <= declared <= ub:
                result.violations.append(Violation("objective", f"declared objective {declared} is outside {lb}..{ub}"))
            else:
                result.warnings.append(
                    "the objective uses auxiliary variables without a value: only its bounds checked"
                )
            result.objective = declared
            return
        computed = _scalar(expr.value())
        result.objective = computed
        if computed is None:
            result.violations.append(Violation("objective_error", "the objective has no value"))
            return
        if not lb <= computed <= ub:
            result.violations.append(Violation("objective", f"the objective {computed} is outside {lb}..{ub}"))
        if declared is None:
            result.warnings.append(f"no declared objective to compare the computed {formats.number(computed)} with")
        elif abs(computed - declared) > 1e-6 * max(1.0, abs(declared)):
            result.violations.append(
                Violation(
                    "objective_mismatch", f"the objective is {computed} under the solution, but {declared} was declared"
                )
            )
    except Exception as e:
        result.violations.append(Violation("objective_error", f"evaluating the objective: {e}"))


def _flatten(constraints: Any) -> Iterator[Any]:
    from cpmpy.expressions.utils import is_any_list

    for c in constraints:
        if is_any_list(c):
            yield from _flatten(c)
        else:
            yield c


def _scalar(val: Any) -> Any:
    """A plain Python bool, int or float (CPMpy values are often numpy's)."""
    if val is None or isinstance(val, (bool, int, float)):
        return val
    item = getattr(val, "item", None)
    return item() if callable(item) else val


def _truth(val: Any) -> Any:
    size = getattr(val, "size", None)
    if size is not None and not isinstance(val, (bool, int, float)):  # a numpy array or scalar
        if size == 0:
            return None
        if size == 1:
            return _scalar(val.flat[0]) if hasattr(val, "flat") else _scalar(val)
        raise ValueError("it evaluates to an array, not a truth value")
    return val


# --- after the run ---


def _from_json(text: str) -> tuple[dict[str, Any], float | None]:
    data = json.loads(text)
    return data["solution"], data.get("objective")


def _from_xcsp3(text: str) -> tuple[dict[str, Any], float | None]:
    _, objective, values = formats.read_competition_output(text)
    solution, cost = formats.read_xcsp3_instantiation("\n".join(values))
    return solution, cost if cost is not None else objective


def _from_literals(text: str) -> tuple[dict[str, Any], float | None]:
    _, objective, values = formats.read_competition_output(text)
    return formats.read_literals(" ".join(values)), objective


def _from_bits(text: str) -> tuple[dict[str, Any], float | None]:
    _, objective, values = formats.read_competition_output(text)
    return formats.read_bits("".join(values)), objective


SOLUTION_FILES = {
    "solution.json": _from_json,  # SaveSolution
    "xcsp3.out": _from_xcsp3,  # XCSP3Output
    "pb.out": _from_literals,  # PBOutput
    "sat.out": _from_literals,  # SATOutput
    "maxsat.out": _from_bits,  # MaxSATOutput
}
"""Artifacts a run's solution can be read from, in order of preference -> their reader."""


class _CNFLoader(Loader):
    def load(self, instance):
        return formats.load_cnf(instance.path, self.opener(instance.path))


def read_solution(out: str | Path, run_id: str) -> tuple[dict[str, Any], float | None, str] | None:
    """A run's solution from its artifacts in `out/logs`: ({name: value}, declared objective, artifact
    name), or None if it wrote none of `SOLUTION_FILES`."""
    for name, read in SOLUTION_FILES.items():
        path = Path(out) / "logs" / f"{run_id}.{name}"
        if path.exists():
            solution, objective = read(path.read_text())
            return solution, objective, name
    return None


def load_model(out: str | Path, run_id: str, loader: Any = None) -> Any:
    """A run's model, loaded again as the worker loaded it (from its `logs/<run_id>.job.json`), or with
    `loader` (a `Loader`) if given. Relative paths are relative to the directory the run was started in."""
    from cpbenchy.spec import RunSpec

    job = json.loads((Path(out) / "logs" / f"{run_id}.job.json").read_text())
    spec = RunSpec.from_dict(job["spec"])
    cwd = Path(job.get("cwd") or os.getcwd())
    instance = replace(spec.instance, path=str(cwd / spec.instance.path))
    if loader is None and spec.loader:
        target, _, rest = spec.loader.partition(":")
        if target.endswith(".py"):
            target = str(cwd / target)
        if str(cwd) not in sys.path:
            sys.path.append(str(cwd))  # for loaders from local modules
        loader = refs.load(f"{target}:{rest}" if rest else target)
    if loader is None:
        # SATOutput loads CNF itself, to keep the variables' numbers; SaveSolution then has them too
        loader = _CNFLoader() if instance.format == "cnf" else Loader()
    with warnings.catch_warnings():  # loading many models in one process: CPMpy warns about reused names
        warnings.filterwarnings("ignore", message="Loading a model whilst")
        return loader.load(instance)


def recheck(out: str | Path, results: Any = None, loader: Any = None) -> Iterator[tuple[Any, CheckResult]]:
    """Check the solutions of runs in `out` after the fact: yields (RunResult, CheckResult) for each run
    (of `results`, default: all stored in `out`). Each model is loaded again, and each solution read from
    what the run wrote (`SOLUTION_FILES`): run with `SaveSolution` or a competition output observer."""
    from cpbenchy.result import Results

    for result in Results.load(out) if results is None else results:
        if result.status not in SOLUTION_STATUSES:
            yield result, CheckResult(skipped=f"status {result.status}")
            continue
        found = read_solution(out, result.run_id)
        if found is None:
            names = ", ".join(SOLUTION_FILES)
            yield result, CheckResult(skipped=f"no solution file ({names}); run with SaveSolution to have one")
            continue
        solution, objective, source = found
        try:
            model = load_model(out, result.run_id, loader)
        except Exception as e:
            yield result, CheckResult(skipped=f"loading the model failed: {type(e).__name__}: {e}", source=source)
            continue
        if objective is None:
            objective = result.objective
        check = check_solution(model, solution, objective)
        check.source = source
        yield result, check
