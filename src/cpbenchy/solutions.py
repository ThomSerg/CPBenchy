"""Built-in plugin: record each run's solutions over time, as `extra["solutions"]`: [[seconds, objective], ...].

The worker reports solutions of optimization problems through CPMpy's `display` callback (see
`cpbenchy.worker.solvers`). Recorded from the events, so also for runs that get killed.
"""

from cpbenchy import hookimpl


@hookimpl
def cpbenchy_addoption(parser):
    parser.getgroup("run").addoption(
        "--no-solutions",
        dest="solutions",
        action="store_false",
        help="don't report intermediate solutions (no solution callback)",
    )


@hookimpl
def cpbenchy_run_event(run, event):
    if event.kind == "solution":
        run.extra.setdefault("solutions", []).append([round(event.t, 3), event.data["objective"]])
