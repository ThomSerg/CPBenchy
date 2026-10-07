"""Stopping a run at its limit, as competitions do (`--terminate`): at the time limit (wall or CPU), or on
SIGTERM, the worker reports the best solution it has and exits, before the executor kills it `--grace`
seconds later.

A watcher thread does this, not a signal handler: Python runs signal handlers only between bytecodes of the
main thread, which may be inside a solver's `solve()` until long after the limit. So SIGTERM (and SIGXCPU,
the CPU limit of `setrlimit`) is blocked in every thread and the watcher waits for it with `sigtimedwait`,
checking the limits in between. The watcher can only run while the solver releases the GIL, as solvers
with a native core do while they search.

Solutions are kept as the solver reports them (`WorkerContext.keep_solution`, from its solution callback),
so a run stopped while solving reports its last one: status feasible, with that objective. Satisfaction
problems and solvers without a solution callback have none to report: they end as timeouts.
"""

import os
import signal
import sys
import threading
import time
import traceback

from cpbenchy.worker.context import WorkerContext

SIGNALS = {signal.SIGTERM, signal.SIGXCPU}
POLL_S = 0.05


def block_signals() -> None:
    """Block the signals in this thread, and so in the threads started after it. Call it before anything
    starts threads: a signal goes to any thread that doesn't block it, and kills the process there. Importing
    numpy does (OpenBLAS), and so CPMpy."""
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)


def install(ctx: WorkerContext) -> None:
    """Block the signals (see `block_signals`) and start the watcher."""
    block_signals()
    threading.Thread(target=_watch, args=(ctx,), name="cpbenchy-terminate", daemon=True).start()


def _watch(ctx: WorkerContext) -> None:
    limits = ctx.spec.limits
    while True:
        received = signal.sigtimedwait(SIGNALS, POLL_S)
        if ctx.elapsed() >= limits.time_s:
            reason = "walltime"
        elif limits.cputime_s is not None and ctx.cputime() >= limits.cputime_s:
            reason = "cputime"
        elif received is not None:
            reason = "cputime" if received.si_signo == signal.SIGXCPU else "signal"
        else:
            continue
        if stop(ctx, reason):
            return


def stop(ctx: WorkerContext, reason: str) -> bool:
    """Report what the run has and exit. Returns (True: stop watching) only if the run is already finishing
    by itself."""
    ctx.lock.acquire()  # never released: the process ends here, and a solution callback must not change `best`
    if ctx.finishing:
        ctx.lock.release()
        return True  # the run reports by itself; the executor's kill is the backstop
    try:
        ctx.terminated = reason
        ctx.log(f"stopped at the {reason} limit" if reason != "signal" else "stopped by SIGTERM")
        if ctx.solve_started is not None:
            ctx.times["solve_s"] = time.perf_counter() - ctx.solve_started
        if ctx.restore_best():
            ctx.status, ctx.objective = "feasible", ctx.best[0] if ctx.best else None
        else:
            ctx.status = "unknown"
        ctx.finishing = True
        try:
            ctx.hook.cpbenchy_worker_finish(ctx=ctx)
        except Exception as e:
            ctx.status, ctx.error = "error", f"in finish: {type(e).__name__}: {e}"
            traceback.print_exc()
        ctx.emit("result", **ctx.report())
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1 if ctx.status == "error" else 0)
