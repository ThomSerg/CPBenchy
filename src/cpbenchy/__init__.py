"""cpbenchy: benchmark CPMpy solvers on datasets under proper resource limits, extensible with plugins.

This module is imported inside the measured worker process too, so it only defines the plugin markers and
loads the rest of the public API lazily.
"""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

import pluggy

try:
    __version__ = version("cpbenchy")
except PackageNotFoundError:  # imported from a source tree, e.g. inside a solver env
    __version__ = "unknown"

hookspec = pluggy.HookspecMarker("cpbenchy")
hookimpl = pluggy.HookimplMarker("cpbenchy")

if TYPE_CHECKING:
    from cpbenchy import backend, check, formats, observers, scoring
    from cpbenchy.api import load, run, run_async
    from cpbenchy.experiment import Experiment
    from cpbenchy.loader import Loader
    from cpbenchy.observer import Observer
    from cpbenchy.result import Results, RunResult
    from cpbenchy.spec import Instance, Limits, RunSpec

_LAZY = {
    "run": "cpbenchy.api",
    "run_async": "cpbenchy.api",
    "load": "cpbenchy.api",
    "Experiment": "cpbenchy.experiment",
    "Observer": "cpbenchy.observer",
    "Loader": "cpbenchy.loader",
    "Instance": "cpbenchy.spec",
    "Limits": "cpbenchy.spec",
    "RunSpec": "cpbenchy.spec",
    "RunResult": "cpbenchy.result",
    "Results": "cpbenchy.result",
}

_SUBMODULES = ("backend", "check", "formats", "observers", "scoring")

__all__ = [
    "__version__",
    "hookimpl",
    "hookspec",
    "run",
    "run_async",
    "load",
    "Experiment",
    "Observer",
    "Loader",
    "Instance",
    "Limits",
    "RunSpec",
    "RunResult",
    "Results",
    "backend",
    "check",
    "formats",
    "observers",
    "scoring",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        return getattr(import_module(_LAZY[name]), name)
    if name in _SUBMODULES:
        return import_module(f"cpbenchy.{name}")
    raise AttributeError(f"module 'cpbenchy' has no attribute {name!r}")
