"""`cpbenchy solve INSTANCE`: solve one instance in this process, as a competition runs a solver.

    cpbenchy solve instance.xml -s ortools --rules xcsp3-2025 --cpu-time-limit 1800 --seed 7

Where `cpbenchy run` starts a measured worker process per run under an executor's limits, `solve` *is* the
measured process: the competition's own tool (e.g. runsolver) limits and measures it, and reads its
standard output. So it runs the worker in this process, with:

- competition output (`o`, `s`, `v` lines from the rules' output observer) on stdout, progress as
  comment lines (`c ...`), and a summary of the run as comments at the end
- `--terminate` on: at its time limit, or on SIGTERM, it prints the best solution found so far
- time counted from when this process started
- the run's own files (`ctx.artifact`) in a fresh directory under $TMPDIR

It takes the options of `cpbenchy run` that make sense for one run. The launchers of a submission
(`cpbenchy submission`) call it.
"""

import json
import os
import tempfile
from collections.abc import Sequence

from cpbenchy import hookimpl
from cpbenchy.config import UsageError, make_config
from cpbenchy.session import collect_instances, make_limits, parse_params
from cpbenchy.spec import RunSpec


class _Summary:
    """The run's outcome as comment lines, last thing in the worker (also when stopped at its limit)."""

    @hookimpl(trylast=True)
    def cpbenchy_worker_finish(self, ctx):
        times = ", ".join(f"{k[:-2]} {v:.2f}s" for k, v in ctx.times.items() if k.endswith("_s"))
        objective = f", objective {ctx.objective}" if ctx.objective is not None else ""
        stopped = f", stopped ({ctx.terminated})" if ctx.terminated else ""
        print(f"c cpbenchy: {ctx.status}{objective}{stopped}; {times}", flush=True)
        if ctx.error:
            print(f"c cpbenchy: {ctx.error}", flush=True)


def solve(args: Sequence[str]) -> int:
    config = make_config(args, prog="cpbenchy solve")
    get = config.getoption
    if len(get("solvers")) != 1:
        raise UsageError("solve needs exactly one solver (-s)")
    if len(get("seeds")) > 1:
        raise UsageError("solve runs one seed")
    if get("time_limit") is None and get("cputime_limit_s") is None:
        raise UsageError("no time limit (-t, --cpu-time-limit or --rules)")
    instances = collect_instances(config, config.sources)
    if len(instances) != 1:
        raise UsageError(f"solve needs exactly one instance, got {len(instances)}")
    # the CPU time limit bounds the wall time too when it is the only one, as for a sequential solver
    time_limit = get("time_limit") if get("time_limit") is not None else get("cputime_limit_s")
    spec = RunSpec(
        instances[0],
        get("solvers")[0],
        make_limits(config, time_limit, get("mem_limit_mib"), get("cputime_limit_s")),
        parse_params(get("params")),
        get("seeds")[0] if get("seeds") else None,
        get("cores"),
        get("loader"),
    )
    job = {
        "spec": spec.to_dict(),
        "events": os.devnull,
        "artifacts": tempfile.mkdtemp(prefix="cpbenchy-solve-"),
        "plugins": config.worker_plugins(),
        "disabled": config.blocked,
        "options": {**json.loads(json.dumps(config.worker_options(), default=str)), "stdout": True, "terminate": True},
    }
    from cpbenchy.worker.runtime import execute

    ctx = execute(job, standalone=True, extra_plugins=[_Summary()])
    return 1 if ctx.status == "error" else 0
