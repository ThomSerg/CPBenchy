"""Placing parallel runs on the machine: which CPUs and NUMA memory nodes each of the `jobs` slots gets.

BenchExec computes the layout (`_get_cpu_cores_per_run0`, private but stable for many releases; benchexec
is pinned below 4): whole physical cores unless hyperthreading is allowed, so the idle hyperthread
siblings don't disturb the measurements; each run within one NUMA node / CPU package where it fits; and
spread evenly over the nodes. A run's memory is bound to the nodes of its CPUs.
"""

import copy
import os
from pathlib import Path

from cpbenchy.config import UsageError

SYS_CPU = Path("/sys/devices/system/cpu")
SYS_NODE = Path("/sys/devices/system/node")

Slot = tuple[tuple[int, ...] | None, tuple[int, ...] | None]  # (cpus, memory nodes); None: anywhere


def parse_cpu_list(text: str) -> list[int]:
    """'0-3,8,10-11' -> [0, 1, 2, 3, 8, 10, 11]"""
    cpus = []
    for part in text.strip().split(","):
        if part:
            lo, _, hi = part.partition("-")
            cpus.extend(range(int(lo), int(hi or lo) + 1))
    return cpus


def topology() -> tuple[dict[int, list[int]], dict[int, int]]:
    """For the CPUs this process may use: CPU -> CPUs on the same physical core, and CPU -> NUMA node."""
    allowed = sorted(os.sched_getaffinity(0))
    node_of = {}
    for node_dir in SYS_NODE.glob("node[0-9]*"):
        for cpu in parse_cpu_list((node_dir / "cpulist").read_text()):
            node_of[cpu] = int(node_dir.name[4:])
    siblings = {}
    for cpu in allowed:
        path = SYS_CPU / f"cpu{cpu}" / "topology" / "thread_siblings_list"
        siblings[cpu] = [s for s in (parse_cpu_list(path.read_text()) if path.exists() else [cpu]) if s in allowed]
    return siblings, {cpu: node_of.get(cpu, 0) for cpu in allowed}


def layout(
    jobs: int, cores: int, siblings: dict[int, list[int]], node_of: dict[int, int], hyperthreading: bool = False
) -> list[Slot]:
    cores_of_unit: dict[int, list[int]] = {}
    for cpu in sorted(siblings):
        cores_of_unit.setdefault(node_of[cpu], []).append(cpu)
    try:
        # it may modify its arguments, and exits instead of raising when a layout is impossible
        from benchexec import resources as benchexec_resources  # only to schedule runs, not to solve one

        slots = benchexec_resources._get_cpu_cores_per_run0(
            cores, jobs, hyperthreading, sorted(siblings), copy.deepcopy(cores_of_unit), copy.deepcopy(siblings)
        )
    except SystemExit:
        slots = None
    if not slots:
        physical = len({tuple(s) for s in siblings.values()})
        raise UsageError(
            f"cannot place {jobs} parallel runs of {cores} cores on {len(siblings)} CPUs ({physical} physical cores"
            f"{'' if hyperthreading else ', without using hyperthread siblings'}): lower --jobs or --cores"
        )
    return [(tuple(sorted(s)), tuple(sorted({node_of[c] for c in s}))) for s in slots]


def machine_layout(jobs: int, cores: int, hyperthreading: bool = False) -> list[Slot]:
    return layout(jobs, cores, *topology(), hyperthreading=hyperthreading)


def total_memory_mib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None
