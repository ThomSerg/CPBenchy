import pytest

from cpbenchy.scheduling import layout, parse_cpu_list
from cpbenchy.testing import DATA

# A 2-socket machine, 2 physical cores per socket, 2 hyperthreads per core: cpu i and i+4 are siblings.
SIBLINGS = {c: [c % 4, c % 4 + 4] for c in range(8)}
NODE_OF = {c: (c % 4) // 2 for c in range(8)}

RECORD_AFFINITY = """
import os
import cpbenchy

@cpbenchy.hookimpl
def cpbenchy_worker_finish(ctx):
    ctx.record("affinity", sorted(os.sched_getaffinity(0)))
"""


def test_parse_cpu_list():
    assert parse_cpu_list("0-3,8,10-11\n") == [0, 1, 2, 3, 8, 10, 11]


def test_layout_uses_whole_cores_and_keeps_runs_on_one_node():
    slots = layout(2, 2, SIBLINGS, NODE_OF)
    assert slots == [((0, 1), (0,)), ((2, 3), (1,))]


def test_layout_with_hyperthreading_packs_siblings():
    slots = layout(4, 2, SIBLINGS, NODE_OF, hyperthreading=True)
    assert len(slots) == 4
    assert all(len(cpus) == 2 for cpus, _ in slots)


def test_impossible_layout_is_a_usage_error():
    from cpbenchy.config import UsageError

    with pytest.raises(UsageError, match="lower --jobs"):
        layout(3, 2, SIBLINGS, NODE_OF)


def test_subprocess_executor_pins_runs(benchtester):
    benchtester.makeconf(RECORD_AFFINITY)
    results = benchtester.run(DATA, executor="subprocess", jobs=2)
    assert all(r.extra["affinity"] == r.cpus for r in results)
    assert len({tuple(r.cpus) for r in results}) == 2


@pytest.mark.runexec
def test_runlimit_executor(benchtester):
    benchtester.makeconf(RECORD_AFFINITY)
    results = benchtester.run(DATA, executor="runlimit", mem_limit_mib=2048, jobs=2)
    assert {r.executor for r in results} == {"runlimit"} and all(r.reliable for r in results)
    assert sorted(r.status for r in results) == ["feasible", "optimal", "optimal", "unsat"]
    assert all(r.extra["affinity"] == r.cpus for r in results)
    assert all(r.memory_mib > 10 for r in results)


@pytest.mark.runexec
def test_runlimit_memout(benchtester):
    benchtester.makeconf(
        """
        import cpbenchy

        @cpbenchy.hookimpl
        def cpbenchy_worker_solve(ctx):
            hog = [bytearray(2**20) for _ in range(4096)]  # 4 GiB
            return True
        """
    )
    [result] = benchtester.run(DATA / "knapsack.opb", executor="runlimit", mem_limit_mib=512)
    assert result.status == "memout"


@pytest.mark.runexec
def test_runlimit_timeout(benchtester):
    benchtester.makeconf(
        """
        import time
        import cpbenchy

        @cpbenchy.hookimpl
        def cpbenchy_worker_solve(ctx):
            time.sleep(60)
            return True
        """
    )
    [result] = benchtester.run(DATA / "knapsack.opb", executor="runlimit", time_limit=1, args=["--grace", "0.5"])
    assert result.status == "timeout"
    assert result.walltime_s < 10
