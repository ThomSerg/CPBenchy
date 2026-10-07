"""Solutions in the formats of instance files and solver competitions, for your own observers.

The observers in `cpbenchy.observers` use these to write competition output; use them directly for
anything else that needs a solution as text:

    from cpbenchy import formats

    class MyOutput(cpbenchy.Observer):
        def on_finish(self, ctx):
            if ctx.status in ("optimal", "feasible"):
                variables = formats.instance_variables(ctx.model)
                ctx.artifact("sol.xml").write_text(formats.xcsp3_instantiation(variables, ctx.objective))

Most functions take an assignment of numbered variables (`{1: True, 2: False, ...}`, from variables
named `x1`, `x2`, ... as the DIMACS, WCNF and OPB loaders name them) and the number of variables in the
instance (`header_size`), so variables that occur in no constraint still get a value.

Imported inside the measured worker process: Python 3.10 compatible, CPMpy imported only when needed.
"""

import builtins
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from typing import Any

AUX_PREFIXES = ("IV", "BV", "B#")
"""Names of CPMpy's auxiliary variables, which loaders and transformations introduce."""

STATUS_LINES = {"unsat": "s UNSATISFIABLE", "unknown": "s UNKNOWN"}

_HEADERS = (
    re.compile(r"^p\s+w?cnf\s+(\d+)"),  # DIMACS CNF and WCNF before 2022: p cnf <vars> <clauses>
    re.compile(r"^\*\s*#variable=\s*(\d+)"),  # OPB: * #variable= <vars> #constraint= <constraints>
)


def instance_variables(model: Any) -> list:
    """The decision variables of a `cpmpy.Model`, in order of appearance, without CPMpy's auxiliary ones."""
    from cpmpy.transformations.get_variables import get_variables_model

    return [v for v in get_variables_model(model) if not v.name.startswith(AUX_PREFIXES)]


def value(var: Any) -> Any:
    """A variable's value as a plain `bool` or `int` (None if it has none), e.g. for JSON."""
    val = var.value()
    if val is None:
        return None
    return bool(val) if var.is_bool() else int(val)


def solution_dict(variables: Iterable[Any]) -> dict[str, Any]:
    """{name: value} of these variables."""
    return {v.name: value(v) for v in variables}


def number(x: float | None) -> str:
    """An objective value as text: integral values without a decimal point."""
    if x is None:
        return ""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def status_line(status: str | None, has_objective: bool | None) -> str:
    """The `s` line of the XCSP3, PB, MaxSAT and SAT competitions for a run's status."""
    if status == "optimal" and has_objective:
        return "s OPTIMUM FOUND"
    if status in ("optimal", "feasible"):
        return "s SATISFIABLE"
    return STATUS_LINES.get(status or "unknown", "s UNKNOWN")


def assignment(variables: Iterable[Any], prefix: str = "x") -> dict[int, bool]:
    """{number: value} of the Boolean variables named `<prefix><number>`; the others are left out."""
    n = len(prefix)
    return {
        int(v.name[n:]): bool(v.value())
        for v in variables
        if v.name.startswith(prefix) and v.name[n:].isdigit() and v.value() is not None
    }


def literals(assignment: dict[int, bool], n: int | None = None, prefix: str = "") -> list[str]:
    """Each variable 1..n as a literal: `x1`/`-x1` with prefix "x" (OPB), `1`/`-1` without (DIMACS).
    Variables without a value are false; n defaults to the highest number in the assignment."""
    n = n if n is not None else max(assignment, default=0)
    return [f"{prefix}{i}" if assignment.get(i) else f"-{prefix}{i}" for i in range(1, n + 1)]


def bits(assignment: dict[int, bool], n: int | None = None) -> str:
    """Variables 1..n as a string of 0s and 1s, as the MaxSAT Evaluation's `v` line."""
    n = n if n is not None else max(assignment, default=0)
    return "".join("1" if assignment.get(i) else "0" for i in range(1, n + 1))


def dimacs_values(assignment: dict[int, bool], n: int | None = None, width: int = 20) -> list[str]:
    """The `v` lines of the SAT competition (without the `v `), `width` literals per line, ending in 0."""
    lits = [*literals(assignment, n), "0"]
    return [" ".join(lits[i : i + width]) for i in range(0, len(lits), width)]


def xcsp3_instantiation(variables: Iterable[Any], cost: float | None = None) -> str:
    """The solution as an XCSP3 `<instantiation>` element: of type "optimum" with a `cost` if given, else
    "solution". Variables without a value get `*`."""
    variables = list(variables)
    if cost is not None:
        root = ET.Element("instantiation", type="optimum", cost=number(cost))
    else:
        root = ET.Element("instantiation", type="solution")
    ET.SubElement(root, "list").text = " ".join(v.name for v in variables)
    ET.SubElement(root, "values").text = " ".join(
        str(int(v.value())) if v.value() is not None else "*" for v in variables
    )
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def header_size(path: str, open: Callable = builtins.open) -> int | None:
    """The number of variables a DIMACS CNF, WCNF or OPB file declares in its header, if it has one."""
    with open(path, "rt") as f:
        for line in f:
            for header in _HEADERS:
                match = header.match(line)
                if match:
                    return int(match.group(1))
            if line.strip() and not line.startswith(("c", "*")):  # the header comes before the content
                return None
    return None


def load_cnf(path: str, open: Callable = builtins.open) -> Any:
    """A DIMACS CNF file as a `cpmpy.Model` with variables named `x1`, `x2`, ..., so solutions can be
    written in DIMACS (CPMpy's own loader gives them generated names)."""
    import cpmpy as cp

    variables: dict[int, Any] = {}

    def literal(lit: int) -> Any:
        if abs(lit) not in variables:
            variables[abs(lit)] = cp.boolvar(name=f"x{abs(lit)}")
        return variables[abs(lit)] if lit > 0 else ~variables[abs(lit)]

    clauses, clause = [], []
    with open(path, "rt") as f:
        for line in f:
            if not line.strip() or line.startswith(("c", "p", "%")):
                continue
            for token in line.split():
                lit = int(token)
                if lit == 0:
                    clauses.append(cp.any(clause) if clause else cp.BoolVal(False))
                    clause = []
                else:
                    clause.append(literal(lit))
    if clause:  # a last clause without its 0
        clauses.append(cp.any(clause))
    return cp.Model(clauses)


# --- reading solutions back, e.g. to check them after the run (`cpbenchy.check`) ---


def read_competition_output(text: str) -> tuple[str | None, float | None, list[str]]:
    """Competition output -> (the `s` line's answer, the last `o` value, the `v` lines without `v `)."""
    status, objective, values = None, None, []
    for line in text.splitlines():
        if line.startswith("s "):
            status = line[2:].strip()
        elif line.startswith("o "):
            objective = float(line[2:].strip())
        elif line.startswith("v ") or line == "v":
            values.append(line[2:])
    return status, objective, values


def read_xcsp3_instantiation(text: str) -> tuple[dict[str, int], float | None]:
    """An XCSP3 `<instantiation>` -> ({name: value}, its cost if it has one). Variables with value `*` are
    left out. Lists must name each variable (no `x[]` shorthands), as `xcsp3_instantiation` writes them."""
    root = ET.fromstring(text)
    names = (root.findtext("list") or "").split()
    values = (root.findtext("values") or "").split()
    if len(names) != len(values):
        raise ValueError(f"the instantiation has {len(names)} variables but {len(values)} values")
    cost = root.get("cost")
    solution = {name: int(val) for name, val in zip(names, values, strict=True) if val != "*"}
    return solution, float(cost) if cost is not None else None


def read_literals(text: str, prefix: str = "x") -> dict[str, bool]:
    """Literals (`x1 -x2` or DIMACS `1 -2 0`) -> {name: value}; numbers become `<prefix><number>`."""
    solution = {}
    for token in text.split():
        negated = token.startswith("-")
        name = token.lstrip("-")
        if name == "0":
            continue
        solution[prefix + name if name.isdigit() else name] = not negated
    return solution


def read_bits(text: str, prefix: str = "x") -> dict[str, bool]:
    """A string of 0s and 1s (MaxSAT) -> {"x1": ..., "x2": ...}."""
    return {f"{prefix}{i}": bit == "1" for i, bit in enumerate(text.strip(), start=1)}
