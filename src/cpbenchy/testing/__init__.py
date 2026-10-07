"""Testing plugins with pytest. Enable it in your `conftest.py`:

    pytest_plugins = ["cpbenchy.testing"]

and use the `benchtester` fixture, which works in a temporary directory:

    def test_my_plugin(benchtester):
        benchtester.makeconf('''
            import cpbenchy

            @cpbenchy.hookimpl
            def cpbenchy_worker_finish(ctx):
                ctx.record("n_constraints", len(ctx.model.constraints))
        ''')
        results = benchtester.run()  # the bundled tiny instances, with ortools
        assert all(r.extra["n_constraints"] > 0 for r in results)
"""

import io
import textwrap
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import cpbenchy
from cpbenchy.config import CONF_FILE
from cpbenchy.result import Results

DATA = Path(__file__).parent / "data"
"""Tiny OPB instances: knapsack (optimal -9), its xz-compressed copy, sat, and unsat."""


@dataclass
class CliOutcome:
    ret: int
    stdout: str
    stderr: str
    results: Results


class Benchtester:
    def __init__(self, path: Path):
        self.path = path
        self.out = path / "out"

    def makeconf(self, source: str) -> Path:
        """Write the local plugin file `cpbenchy_conf.py`."""
        return self.makefile(CONF_FILE, source)

    def makefile(self, name: str, source: str) -> Path:
        path = self.path / name
        path.write_text(textwrap.dedent(source))
        return path

    def run(self, *sources: Any, **kwargs: Any) -> Results:
        """`cpbenchy.run`, by default on the tiny instances with ortools, 10 s, storing in `self.out`."""
        kwargs.setdefault("solvers", ["ortools"])
        kwargs.setdefault("time_limit", 10)
        kwargs.setdefault("out", self.out)
        return cpbenchy.run(*(sources or [DATA]), **kwargs)

    def run_cli(self, *args: str) -> CliOutcome:
        """`cpbenchy ARGS...` in-process, with output captured."""
        from cpbenchy.cli import main

        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            ret = main(list(args))
        return CliOutcome(ret, stdout.getvalue(), stderr.getvalue(), Results.load(self.out))


@pytest.fixture
def benchtester(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Benchtester:
    monkeypatch.chdir(tmp_path)
    return Benchtester(tmp_path)
