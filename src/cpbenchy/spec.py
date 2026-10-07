"""What to run: an instance, a solver configuration, and limits.

A `RunSpec` describes one run completely. It is plain data and travels as JSON to the worker process (and,
later, to remote executors), so everything in it must be JSON-serializable.

This module is imported inside the measured worker process, so it must stay standard-library only and
Python 3.10 compatible.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cpbenchy.refs import short

COMPRESSION_SUFFIXES = (".lzma", ".xz", ".gz", ".bz2")


@dataclass(frozen=True)
class Instance:
    """One benchmark instance file.

    `format` is a `cpmpy.tools.io.load_formats()` name; None means derive it from the file name.
    """

    path: str
    name: str
    dataset: str | None = None
    format: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_path(cls, path: str | Path, **kwargs: Any) -> "Instance":
        """An instance named after its file, without compression and format extensions."""
        name = Path(path).name
        for suffix in COMPRESSION_SUFFIXES:
            name = name.removesuffix(suffix)
        name = name.rsplit(".", 1)[0] if "." in name else name
        return cls(path=str(path), name=name, **kwargs)

    @property
    def key(self) -> str:
        """What identifies the instance across machines: dataset and name if known, else its path."""
        return f"{self.dataset}/{self.name}" if self.dataset else self.path


@dataclass(frozen=True)
class Limits:
    """How much a run may use. `time_s` is wall time; `cputime_s` (optional) the CPU time of the run's
    processes, as competitions limit sequential solvers."""

    time_s: float
    mem_mib: int | None = None
    cputime_s: float | None = None


@dataclass(frozen=True)
class RunSpec:
    instance: Instance
    solver: str
    limits: Limits
    params: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    cores: int = 1
    loader: str | None = None  # a reference to a `Loader` (see `cpbenchy.refs`); None: CPMpy's loaders

    @property
    def run_id(self) -> str:
        """Stable id of what is measured (not of how it is scheduled); finished ids are skipped on resume."""
        key = {
            "instance": self.instance.key,
            "solver": self.solver,
            "params": self.params,
            "seed": self.seed,
            "cores": self.cores,
            # without unset optional limits, so ids stay those of before they existed
            "limits": {k: v for k, v in asdict(self.limits).items() if v is not None or k in ("time_s", "mem_mib")},
        }
        if self.loader:  # by class and arguments, not by where its file is
            key["loader"] = short(self.loader)
        return hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunSpec":
        data = dict(data)
        data["instance"] = Instance(**data["instance"])
        data["limits"] = Limits(**data["limits"])
        return cls(**data)
