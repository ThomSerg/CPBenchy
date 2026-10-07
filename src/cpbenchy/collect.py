"""Built-in collection: instances from files, directories, glob patterns and cpmpy datasets; and selecting
which of them to run (`-k`, `--limit`)."""

import fnmatch
import glob
import json
from pathlib import Path
from typing import Any

from cpbenchy import hookimpl
from cpbenchy.config import UsageError
from cpbenchy.spec import COMPRESSION_SUFFIXES, Instance

# cpmpy dataset name -> cpmpy load format, where they differ
DATASET_FORMATS = {"maxsateval": "wcnf", "psplib": "rcpsp", "scaledsudoku": "sudoku", "sat": "cnf"}
# file suffix -> cpmpy load format, for files cpmpy can't derive the format of
SUFFIX_FORMATS = {".xml": "xcsp3"}


@hookimpl
def cpbenchy_addoption(parser):
    group = parser.getgroup("selection")
    group.addoption("-k", dest="keyword", metavar="PATTERN", help="only instances whose name matches (glob)")
    group.addoption("--limit", type=int, metavar="N", help="only the first N instances")
    group.addoption("--format", help="cpmpy load format of the instance files (default: from the file name)")


@hookimpl(trylast=True)
def cpbenchy_collect(source, config):
    if isinstance(source, Instance):
        return [source]
    if isinstance(source, (list, tuple)):
        instances = []
        for item in source:
            found = config.hook.cpbenchy_collect(source=item, config=config)
            if found is None:
                return None
            instances.extend(found)
        return instances
    if _is_dataset(source):
        return from_dataset(source)
    if isinstance(source, (str, Path)):
        return from_path(source, format=config.getoption("format"))
    return None


@hookimpl
def cpbenchy_modify_runs(config, runs):
    pattern, limit = config.getoption("keyword"), config.getoption("limit")
    if pattern:
        if not any(ch in pattern for ch in "*?["):
            pattern = f"*{pattern}*"
        runs[:] = [r for r in runs if fnmatch.fnmatch(r.instance.name, pattern)]
    if limit is not None:
        keep = list(dict.fromkeys(r.instance.key for r in runs))[:limit]
        runs[:] = [r for r in runs if r.instance.key in keep]


def from_path(source: str | Path, format: str | None = None) -> list[Instance]:
    path = Path(source)
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file() and _is_instance_file(p))
    elif glob.has_magic(str(source)):
        files = sorted(Path(p) for p in glob.glob(str(source), recursive=True) if Path(p).is_file())
    else:
        raise UsageError(f"{source}: no such file or directory")
    return [Instance.from_path(f, format=format or _format_of(f)) for f in files]


def from_dataset(dataset: Any) -> list[Instance]:
    """The instances of a cpmpy `Dataset`; the worker loads them, so the dataset must yield file paths."""
    name = getattr(dataset, "name", None)
    format = DATASET_FORMATS.get(name, name) if name else None
    instances = []
    for item, metadata in dataset:
        if not isinstance(item, (str, Path)):
            raise UsageError(
                f"dataset {name!r} yields {type(item).__name__}, not file paths: cpbenchy loads instances in the "
                "measured worker process, so pass the dataset without a loading transform"
            )
        meta = json.loads(json.dumps(metadata, default=str))  # results are JSON
        path = Path(item)
        instances.append(
            Instance(
                path=str(path.resolve()),
                name=str(meta.get("name") or Instance.from_path(path).name),
                dataset=meta.get("dataset") or name,
                format=format if format in _load_formats() else _format_of(path),
                metadata=meta,
            )
        )
    return instances


def _is_dataset(source: Any) -> bool:
    try:
        from cpmpy.tools.datasets.core import Dataset
    except ImportError:  # pragma: no cover
        return False
    return isinstance(source, Dataset)


def _is_instance_file(path: Path) -> bool:
    return not path.name.startswith(".") and not path.name.endswith(".meta.json")


def _format_of(path: Path) -> str | None:
    """The cpmpy load format from the file name (as cpmpy itself would derive it), or None."""
    name = path.name
    for suffix in COMPRESSION_SUFFIXES:
        name = name.removesuffix(suffix)
    if Path(name).suffix in SUFFIX_FORMATS:
        return SUFFIX_FORMATS[Path(name).suffix]
    try:
        from cpmpy.tools.io.utils import _derive_format  # private, so tolerate it changing

        return _derive_format(name)
    except Exception:
        return None


def _load_formats() -> list[str]:
    from cpmpy.tools.io import load_formats

    return load_formats()
