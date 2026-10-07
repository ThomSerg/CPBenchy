"""Executors start worker processes under limits and measure them.

This is the one place that knows *how* a worker process is launched. Local executors are built in;
others (in a container with fm-weck, on a remote machine) implement the same `Executor` interface and are
provided by a plugin through `cpbenchy_make_executor`.

The worker gets the time limits and gives what is left of them to the solver; the executor kills the
process `grace_s` after a limit (wall or CPU time), as a backstop. With `terminate` (as in competitions), the
run is also told to stop at its limit: the worker stops itself at it (see `cpbenchy.worker.terminate`), and
runlimit sends it SIGTERM at its CPU time limit.
"""

import contextlib
import functools
import math
import os
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from cpbenchy import hookimpl
from cpbenchy.config import UsageError
from cpbenchy.result import Measurement
from cpbenchy.scheduling import Slot, machine_layout
from cpbenchy.spec import Limits

GRACE_S = 10.0


@dataclass(frozen=True)
class WorkerJob:
    """Everything needed to start one worker process."""

    run_id: str
    cmd: list[str]
    job_file: Path
    log: Path
    limits: Limits
    cpus: tuple[int, ...] | None = None
    memory_nodes: tuple[int, ...] | None = None
    env: dict[str, str] = field(default_factory=dict)


class Executor:
    """Runs worker jobs, at most `jobs` at a time. Subclasses implement the blocking `execute`."""

    name = "executor"
    reliable = False  # do limits and measurements hold up (cgroups), or are they best effort?
    pin = False  # pin each run to its own CPUs?

    def __init__(
        self, *, jobs: int = 1, grace_s: float = GRACE_S, hyperthreading: bool = False, terminate: bool = False
    ):
        self.grace_s = grace_s
        self.hyperthreading = hyperthreading
        self.terminate = terminate
        self._pool = ThreadPoolExecutor(max_workers=jobs, thread_name_prefix=f"cpbenchy-{self.name}")

    def slots(self, jobs: int, cores: int) -> list[Slot]:
        """Where the parallel runs go: per slot, the CPUs and NUMA memory nodes to pin to (None: anywhere)."""
        if not self.pin:
            return [(None, None)] * jobs
        return machine_layout(jobs, cores, self.hyperthreading)

    def start(self, job: WorkerJob) -> "Future[Measurement]":
        return self._pool.submit(self.execute, job)

    def execute(self, job: WorkerJob) -> Measurement:
        raise NotImplementedError

    def close(self) -> None:
        """Stop: cancel what hasn't started, and wait for (or kill) what has."""
        self._pool.shutdown(wait=True, cancel_futures=True)


class SubprocessExecutor(Executor):
    """A plain child process: killed after the time limit plus grace, pinned to its CPUs (on Linux). A CPU
    time limit is the kernel's (`RLIMIT_CPU`), of the main process only.

    No memory limit, and memory is the peak resident size of the main process only, so measurements are
    not reliable. For laptops and CI without cgroups.
    """

    name = "subprocess"
    pin = hasattr(os, "sched_setaffinity")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._running: set[int] = set()

    def execute(self, job: WorkerJob) -> Measurement:
        cpus, cputime = job.cpus, job.limits.cputime_s
        hard_cpu = math.ceil(cputime + self.grace_s) if cputime is not None else None

        def limit():  # in the child, before it starts the worker
            if cpus:
                os.sched_setaffinity(0, cpus)
            if hard_cpu is not None:
                import resource

                resource.setrlimit(resource.RLIMIT_CPU, (hard_cpu, hard_cpu))  # then SIGKILL

        with open(job.log, "ab") as log:
            start = time.monotonic()
            proc = subprocess.Popen(
                job.cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, **job.env},
                start_new_session=True,  # its own process group, so a kill gets its children too
                preexec_fn=limit if cpus or hard_cpu is not None else None,
            )
            self._running.add(proc.pid)
            killed = threading.Event()

            def kill():
                killed.set()
                _killpg(proc.pid)

            timer = threading.Timer(job.limits.time_s + self.grace_s, kill)
            timer.start()
            try:
                _, status, usage = os.wait4(proc.pid, 0)
            finally:
                timer.cancel()
                self._running.discard(proc.pid)
            proc.returncode = os.waitstatus_to_exitcode(status)
        cputime_s = usage.ru_utime + usage.ru_stime
        termination = None
        if killed.is_set():
            termination = "walltime"
        elif (
            hard_cpu is not None and proc.returncode in (-signal.SIGKILL, -signal.SIGXCPU) and cputime_s >= hard_cpu - 1
        ):
            termination = "cputime"
        return Measurement(
            walltime_s=time.monotonic() - start,
            cputime_s=cputime_s,
            memory_mib=usage.ru_maxrss / 1024,  # KiB on Linux
            termination=termination,
            exitcode=proc.returncode,
            executor=self.name,
            reliable=self.reliable,
        )

    def close(self) -> None:
        for pid in list(self._running):  # only left if interrupted
            _killpg(pid)
        super().close()


class RunlimitExecutor(Executor):
    """BenchExec's runexec, through runlimit: cgroups enforce the memory limit and measure CPU time and
    memory of the whole process tree; each run is pinned to its own cores and NUMA memory."""

    name = "runlimit"
    reliable = True
    pin = True

    def __init__(self, *, container: bool = False, writable_dirs: tuple[Path, ...] = (), **kwargs):
        super().__init__(**kwargs)
        self.container = container
        self.writable_dirs = writable_dirs
        self._running: set = set()

    def execute(self, job: WorkerJob) -> Measurement:
        from cpbenchy import runlimit

        handle = runlimit.start(
            job.cmd,
            output_file=job.log,
            walltime=job.limits.time_s + self.grace_s,
            cputime=job.limits.cputime_s + self.grace_s if job.limits.cputime_s is not None else None,
            soft_cputime=job.limits.cputime_s if self.terminate else None,
            memlimit_mib=job.limits.mem_mib,
            cores=job.cpus,
            memory_nodes=job.memory_nodes,
            container=self.container,
            writable_dirs=[job.log.parent, *self.writable_dirs],
            env=job.env or None,
        )
        self._running.add(handle)
        try:
            result = handle.result()
        finally:
            self._running.discard(handle)
        return Measurement(
            walltime_s=result["walltime"],
            cputime_s=result["cputime"],
            memory_mib=result["memory"] / 2**20 if result["memory"] is not None else None,
            termination=result["terminationreason"],
            exitcode=result["exitcode"]["code"],
            executor=self.name,
            reliable=self.reliable,
        )

    def close(self) -> None:
        for handle in list(self._running):  # only left if interrupted
            handle.terminate()
        super().close()


@functools.cache
def runexec_problem() -> str | None:
    """Why runexec can't be used here, or None if it can (tries a tiny run once per process)."""
    try:
        from cpbenchy import runlimit

        with tempfile.TemporaryDirectory() as tmp:
            result = runlimit.run(["true"], output_file=Path(tmp) / "probe.log", walltime=30)
        if result["exitcode"]["code"] != 0:
            return f"a test run failed: {result}"
    except Exception as e:
        return f"{type(e).__name__}: {str(e).strip().splitlines()[0] if str(e).strip() else ''}"
    return None


def _killpg(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)


class InlineExecutor(Executor):
    """Runs the worker in this process, one run at a time, without limits: for debugging (breakpoints work)
    and fast tests."""

    name = "inline"

    def start(self, job: WorkerJob) -> "Future[Measurement]":
        future: Future[Measurement] = Future()
        future.set_result(self.execute(job))
        return future

    def execute(self, job: WorkerJob) -> Measurement:
        from cpbenchy.worker.runtime import main

        start, cpu_start = time.monotonic(), time.process_time()
        exitcode = main([str(job.job_file)])
        return Measurement(
            walltime_s=time.monotonic() - start,
            cputime_s=time.process_time() - cpu_start,
            memory_mib=None,
            termination=None,
            exitcode=exitcode,
            executor=self.name,
            reliable=False,
        )


# --- plugin: choosing the executor ---

EXECUTORS: dict[str, type[Executor]] = {
    "runlimit": RunlimitExecutor,
    "subprocess": SubprocessExecutor,
    "inline": InlineExecutor,
}


@hookimpl
def cpbenchy_addoption(parser):
    group = parser.getgroup("execution")
    group.addoption(
        "--executor",
        default="auto",
        metavar="NAME",
        help=f"how to run workers: auto (runlimit if it works here), {', '.join(EXECUTORS)} (default: %(default)s)",
    )
    group.addoption(
        "--grace",
        dest="grace_s",
        type=float,
        default=GRACE_S,
        metavar="SECONDS",
        help="seconds after a time limit before a run is killed (default: %(default)s)",
    )
    group.addoption(
        "--terminate",
        action="store_true",
        help="stop each run at its time limit, as competitions do: it reports the best solution it found so "
        "far, and is killed --grace seconds later if it hasn't stopped by then",
    )
    group.addoption("--hyperthreading", action="store_true", help="let runs use hyperthread siblings")
    group.addoption("--container", action="store_true", help="runlimit: no network, read-only file system")


@hookimpl(trylast=True)
def cpbenchy_make_executor(config):
    name = config.getoption("executor")
    if name == "auto":
        name = "runlimit" if runexec_problem() is None else "subprocess"
    if name not in EXECUTORS:
        raise UsageError(f"unknown executor {name!r}; built in: auto, {', '.join(EXECUTORS)}")
    if name == "runlimit" and runexec_problem():
        raise UsageError(f"runexec does not work here ({runexec_problem()}); see `cpbenchy doctor`")
    kwargs = {"jobs": config.getoption("jobs"), "grace_s": config.getoption("grace_s")}
    kwargs["terminate"] = config.getoption("terminate")
    kwargs["hyperthreading"] = config.getoption("hyperthreading")
    if name == "runlimit":
        kwargs["container"] = config.getoption("container")
    return EXECUTORS[name](**kwargs)
