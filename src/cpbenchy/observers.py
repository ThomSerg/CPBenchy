"""Ready-made observers: competition output, checking and saving solutions, model statistics.

Use one with `-p cpbenchy.observers:NAME` (arguments as `-p "cpbenchy.observers:XCSP3Output(checker='c.jar')"`),
or `plugins=[cpbenchy.observers.NAME()]` in Python:

    XCSP3Output     XCSP3 competition output (`o`, `s`, `v` lines with an <instantiation>); optionally checked
    PBOutput        Pseudo-Boolean competition output (`v x1 -x2 ...`)
    MaxSATOutput    MaxSAT Evaluation output (`v 0101...`)
    SATOutput       SAT competition output (`v 1 -2 ... 0`)
    SaveSolution    the solution as JSON, in `logs/<run_id>.solution.json` (and optionally in the result)
    CheckSolutions  re-check every solution against the model; wrong answers become errors
    ModelSize       record the number of variables and constraints of each model

Competition output goes to each run's `logs/<run_id>.<name>.out`, written in the worker as a competition
solver would print it, so it counts toward the run's time. With `cpbenchy solve` (a submission), it goes to
stdout, where competitions read it. Subclass `CompetitionOutput` for other formats;
`cpbenchy.formats` has the pieces.

Name the ones you want: loading the whole module (`-p cpbenchy.observers`) would enable all its observers.

Imported inside the measured worker process: Python 3.10 compatible.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cpbenchy import check, hookimpl
from cpbenchy import formats as fmt
from cpbenchy.loader import Loader
from cpbenchy.observer import Observer


class CompetitionOutput(Observer):
    """Writes `o` lines for each solution while solving, then an `s` line and the solution as `v` lines,
    to `<run_id>.<name>.out`. Override `solution` (and set `name` and `formats`) for a new format."""

    name = "competition"
    formats = ()  # observes nothing by itself

    def solution(self, ctx) -> list[str]:
        """The solution, as the lines after `v `."""
        raise NotImplementedError

    def on_solution(self, ctx, objective):
        if objective is not None:
            self.write(ctx, f"o {fmt.number(objective)}")

    def on_finish(self, ctx):
        if ctx.status in ("optimal", "feasible"):
            status = fmt.status_line(ctx.status, ctx.model.has_objective())
            self.write(ctx, status, *(f"v {line}" for line in self.solution(ctx)))
        elif ctx.status == "unsat":
            self.write(ctx, "s UNSATISFIABLE")
        else:
            self.write(ctx, f"c {ctx.error or 'no solution within the limits'}", "s UNKNOWN")

    def output(self, ctx_or_run) -> Path:
        """The output file, from the worker's `ctx` or the parent's `run`."""
        return ctx_or_run.artifact(f"{self.name}.out")

    def write(self, ctx, *lines: str) -> None:
        text = "".join(line + "\n" for line in lines)
        if ctx.options.get("stdout"):
            sys.stdout.write(text)
            sys.stdout.flush()
        else:
            with open(self.output(ctx), "a") as f:
                f.write(text)


class XCSP3Output(CompetitionOutput):
    """XCSP3 competition output. With `checker` (the path of the competition's checker jar, needs java),
    the parent also checks every solution after its run, outside the measured time, and records the
    verdict as `extra["xcsp3_check"]`: "OK", or what is wrong."""

    name = "xcsp3"
    formats = ("xcsp3",)

    def __init__(self, checker=None):
        self.checker = checker

    def solution(self, ctx):
        cost = ctx.objective if ctx.model.has_objective() else None
        return fmt.xcsp3_instantiation(fmt.instance_variables(ctx.model), cost).splitlines()

    def on_result(self, run, result):
        output = self.output(run)
        if self.checker and result.status in ("optimal", "feasible") and output.exists():
            result.extra["xcsp3_check"] = xcsp3_check(self.checker, run.spec.instance.path, output)


class PBOutput(CompetitionOutput):
    """Pseudo-Boolean competition output: every variable as `x1` or `-x1`."""

    name = "pb"
    formats = ("opb",)

    def solution(self, ctx):
        return [" ".join(fmt.literals(*numbered(ctx), prefix="x"))]


class MaxSATOutput(CompetitionOutput):
    """MaxSAT Evaluation output: the cost as `o`, the assignment as a string of 0s and 1s."""

    name = "maxsat"
    formats = ("wcnf",)

    def on_finish(self, ctx):
        if ctx.status in ("optimal", "feasible"):
            cost = fmt.number(ctx.objective) if ctx.objective is not None else "0"
            # without soft clauses, any solution is optimal
            optimal = ctx.status == "optimal" or not ctx.model.has_objective()
            self.write(ctx, f"o {cost}", "s OPTIMUM FOUND" if optimal else "s SATISFIABLE")
            self.write(ctx, *(f"v {line}" for line in self.solution(ctx)))
        else:
            super().on_finish(ctx)

    def solution(self, ctx):
        return [fmt.bits(*numbered(ctx))]


class SATOutput(CompetitionOutput):
    """SAT competition output: `v` lines of DIMACS literals, ending in 0.

    CPMpy's CNF loader names variables in a way that loses their numbers, so unless the run has its own
    loader, this loads `.cnf` files with `cpbenchy.formats.load_cnf` instead (timed as `parse_s`, as usual).
    """

    name = "sat"
    formats = ("cnf",)

    def on_load(self, ctx):
        if ctx.spec.loader is None:
            path = ctx.spec.instance.path
            return fmt.load_cnf(path, Loader().opener(path))
        return None

    def solution(self, ctx):
        return fmt.dimacs_values(*numbered(ctx))


class SaveSolution(Observer):
    """The final solution as JSON, `{"status": ..., "objective": ..., "solution": {name: value}}`, in
    `<run_id>.solution.json` (in the parent: `run.artifact("solution.json")`). With `record=True`, also in
    the result, as `extra["solution"]`: handy for small models, but it makes results.jsonl large."""

    def __init__(self, record=False):
        self.record = record

    def on_finish(self, ctx):
        if ctx.status not in ("optimal", "feasible"):
            return
        solution = fmt.solution_dict(fmt.instance_variables(ctx.model))
        data = {"status": ctx.status, "objective": ctx.objective, "solution": solution}
        ctx.artifact("solution.json").write_text(json.dumps(data))
        if self.record:
            ctx.record("solution", solution)


class CheckSolutions:
    """Check every solution against the model, to catch wrong answers from solvers (or from CPMpy's
    transformations), with `cpbenchy.check.check_solution`: every variable has a value within its domain,
    every constraint holds, and the objective matches what the solver reported.

    Every checked run gets `extra["check"]` (`valid`, `summary`, `violations`, `warnings`), and a run with
    a wrong solution becomes an `error`. It runs before the other observers' `on_finish` (it is a plugin
    with a `tryfirst` hook, not an observer), so competition output and saved solutions already see the
    corrected status. To check solutions after the fact instead, see `cpbenchy check`.
    """

    @hookimpl(tryfirst=True)
    def cpbenchy_worker_finish(self, ctx):
        if ctx.status not in check.SOLUTION_STATUSES:
            return
        from cpmpy.transformations.get_variables import get_variables_model

        solution = {v.name: fmt.value(v) for v in get_variables_model(ctx.model) if v.value() is not None}
        result = check.check_solution(ctx.model, solution, ctx.objective)
        result.source = "worker"
        ctx.record("check", result.to_dict())
        if not result.valid:
            problems = "; ".join(str(v) for v in result.violations[:3])
            more = f" (and {len(result.violations) - 3} more)" if len(result.violations) > 3 else ""
            ctx.status, ctx.error = "error", f"wrong solution: {problems}{more}"


class ModelSize(Observer):
    """Record the size of each model: `n_variables` (of which `n_boolvars` Boolean) and `n_constraints`."""

    def on_finish(self, ctx):
        if ctx.model is None:  # loading failed
            return
        from cpmpy.transformations.get_variables import get_variables_model

        variables = get_variables_model(ctx.model)
        ctx.record("n_variables", len(variables))
        ctx.record("n_boolvars", sum(1 for v in variables if v.is_bool()))
        ctx.record("n_constraints", len(ctx.model.constraints))


def numbered(ctx) -> tuple[dict[int, bool], int | None]:
    """The solution of an instance with variables x1, x2, ...: {number: value}, and how many variables the
    instance's header declares."""
    path = ctx.spec.instance.path
    return fmt.assignment(fmt.instance_variables(ctx.model)), fmt.header_size(path, Loader().opener(path))


def xcsp3_check(jar: str, instance: str, output: Path) -> str:
    """Check competition output with the XCSP3 checker: "OK", or what the checker says is wrong."""
    with tempfile.TemporaryDirectory() as tmp:
        if instance.endswith((".lzma", ".xz", ".gz", ".bz2")):  # the checker reads plain XML
            plain = Path(tmp) / "instance.xml"
            plain.write_text(Loader().read(instance))
            instance = str(plain)
        proc = subprocess.run(["java", "-jar", jar, instance, str(output)], capture_output=True, text=True)
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip() and not line.startswith("LOG")]
    if lines and lines[-1].startswith("OK"):
        return "OK"
    return "; ".join(lines) or proc.stderr.strip() or f"checker exited with {proc.returncode}"
