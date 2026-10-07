"""Runs one job: set up the worker's plugins, go through the steps, report.

A job file holds:
    spec      the RunSpec, as a dict
    events    path of the JSONL event file to append to
    cwd       the directory relative paths in the spec are relative to

With the `terminate` option, the run is stopped at its limit and reports what it has; see `terminate`.
    plugins   plugin and observer references to load besides the built-in ones (see `cpbenchy.refs`)
    disabled  names of built-in worker plugins not to load
    options   JSON-safe settings for plugins, available as `ctx.options`
    artifacts the directory for the run's own files (`ctx.artifact`); default: that of `events`
"""

import importlib
import json
import os
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pluggy

from cpbenchy import refs
from cpbenchy.observer import Observer, ObserverPlugin
from cpbenchy.spec import RunSpec
from cpbenchy.worker import hookspecs
from cpbenchy.worker.context import WorkerContext

BUILTIN_PLUGINS = {
    "defaults": "cpbenchy.worker.defaults",
    "solvers": "cpbenchy.worker.solvers",
}

# ExitStatus name -> status
_STATUS = {"OPTIMAL": "optimal", "FEASIBLE": "feasible", "UNSATISFIABLE": "unsat"}


def plugin_manager(plugins: Sequence[str] = (), disabled: Sequence[str] = ()) -> pluggy.PluginManager:
    pm = pluggy.PluginManager("cpbenchy")
    pm.add_hookspecs(hookspecs)
    for name in disabled:
        pm.set_blocked(name)
    for name, module in BUILTIN_PLUGINS.items():
        if not pm.is_blocked(name):
            pm.register(importlib.import_module(module), name)
    for ref in plugins:
        plugin = refs.load(ref)
        pm.register(ObserverPlugin(plugin) if isinstance(plugin, Observer) else plugin, ref)
    return pm


def run(ctx: WorkerContext) -> None:
    hook = ctx.hook
    try:
        hook.cpbenchy_worker_start(ctx=ctx)

        ctx.log(f"loading {ctx.spec.instance.path}")
        t0 = time.perf_counter()
        ctx.model = hook.cpbenchy_worker_load(ctx=ctx)
        ctx.times["parse_s"] = time.perf_counter() - t0
        ctx.emit("loaded", parse_s=ctx.times["parse_s"], has_objective=ctx.model.has_objective())

        ctx.log(f"loaded in {ctx.times['parse_s']:.2f}s; creating solver {ctx.spec.solver}")
        t0 = time.perf_counter()
        ctx.solver = hook.cpbenchy_worker_solver(ctx=ctx)
        ctx.times["transform_s"] = time.perf_counter() - t0
        ctx.emit("transformed", transform_s=ctx.times["transform_s"])

        args: dict[str, Any] = {}
        for part in reversed(hook.cpbenchy_worker_solver_args(ctx=ctx)):
            args.update(part)
        ctx.solver_args = {**args, **ctx.spec.params}

        ctx.log(f"transformed in {ctx.times['transform_s']:.2f}s; solving, {ctx.time_left():.2f}s left")
        ctx.emit("solving", time_left_s=ctx.time_left())
        ctx.solve_started = t0 = time.perf_counter()
        hook.cpbenchy_worker_solve(ctx=ctx)
        with ctx.lock:  # from here on, the run reports by itself even if stopped at its limit
            ctx.finishing = True
        ctx.times["solve_s"] = time.perf_counter() - t0

        ctx.status = _STATUS.get(ctx.solver.status().exitstatus.name, "unknown")
        if ctx.status in ("optimal", "feasible") and ctx.model.has_objective():
            ctx.objective = ctx.solver.objective_value()
        ctx.log(f"solved in {ctx.times['solve_s']:.2f}s: {ctx.status}")
    except Exception as e:
        ctx.status, ctx.error = "error", f"{type(e).__name__}: {e}"
        traceback.print_exc()
    finally:
        with ctx.lock:
            ctx.finishing = True
        try:
            hook.cpbenchy_worker_finish(ctx=ctx)
        except Exception as e:
            ctx.status, ctx.error = "error", ctx.error or f"in finish: {type(e).__name__}: {e}"
            traceback.print_exc()


def main(argv: list[str], standalone: bool = False) -> int:
    """Run the job in `argv[0]`; see `execute`."""
    ctx = execute(json.loads(Path(argv[0]).read_text()), standalone)
    return 1 if ctx.status == "error" else 0


def execute(job: dict[str, Any], standalone: bool = False, extra_plugins: Sequence[Any] = ()) -> WorkerContext:
    """Run a job (see the module's docs). `standalone`: this is the measured process (`python -m
    cpbenchy.worker`, or `cpbenchy solve`), so time counts from when the process started, and `--terminate`
    can stop it; else (the inline executor) from now, without stopping. `extra_plugins` are plugin objects
    to register as they are."""
    options = job.get("options") or {}
    start = time.perf_counter() - process_age() if standalone else None
    with open(job["events"], "a") as events:
        spec = RunSpec.from_dict(job["spec"])
        artifacts = Path(job.get("artifacts") or Path(job["events"]).parent)
        ctx = WorkerContext(spec, events, options, artifacts, start)
        if standalone and options.get("terminate"):
            from cpbenchy.worker import terminate

            terminate.install(ctx)
        try:
            pm = plugin_manager(job.get("plugins", []), job.get("disabled", []))
            for plugin in extra_plugins:
                pm.register(plugin)
            ctx.hook = pm.hook
        except Exception as e:
            ctx.status, ctx.error = "error", f"loading plugins: {type(e).__name__}: {e}"
            traceback.print_exc()
        else:
            run(ctx)
        ctx.emit("result", **ctx.report())
    return ctx


def process_age() -> float:
    """Seconds since this process started (from /proc on Linux; elsewhere 0, i.e. from now)."""
    try:
        with open("/proc/self/stat") as f:
            fields = f.read().rpartition(")")[2].split()  # after the command name, which may hold spaces
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        return max(0.0, uptime - int(fields[19]) / os.sysconf("SC_CLK_TCK"))  # field 22: starttime, in ticks
    except (OSError, ValueError, IndexError):
        return 0.0
