"""Hooks called in the parent process, in this order:

    addoption, configure                once, while setting up
    collect (per source), modify_runs   building the list of runs
    make_executor, sessionstart
    per run: run_start, run_event (live, repeatedly), run_finished
    sessionfinish

All parent hooks are called from the main thread, so plugins need no locking. The hooks that run inside
the measured worker process are in `cpbenchy.worker.hookspecs`.
"""

from cpbenchy import hookspec


@hookspec(historic=True)
def cpbenchy_addoption(parser):
    """Add command-line options: `parser.addoption(...)` or `parser.getgroup(name).addoption(...)`, with
    argparse's arguments. Values are available as `config.getoption(dest)`."""


@hookspec(historic=True)
def cpbenchy_configure(config):
    """Options are parsed and plugins registered."""


@hookspec(firstresult=True)
def cpbenchy_collect(source, config):
    """Turn one source into a list of `Instance`s, or return None if this plugin doesn't handle it.

    Built in: a cpmpy `Dataset`, an `Instance`, a file, a directory, a glob pattern, or a list of these.
    """


@hookspec
def cpbenchy_modify_runs(config, runs):
    """Filter, reorder or extend `runs` (a list of `RunSpec`) in place, before anything runs. Runs whose
    results are already stored are skipped after this (unless `--rerun`)."""


@hookspec(firstresult=True)
def cpbenchy_make_executor(config):
    """Return the `Executor` that runs the workers (see `cpbenchy.executors`)."""


@hookspec
def cpbenchy_sessionstart(session):
    """Before the first run starts; `session.runs` holds the runs to do."""


@hookspec
def cpbenchy_run_start(run):
    """A run is about to start. `run.cmd` and `run.env` may still be changed (e.g. to use another python)."""


@hookspec
def cpbenchy_run_event(run, event):
    """The worker of `run` sent an `Event` (`event.kind`: loaded, transformed, solving, solution, result,
    or anything a worker plugin emits)."""


@hookspec
def cpbenchy_run_finished(run, result):
    """A run is done; `result` is about to be stored, so `result.extra` can still be added to."""


@hookspec
def cpbenchy_sessionfinish(session):
    """All runs are done (or the session was interrupted); `session.results` holds this session's results."""
