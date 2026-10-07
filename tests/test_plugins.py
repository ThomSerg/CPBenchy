import cpbenchy
from cpbenchy.testing import DATA


class CountConstraints:
    """A worker plugin passed as an object: the worker re-creates it from its class."""

    @cpbenchy.hookimpl
    def cpbenchy_worker_finish(self, ctx):
        ctx.record("n_constraints", len(ctx.model.constraints))


def test_conf_file_hooks_run_in_worker_and_parent(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        seen = []

        @cpbenchy.hookimpl
        def cpbenchy_worker_finish(ctx):
            ctx.record("worker_saw", ctx.status)

        @cpbenchy.hookimpl
        def cpbenchy_run_event(run, event):
            seen.append(event.kind)

        @cpbenchy.hookimpl
        def cpbenchy_run_finished(run, result):
            result.extra["events"] = list(seen)
            seen.clear()
        """
    )
    results = benchtester.run()
    assert {r.extra["worker_saw"] for r in results} == {"optimal", "feasible", "unsat"}
    assert all(r.extra["events"][-1] == "result" for r in results)
    assert all("loaded" in r.extra["events"] for r in results)


def test_plugin_object_from_api_is_shipped_to_worker(benchtester):
    results = benchtester.run(plugins=[CountConstraints()])
    assert all(r.extra["n_constraints"] >= 1 for r in results)


def test_worker_plugin_reads_its_own_option(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        @cpbenchy.hookimpl
        def cpbenchy_addoption(parser):
            parser.addoption("--tag")

        @cpbenchy.hookimpl
        def cpbenchy_worker_finish(ctx):
            ctx.record("tag", ctx.options["tag"])
        """
    )
    results = benchtester.run(args=["--tag", "hello"])
    assert {r.extra["tag"] for r in results} == {"hello"}


def test_replacing_a_worker_step_and_hard_timeout(benchtester):
    benchtester.makeconf(
        """
        import time
        import cpbenchy

        @cpbenchy.hookimpl
        def cpbenchy_worker_solve(ctx):
            time.sleep(60)  # ignores the time limit, so the executor has to kill it
            return True
        """
    )
    results = benchtester.run(DATA / "knapsack.opb", time_limit=1, args=["--grace", "0.5"])
    assert results[0].status == "timeout"
    assert results[0].termination == "walltime"
    assert results[0].walltime_s < 10


def test_disabling_a_plugin(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        @cpbenchy.hookimpl
        def cpbenchy_worker_finish(ctx):
            ctx.record("conf", True)
        """
    )
    results = benchtester.run(args=["-p", "no:cpbenchy_conf.py"])
    assert all("conf" not in r.extra for r in results)


def test_solution_events_reach_the_parent(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        objectives = []

        @cpbenchy.hookimpl
        def cpbenchy_worker_solve(ctx):
            for objective in (3, 2, 1):
                ctx.report_solution(objective)
            return None  # and let the built-in solve run too

        @cpbenchy.hookimpl
        def cpbenchy_run_event(run, event):
            if event.kind == "solution":
                run.extra.setdefault("objectives", []).append(event.data["objective"])
        """
    )
    [result] = benchtester.run(DATA / "knapsack.opb")
    assert result.extra["objectives"][:3] == [3, 2, 1]  # then the solver's own
    assert result.objective == -9


def test_wrapper_hook_from_the_docs(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        @cpbenchy.hookimpl(wrapper=True)
        def cpbenchy_worker_solve(ctx):
            ctx.log("about to solve")
            result = yield
            ctx.record("solver_wall_s", ctx.solver.status().runtime)
            return result
        """
    )
    [result] = benchtester.run(DATA / "knapsack.opb", args=["-p", "no:terminal"])
    assert result.status == "optimal" and result.extra["solver_wall_s"] >= 0
