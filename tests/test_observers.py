import pytest

import cpbenchy
from cpbenchy.config import UsageError, make_config
from cpbenchy.testing import DATA

KNAPSACK = DATA / "knapsack.opb"


class Tag(cpbenchy.Observer):
    """Defined at module level, so the worker can import it from this test module."""

    def __init__(self, value):
        self.value = value

    def on_finish(self, ctx):
        ctx.record("worker_tag", self.value)

    def on_result(self, run, result):
        result.extra["parent_tag"] = self.value


class OnlyInParent(cpbenchy.Observer):
    def on_result(self, run, result):
        result.extra["seen"] = True


def test_observer_in_conf_file_runs_in_worker_and_parent(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        class Count(cpbenchy.Observer):
            def __init__(self):
                self.finished = 0

            def on_finish(self, ctx):
                ctx.record("n_constraints", len(ctx.model.constraints))

            def on_result(self, run, result):
                self.finished += 1
                result.extra["finished_so_far"] = self.finished

            def on_session_end(self, session):
                print(f"observed {self.finished} runs")
        """
    )
    outcome = benchtester.run_cli("run", str(KNAPSACK), str(DATA / "sat.opb"), "-s", "ortools", "-t", "10", "-o", "out")
    assert outcome.ret == 0, outcome.stderr
    assert sorted(r.extra["finished_so_far"] for r in outcome.results) == [1, 2]
    assert all(r.extra["n_constraints"] >= 1 for r in outcome.results)
    assert "observed 2 runs" in outcome.stdout


def test_observer_with_arguments_from_the_command_line(benchtester):
    path = benchtester.makefile(
        "tags.py",
        """
        import cpbenchy

        class Tag(cpbenchy.Observer):
            def __init__(self, value, times=1):
                self.value = value * times

            def on_finish(self, ctx):
                ctx.record("tag", self.value)
        """,
    )
    outcome = benchtester.run_cli(
        "run", str(KNAPSACK), "-s", "ortools", "-t", "10", "-o", "out", "-p", f"{path}:Tag('ab', times=2)"
    )
    assert outcome.ret == 0, outcome.stderr
    assert outcome.results[0].extra["tag"] == "abab"


def test_observer_object_from_the_api_is_recreated_in_the_worker(benchtester):
    [result] = benchtester.run(KNAPSACK, plugins=[Tag("hello")], quiet=True)
    assert result.extra["worker_tag"] == result.extra["parent_tag"] == "hello"


def test_parent_only_observer_is_not_sent_to_the_worker():
    config = make_config(plugins=[OnlyInParent(), Tag("x")])
    assert [ref.rsplit(":", 1)[1] for ref in config.worker_plugins()] == ["Tag('x')"]


def test_formats_limit_what_an_observer_sees(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        class WcnfOnly(cpbenchy.Observer):
            formats = ("wcnf",)

            def on_finish(self, ctx):
                ctx.record("wcnf", True)

            def on_result(self, run, result):
                result.extra["wcnf_parent"] = True
        """
    )
    [result] = benchtester.run(KNAPSACK, quiet=True)
    assert "wcnf" not in result.extra and "wcnf_parent" not in result.extra


def test_observer_can_replace_loading_and_add_solver_args(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        class Replace(cpbenchy.Observer):
            def on_load(self, ctx):
                import cpmpy as cp

                x = cp.intvar(0, 10, name="x")
                return cp.Model(x >= 3, minimize=x)

            def solver_args(self, ctx):
                return {"num_search_workers": 2}

            def on_finish(self, ctx):
                ctx.record("args", ctx.solver_args.get("num_search_workers"))
        """
    )
    [result] = benchtester.run(KNAPSACK, quiet=True)
    assert result.objective == 3
    assert result.extra["args"] == 2


def test_disabling_an_observer_by_class_name(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        class Noisy(cpbenchy.Observer):
            def on_result(self, run, result):
                result.extra["noisy"] = True
        """
    )
    [result] = benchtester.run(KNAPSACK, args=["-p", "no:Noisy"], quiet=True)
    assert "noisy" not in result.extra


def test_arguments_must_be_literals():
    with pytest.raises(UsageError, match="Python literals"):
        make_config(plugins=[Tag(object())]).worker_plugins()
