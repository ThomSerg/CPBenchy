"""Running from asyncio: `cpbenchy.run_async`, `Experiment.run_async` and `iter_results_async`."""

import asyncio
import contextlib
import subprocess
import time

import cpbenchy
from cpbenchy.testing import DATA

KNAPSACK, SAT, UNSAT = DATA / "knapsack.opb", DATA / "sat.opb", DATA / "unsat.opb"

SLEEPING_SOLVER = """
import time
import cpbenchy

@cpbenchy.hookimpl(tryfirst=True)
def cpbenchy_worker_solve(ctx):
    time.sleep(60)
    return True
"""


def workers_of(out) -> list[str]:
    """Worker processes still running for runs of the output directory `out`."""
    found = subprocess.run(["pgrep", "-f", f"cpbenchy.worker {out}"], capture_output=True, text=True)
    return found.stdout.split()


def test_run_async_returns_what_run_does(benchtester):
    finished, solutions = [], []
    results = asyncio.run(
        cpbenchy.run_async(
            KNAPSACK,
            UNSAT,
            solvers=["ortools"],
            time_limit=10,
            out=benchtester.out,
            quiet=True,
            on_result=lambda r: finished.append(r.instance),
            on_solution=lambda run, t, objective: solutions.append(objective),
        )
    )
    assert sorted((r.instance, r.status) for r in results) == [("knapsack", "optimal"), ("unsat", "unsat")]
    assert sorted(finished) == ["knapsack", "unsat"] and solutions[-1] == -9
    assert cpbenchy.load(benchtester.out) == results  # stored, as with run()


def test_the_event_loop_stays_free_while_runs_go_on(benchtester):
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    async def main():
        tick = asyncio.ensure_future(ticker())
        exp = cpbenchy.Experiment(benchtester.out, time_limit=10, quiet=True)
        results = await exp.add(KNAPSACK, SAT, solver="ortools").run_async()
        tick.cancel()
        return results

    started = time.monotonic()
    assert len(asyncio.run(main())) == 2
    assert ticks > 0.5 * (time.monotonic() - started) / 0.05  # the ticker ran most of the time


def test_runs_go_on_while_the_loop_body_awaits(benchtester):
    finished_at = {}

    async def main():
        exp = cpbenchy.Experiment(benchtester.out, time_limit=10, jobs=1, quiet=True)
        exp.add(KNAPSACK, SAT, UNSAT, solver="ortools")
        seen = []
        async for result in exp.iter_results_async(
            on_result=lambda r: finished_at.setdefault(r.instance, time.monotonic())
        ):
            seen.append(result.instance)
            if len(seen) == 1:
                woke = time.monotonic() + 6
                await asyncio.sleep(6)  # a slow body; with jobs=1, the other runs must still start meanwhile
        return seen, woke

    seen, woke = asyncio.run(main())
    assert len(seen) == 3
    assert sorted(finished_at.values())[1] < woke  # the second run finished while the body was waiting


def test_cancelling_stops_the_runs_and_stores_nothing(benchtester):
    benchtester.makeconf(SLEEPING_SOLVER)

    async def main():
        exp = cpbenchy.Experiment(benchtester.out, time_limit=60, jobs=2, executor="subprocess", quiet=True)
        exp.add(KNAPSACK, SAT, solver="ortools")
        task = asyncio.ensure_future(exp.run_async())
        await asyncio.sleep(5)  # the runs are going
        assert len(workers_of(benchtester.out)) >= 2
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert cpbenchy.load(benchtester.out) == []
    assert workers_of(benchtester.out) == []


def test_breaking_out_stops_the_rest(benchtester):
    async def main():
        exp = cpbenchy.Experiment(benchtester.out, time_limit=10, jobs=1, quiet=True)
        exp.add(KNAPSACK, SAT, UNSAT, solver="ortools")
        async with contextlib.aclosing(exp.iter_results_async()) as results:
            async for _ in results:
                break

    asyncio.run(main())
    assert 1 <= len(cpbenchy.load(benchtester.out)) < 3  # what finished is stored; the rest didn't run
    assert workers_of(benchtester.out) == []
