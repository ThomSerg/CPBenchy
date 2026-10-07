"""A session: collect the runs, execute them, store the results. Also the core command-line options.

The loop runs on the main thread. Executors run the worker processes in the background; meanwhile the loop
reads each active run's event file and calls the hooks, so plugins never see two hooks at once.
"""

import asyncio
import contextlib
import json
import os
import socket
import sys
from collections import deque
from collections.abc import AsyncIterator, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cpbenchy
from cpbenchy import hookimpl, refs
from cpbenchy.config import Config, UsageError
from cpbenchy.executors import Executor, WorkerJob
from cpbenchy.loader import Loader
from cpbenchy.result import Measurement, Results, RunResult
from cpbenchy.scheduling import total_memory_mib
from cpbenchy.spec import Instance, Limits, RunSpec
from cpbenchy.store import Store
from cpbenchy.worker import THREAD_ENV

DEFAULT_OUT = "cpbenchy-results"
POLL_S = 0.2


@hookimpl
def cpbenchy_addoption(parser):
    group = parser.getgroup("run", "what to run")
    group.addoption(
        "sources", nargs="*", default=[], metavar="SOURCE", help="instance files, directories or glob patterns"
    )
    group.addoption(
        "-s", "--solver", dest="solvers", action="append", default=[], metavar="SOLVER", help="solver (repeatable)"
    )
    group.addoption("-t", "--time-limit", type=float, metavar="SECONDS", help="time limit per run (wall clock)")
    group.addoption(
        "--cpu-time-limit",
        dest="cputime_limit_s",
        type=float,
        metavar="SECONDS",
        help="CPU time limit per run, as competitions limit sequential solvers (default: none)",
    )
    group.addoption("-m", "--mem-limit", dest="mem_limit_mib", type=int, metavar="MIB", help="memory limit per run")
    group.addoption(
        "--scale",
        type=float,
        default=1.0,
        metavar="FACTOR",
        help="multiply the time limits (not the memory limit) by this, e.g. 0.1 to try rules quickly "
        "(default: %(default)s)",
    )
    group.addoption(
        "-P",
        "--param",
        dest="params",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="solver parameter, VALUE as JSON if it parses (repeatable)",
    )
    group.addoption(
        "--seed", dest="seeds", type=int, action="append", default=[], metavar="N", help="seed (repeatable)"
    )
    group.addoption("--cores", type=int, default=1, metavar="N", help="cores per run (default: %(default)s)")
    group.addoption(
        "--loader",
        metavar="REF",
        help="load instances with this Loader class, e.g. 'myloaders.py:MyLoader(k=1)' (default: CPMpy's loaders)",
    )

    group = parser.getgroup("execution")
    group.addoption("-j", "--jobs", type=int, default=1, metavar="N", help="runs in parallel (default: %(default)s)")
    group.addoption("-o", "--out", default=DEFAULT_OUT, metavar="DIR", help="output directory (default: %(default)s)")
    group.addoption("--rerun", action="store_true", help="also run what is already in the output directory")


def parse_params(items: list[str] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(items, dict):
        return items
    params = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep:
            raise UsageError(f"--param expects KEY=VALUE, got {item!r}")
        try:
            params[key] = json.loads(value)
        except json.JSONDecodeError:
            params[key] = value
    return params


@dataclass(frozen=True)
class Event:
    t: float  # seconds since the worker started
    kind: str
    data: dict[str, Any]


@dataclass
class Run:
    """One run in progress. Parent-side plugins may add result fields to `extra`."""

    spec: RunSpec
    job_file: Path
    log_file: Path
    events_file: Path
    cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cpus: tuple[int, ...] | None = None
    memory_nodes: tuple[int, ...] | None = None
    started: str | None = None
    report: dict[str, Any] | None = None  # the worker's final report, once it arrived
    extra: dict[str, Any] = field(default_factory=dict)
    _offset: int = 0

    @property
    def run_id(self) -> str:
        return self.spec.run_id

    def artifact(self, name: str) -> Path:
        """A file of this run's own, next to its log; what the worker wrote as `ctx.artifact(name)`."""
        return self.log_file.parent / f"{self.run_id}.{name}"

    def read_events(self) -> list[Event]:
        """Events written since the last call (complete lines only)."""
        if not self.events_file.exists():
            return []
        with open(self.events_file, "rb") as f:
            f.seek(self._offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1
        self._offset += end
        events = [Event(**json.loads(line)) for line in chunk[:end].splitlines() if line.strip()]
        for event in events:
            if event.kind == "result":
                self.report = event.data
        return events


def collect_instances(config: Config, sources: Iterable[Any]) -> list[Instance]:
    """The instances of all sources, through `cpbenchy_collect`."""
    instances = []
    for source in sources:
        found = config.hook.cpbenchy_collect(source=source, config=config)
        if found is None:
            raise UsageError(f"don't know how to collect instances from {source!r}")
        instances.extend(found)
    return instances


def make_limits(config: Config, time_s: float, mem_mib: int | None = None, cputime_s: float | None = None) -> Limits:
    """Limits, with the time limits scaled by `--scale`."""
    scale = config.getoption("scale", 1.0) or 1.0
    return Limits(time_s * scale, mem_mib, cputime_s * scale if cputime_s is not None else None)


def grid(
    instances: Iterable[Instance],
    solvers: Iterable[str],
    limits: Limits,
    params: dict[str, Any] | None = None,
    seeds: Iterable[int | None] = (None,),
    cores: int = 1,
    loader: str | None = None,
) -> list[RunSpec]:
    """Every solver with every seed on every instance."""
    return [
        RunSpec(instance, solver, limits, dict(params or {}), seed, cores, loader)
        for instance in instances
        for solver in solvers
        for seed in seeds
    ]


_DONE = object()  # the end of the results, in iter_results_async's queue


class _Scheduler:
    """The runs of a session in progress: starts runs in free slots, passes on their events, and finishes
    them (storing the result) as they end. Both `iter_results` and `iter_results_async` drive it."""

    def __init__(self, session: "Session", executor: Executor):
        self.session = session
        self.executor = executor
        self.pending = deque(session.runs)
        self.active: dict[Future[Measurement], Run] = {}
        jobs = session.config.getoption("jobs")
        cores = max((r.cores for r in session.runs), default=1)
        self.free_slots = executor.slots(jobs, cores) if session.runs else []

    @property
    def busy(self) -> bool:
        return bool(self.pending or self.active)

    def step(self, timeout: float) -> list[RunResult]:
        """Start what fits, wait up to `timeout` seconds for a run to end, and return the runs' results that
        ended, stored."""
        while self.pending and self.free_slots:
            run, future = self.session._start(self.executor, self.pending.popleft(), self.free_slots.pop(0))
            self.active[future] = run
        done, _ = wait(self.active, timeout=timeout, return_when=FIRST_COMPLETED) if self.active else ((), ())
        for run in self.active.values():
            self.session._dispatch_events(run)
        results = []
        for future in done:
            run = self.active.pop(future)
            self.free_slots.append((run.cpus, run.memory_nodes))
            results.append(self.session._finish(run, future))
        return results


class Session:
    """Runs a list of `RunSpec`s: from `runs`, or else from the options and sources in `config` (the
    command line). `iter_results()` yields results as runs finish; `run()` returns them all."""

    def __init__(self, config: Config, runs: Iterable[RunSpec] | None = None):
        self.config = config
        self.hook = config.hook
        self.store = Store(config.getoption("out"))
        self.runs: list[RunSpec] = list(runs) if runs is not None else []
        self.collected = 0  # runs before `cpbenchy_modify_runs` (before -k, --limit, ...)
        self.already_done = 0  # selected runs skipped because `out` has their results (not with --rerun)
        self.results = Results()
        self.executor: Executor | None = None
        self.interrupted = False
        self._given_runs = runs is not None
        self._worker_job: dict[str, Any] = {}  # the part of every job file that's the same for all runs
        self._env: dict[str, str] = {}

    def collect(self) -> list[RunSpec]:
        runs = list(self.runs) if self._given_runs else self._runs_from_options()
        self.collected = len(runs)
        self.hook.cpbenchy_modify_runs(config=self.config, runs=runs)
        selected = len(runs)
        if not self.config.getoption("rerun"):  # resume: what is stored is done
            done = self.store.finished_ids()
            runs = [r for r in runs if r.run_id not in done]
        self.already_done = selected - len(runs)
        self.runs = runs
        self._check_loaders()
        return runs

    def _check_loaders(self) -> None:
        """Load each loader once here, so a mistake shows now rather than as an error in every run."""
        for ref in {r.loader for r in self.runs if r.loader}:
            try:
                loader = refs.load(ref)
            except UsageError:
                raise
            except Exception as e:
                raise UsageError(f"can't load the loader {ref!r}: {type(e).__name__}: {e}") from e
            if not isinstance(loader, Loader):
                raise UsageError(f"{ref!r} is a {type(loader).__name__}, not a cpbenchy.Loader")

    def _runs_from_options(self) -> list[RunSpec]:
        get = self.config.getoption
        if not get("solvers"):
            raise UsageError("no solver given (-s/--solver)")
        if get("time_limit") is None:
            raise UsageError("no time limit given (-t/--time-limit)")
        if not self.config.sources:
            raise UsageError("nothing to run: give instance files, directories, or a dataset")
        return grid(
            collect_instances(self.config, self.config.sources),
            get("solvers"),
            make_limits(self.config, get("time_limit"), get("mem_limit_mib"), get("cputime_limit_s")),
            parse_params(get("params")),
            get("seeds") or [None],
            get("cores"),
            get("loader"),
        )

    def run(self) -> Results:
        for _ in self.iter_results():
            pass
        return self.results

    def iter_results(self) -> Iterator[RunResult]:
        """Run everything, yielding each result as its run finishes (after it is stored).

        While the caller handles a result, the generator waits: runs already going go on, but no new run
        starts until the caller asks for the next result. Stopping early (`break`, an exception, Ctrl-C)
        stops the runs still going; they are not stored, so running again picks them up.
        """
        executor = self._prepare()
        self._begin()
        finished = False
        try:
            scheduler = _Scheduler(self, executor)
            while scheduler.busy:
                yield from scheduler.step(timeout=POLL_S)
            finished = True
        finally:
            self._end(executor, finished)

    async def iter_results_async(self) -> AsyncIterator[RunResult]:
        """`iter_results` for asyncio: `async for result in session.iter_results_async()`.

        A task in the event loop schedules the runs, and calls the hooks, while the caller handles results:
        a slow `async for` body doesn't hold up new runs, as long as it awaits. Setting up (collecting
        instances, choosing the executor) happens in a thread. Stopping early (`break`, cancelling) stops
        the runs still going, as `iter_results` does; after a `break`, that happens when the generator is
        closed (use `contextlib.aclosing` to close it right away).
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        task = asyncio.ensure_future(self._drive(queue))
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                yield item
            await task  # its exception, if it failed
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _drive(self, queue: "asyncio.Queue[Any]") -> None:
        executor = None
        finished = False
        try:
            executor = await asyncio.to_thread(self._prepare)
            self._begin()
            scheduler = _Scheduler(self, executor)
            while scheduler.busy:
                results = scheduler.step(timeout=0)
                for result in results:
                    queue.put_nowait(result)
                if not results:
                    await asyncio.sleep(POLL_S)
            finished = True
        finally:
            if executor is not None:
                self._end(executor, finished)
            queue.put_nowait(_DONE)

    def _prepare(self) -> Executor:
        """What may take a while before the runs start: collecting them, and choosing the executor."""
        if refs.importing:
            raise UsageError(
                "an experiment started while cpbenchy imported a plugin or loader: the file that defines it is "
                "imported again for each run, so its top-level code runs again. Start the experiment under "
                '`if __name__ == "__main__":`, or define the plugin in a file of its own'
            )
        self.collect()
        self._check_memory()
        self.store.open()
        self.executor = executor = self.hook.cpbenchy_make_executor(config=self.config)
        self._worker_job = {
            "plugins": self.config.worker_plugins(),
            "disabled": self.config.blocked,
            "options": self.config.worker_options(),
        }
        self._env = self._worker_env()
        return executor

    def _begin(self) -> None:
        self.store.write_provenance(self.provenance())
        self.hook.cpbenchy_sessionstart(session=self)

    def _end(self, executor: Executor, finished: bool) -> None:
        self.interrupted = not finished
        executor.close()
        self.hook.cpbenchy_sessionfinish(session=self)

    def _check_memory(self) -> None:
        jobs = self.config.getoption("jobs")
        mem_mib = max((r.limits.mem_mib or 0 for r in self.runs), default=0)
        total_mib = total_memory_mib()
        if mem_mib and total_mib and jobs * mem_mib > total_mib:
            rules = self.config.rules
            if rules and "mem-limit" in rules.settings and "mem-limit" not in self.config.deviations:
                hint = (
                    f"the memory limit is that of the rules {rules.name}; give a lower one with -m MIB (the runs "
                    "then record the rules as modified)"
                )
            else:
                hint = "give a lower memory limit (-m) or fewer parallel runs (-j)"
            raise UsageError(
                f"{jobs} parallel runs of {mem_mib} MiB need more than this machine's {total_mib} MiB: {hint}"
            )

    def _start(self, executor: Executor, spec: RunSpec, slot: tuple) -> "tuple[Run, Future[Measurement]]":
        cpus, memory_nodes = slot
        run = Run(
            spec=spec,
            job_file=self.store.job_file(spec.run_id),
            log_file=self.store.log_file(spec.run_id),
            events_file=self.store.events_file(spec.run_id),
            cmd=[sys.executable, "-m", "cpbenchy.worker"],
            env=dict(self._env),
            cpus=cpus,
            memory_nodes=memory_nodes,
        )
        for path in self.store.logs.glob(f"{spec.run_id}.*"):
            path.unlink()  # left over from an interrupted session or a rerun: log, events, artifacts
        self.hook.cpbenchy_run_start(run=run)
        job = {"spec": spec.to_dict(), "events": str(run.events_file), "cwd": os.getcwd(), **self._worker_job}
        run.job_file.write_text(json.dumps(job, indent=2, default=str))
        run.started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        worker_job = WorkerJob(
            run_id=spec.run_id,
            cmd=[*run.cmd, str(run.job_file)],
            job_file=run.job_file,
            log=run.log_file,
            limits=spec.limits,
            cpus=run.cpus,
            memory_nodes=run.memory_nodes,
            env=run.env,
        )
        return run, executor.start(worker_job)

    def _worker_env(self) -> dict[str, str]:
        loader_roots = [refs.root_of(ref) for ref in {r.loader for r in self.runs if r.loader}]
        paths = list(dict.fromkeys([*self.config.worker_pythonpath(), *filter(None, loader_roots)]))
        env = {k: v for k, v in THREAD_ENV.items() if k not in os.environ}
        if paths:
            env["PYTHONPATH"] = os.pathsep.join([*paths, *filter(None, [os.environ.get("PYTHONPATH")])])
        return env

    def _dispatch_events(self, run: Run) -> None:
        for event in run.read_events():
            self.hook.cpbenchy_run_event(run=run, event=event)

    def _finish(self, run: Run, future: "Future[Measurement]") -> RunResult:
        executor = self.executor
        assert executor is not None
        try:
            measurement = future.result()
            error = None
        except Exception as e:
            measurement = Measurement(None, None, None, None, None, executor.name, executor.reliable)
            error = f"executor failed: {type(e).__name__}: {e}"
        self._dispatch_events(run)
        result = RunResult.build(
            run.spec,
            run.report,
            measurement,
            started=run.started,
            host=socket.gethostname(),
            rules=self._rules_label(run.spec),
        )
        if error:
            result.status, result.error = "error", error
        result.cpus = list(run.cpus) if run.cpus else None
        result.extra.update(run.extra)
        self.hook.cpbenchy_run_finished(run=run, result=result)
        self.store.append(result)
        self.results.append(result)
        return result

    def _rules_label(self, spec: RunSpec) -> str | None:
        """The rules a run followed: the session's, "(modified)" if its own limits or cores differ."""
        config, get = self.config, self.config.getoption
        if config.rules is None:
            return None
        if get("time_limit") is not None:
            expected = make_limits(config, get("time_limit"), get("mem_limit_mib"), get("cputime_limit_s"))
            if spec.limits != expected or spec.cores != get("cores"):
                return config.rules.label({"run": "own limits"})
        return config.rules_label

    def provenance(self) -> dict[str, Any]:
        from importlib.metadata import version

        assert self.executor is not None
        return {
            "cpbenchy": cpbenchy.__version__,
            "cpmpy": version("cpmpy"),
            "python": sys.version.split()[0],
            "host": socket.gethostname(),
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "argv": sys.argv,
            "options": {k: v for k, v in vars(self.config.options).items() if k != "sources"},
            "sources": [str(s) for s in self.config.sources],
            "executor": {"name": self.executor.name, "reliable": self.executor.reliable},
            "plugins": [name for name, _ in self.config.pluginmanager.list_name_plugin()],
            "worker_plugins": self._worker_job["plugins"],
            "runs": len(self.runs),
            "rules": {**self.config.rules.to_dict(), "deviations": self.config.deviations}
            if self.config.rules
            else None,
        }
