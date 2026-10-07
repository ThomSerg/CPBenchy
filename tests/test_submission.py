"""`cpbenchy solve` (one instance, competition output on stdout) and building submissions from it."""

import json
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from cpbenchy import formats
from cpbenchy.check import check_solution
from cpbenchy.config import UsageError
from cpbenchy.submission import Submission, build, requirements
from cpbenchy.testing import DATA

EXAMPLE_DATA = Path(__file__).parents[1] / "examples" / "data"
KNAPSACK = DATA / "knapsack.opb"

# keeps searching after its first solution, as on a hard instance
SLOW_SOLVER = """
import time
import cpbenchy

class SlowSolver:
    @cpbenchy.hookimpl(tryfirst=True)
    def cpbenchy_worker_solve(self, ctx):
        ctx.solver.solve()
        ctx.report_solution(ctx.model.objective_.value())
        time.sleep(60)
        return True
"""


def solve(*args, cwd=None, env=None):
    cmd = [sys.executable, "-m", "cpbenchy", "solve", *map(str, args)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env, timeout=120)


# --- solve ---


def test_solve_prints_competition_output():
    proc = solve(KNAPSACK, "-s", "ortools", "--rules", "pb26", "--seed", 2**32 - 1)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert "o -9" in lines and lines[-3:-1] == ["s OPTIMUM FOUND", "v x1 x2 -x3 x4"]
    assert lines[-1].startswith("c cpbenchy: optimal, objective -9")
    assert all(line[:2] in ("c ", "o ", "s ", "v ") for line in lines)  # nothing else on stdout


def test_solve_stops_on_sigterm_with_the_best_solution(tmp_path):
    (tmp_path / "slow.py").write_text(SLOW_SOLVER)
    cmd = [sys.executable, "-m", "cpbenchy", "solve", str(KNAPSACK), "-s", "ortools", "--rules", "pb26"]
    proc = subprocess.Popen([*cmd, "-p", "slow.py:SlowSolver"], cwd=tmp_path, stdout=subprocess.PIPE, text=True)
    time.sleep(5)  # past loading CPMpy and solving
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=30)
    lines = out.splitlines()
    assert proc.returncode == 0
    assert lines[-3:-1] == ["s SATISFIABLE", "v x1 x2 -x3 x4"]
    assert "stopped (signal)" in lines[-1]


def test_solve_needs_one_instance_and_solver():
    proc = solve(DATA, "-s", "ortools", "-t", "5")
    assert proc.returncode == 2 and "exactly one instance" in proc.stderr


# --- submissions ---

SUBMISSION = """
name = "test-{solver}"
description = "a test submission with {solver}"
authors = ["Tester"]
solver = "ortools"
params = {log_search_progress = false}
plugins = ["tag.py:Tag"]
include = ["doc"]

[[tracks]]
name = "OPT-LIN"
rules = "pb26"
test = ["knapsack.opb"]

[[tracks]]
name = "ANYTIME"
rules = "my-rules.toml"
test = ["tiny.wcnf"]
"""

MY_RULES = """
name = "my-maxsat"
[settings]
time-limit = 60
terminate = true
grace = 1
plugins = ["cpbenchy.observers:MaxSATOutput"]
[interface]
arguments = ["BENCHNAME", "TIMELIMIT"]
"""

TAG = """
import cpbenchy

class Tag(cpbenchy.Observer):
    def on_finish(self, ctx):
        print("c tagged", flush=True)
"""


@pytest.fixture
def spec(tmp_path):
    (tmp_path / "submission.toml").write_text(SUBMISSION)
    (tmp_path / "my-rules.toml").write_text(MY_RULES)
    (tmp_path / "tag.py").write_text(TAG)
    (tmp_path / "doc").mkdir()
    (tmp_path / "doc" / "description.pdf").write_text("%PDF")
    (tmp_path / "knapsack.opb").write_bytes(KNAPSACK.read_bytes())
    (tmp_path / "tiny.wcnf").write_bytes((EXAMPLE_DATA / "tiny.wcnf").read_bytes())
    return tmp_path / "submission.toml"


def test_build_test_and_run_like_a_competition(spec, tmp_path, benchtester):
    outcome = benchtester.run_cli(
        "submission", "build", str(spec), "-o", str(tmp_path / "sub"), "--test", "--archive", "zip"
    )
    assert outcome.ret == 0, outcome.stdout + outcome.stderr
    assert "ok   OPT-LIN" in outcome.stdout and "ok   ANYTIME" in outcome.stdout
    sub = tmp_path / "sub"
    for path in ["bin/run_OPT-LIN", "bin/run_ANYTIME", "install.sh", "requirements.txt", "README.md", "build.json",
                 "code/cpbenchy/solve.py", "code/tag.py", "rules/pb26.toml", "rules/my-maxsat.toml",
                 "doc/description.pdf"]:  # fmt: skip
        assert (sub / path).exists(), path
    assert (
        "DIR/bin/run_OPT-LIN BENCHNAME RANDOMSEED TIMELIMIT MEMLIMIT NBCORE TMPDIR" in (sub / "README.md").read_text()
    )
    assert "test-ortools" in (sub / "README.md").read_text()
    with zipfile.ZipFile(tmp_path / "sub.zip") as z:
        assert "sub/bin/run_OPT-LIN" in z.namelist()

    # as the competition calls it: from elsewhere, with its placeholders, stopped by SIGTERM
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {**os.environ, "CPBENCHY_PYTHON": sys.executable}
    args = [str(sub / "bin/run_OPT-LIN"), str(KNAPSACK), "4294967295", "1800", "4096", "1", str(tmp_path)]
    proc = subprocess.run(args, cwd=elsewhere, capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "c tagged" in proc.stdout  # the bundled plugin
    _, objective, values = formats.read_competition_output(proc.stdout)
    from cpmpy.tools.io import load

    assert check_solution(load(str(KNAPSACK)), formats.read_literals(" ".join(values)), objective).valid
    usage = subprocess.run([str(sub / "bin/run_ANYTIME"), "x"], capture_output=True, text=True, env=env)
    assert usage.returncode == 2 and "BENCHNAME TIMELIMIT" in usage.stderr


def test_a_file_builds_for_other_solvers(spec, tmp_path):
    sub = Submission.load(spec, solver="exact")
    assert sub.name == "test-exact" and all(t.solver == "exact" for t in sub.tracks)
    out = build(sub, tmp_path / "exact")
    assert "-s exact" in (out / "bin/run_OPT-LIN").read_text()
    assert any(p.lower().startswith("exact==") for p in (out / "requirements.txt").read_text().split())


def test_requirements_pin_what_is_installed(spec):
    pins, warnings = requirements(Submission.load(spec), vendored=["cpbenchy"])
    names = {p.split("==")[0].lower() for p in pins}
    assert {"cpmpy", "ortools", "numpy", "pluggy", "rich"} <= names  # with dependencies, like a lock file
    assert all("==" in p for p in pins if not p.startswith("tomli")) and not warnings
    assert any(p.startswith("tomli") and 'python_version < "3.11"' in p for p in pins)  # for Python 3.10
    assert "benchexec" not in names and "cpbenchy" not in names


def test_rebuilding_needs_force_and_only_replaces_builds(spec, tmp_path):
    sub = Submission.load(spec)
    out = build(sub, tmp_path / "sub")
    with pytest.raises(UsageError, match="--force"):
        build(sub, out)
    assert build(sub, out, force=True) == out
    other = tmp_path / "mine"
    other.mkdir()
    (other / "keep.txt").write_text("x")
    with pytest.raises(UsageError, match="not a submission"):
        build(sub, other, force=True)
    assert (other / "keep.txt").exists()


def test_a_track_needs_to_know_how_it_is_called(spec, tmp_path):
    (tmp_path / "my-rules.toml").write_text(MY_RULES.split("[interface]")[0])
    with pytest.raises(UsageError, match="how the competition calls a solver"):
        Submission.load(spec)


def test_init_writes_a_file_that_builds(benchtester, tmp_path):
    path = tmp_path / "new.toml"
    assert benchtester.run_cli("submission", "init", str(path), "--rules", "xcsp3-2025", "-s", "ortools").ret == 0
    sub = Submission.load(path)
    assert [t.rules.name for t in sub.tracks] == ["xcsp3-2025"]
    info = json.loads((build(sub, tmp_path / "out") / "build.json").read_text())
    assert info["tracks"]["xcsp3-2025"]["arguments"][0] == "BENCHNAME"
