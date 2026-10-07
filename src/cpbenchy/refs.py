"""References to plugins, observers and loaders, so the worker (another process) can load them itself.

A reference is one of:

    pkg.module                     a module
    path/to/file.py                a module, from a file
    pkg.module:Name                an attribute; a class is instantiated without arguments
    path/to/file.py:Name(1, k="v") a class, instantiated with these arguments (Python literals)

Objects of `Shippable` subclasses (observers, loaders) remember their constructor arguments, so cpbenchy
can make a reference that re-creates them in the worker.

Imported inside the measured worker process: standard library only, Python 3.10 compatible.
"""

import ast
import hashlib
import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

from cpbenchy.errors import UsageError


class Shippable:
    """Remembers its constructor arguments, so cpbenchy can create the same object in the worker. The
    arguments must be Python literals: strings, numbers, booleans, None, and lists, tuples or dicts of
    these."""

    _cpbenchy_args: tuple = ()
    _cpbenchy_kwargs: dict = {}  # noqa: RUF012

    def __new__(cls, *args: Any, **kwargs: Any):
        obj = super().__new__(cls)
        obj._cpbenchy_args, obj._cpbenchy_kwargs = args, kwargs
        return obj


def parse(ref: str) -> tuple[str, str, tuple, dict, bool]:
    """`ref` -> (module or file, attribute name or "", args, kwargs, whether arguments were given)."""
    target, _, attr = ref.partition(":")
    if "(" not in attr:
        return target, attr, (), {}, False
    try:
        call = ast.parse(attr, mode="eval").body
        if not (isinstance(call, ast.Call) and isinstance(call.func, (ast.Name, ast.Attribute))):
            raise ValueError
        args = tuple(ast.literal_eval(a) for a in call.args)
        kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords if k.arg}
    except (SyntaxError, ValueError) as e:
        raise UsageError(f"can't read {ref!r}: arguments must be Python literals, as in Name(1, key='value')") from e
    return target, ast.unparse(call.func), args, kwargs, True


_file_modules: dict[str, Any] = {}

# How many references are being imported now. An experiment that starts during one is the top-level code of
# the imported file (say, the script that defines an observer) running again; sessions refuse to start then.
importing = 0


def load_module(target: str) -> Any:
    global importing
    importing += 1
    try:
        return _load_module(target)
    finally:
        importing -= 1


def _load_module(target: str) -> Any:
    if not target.endswith(".py"):
        return importlib.import_module(target)
    path = str(Path(target).resolve())
    if path not in _file_modules:
        name = f"cpbenchy_plugin_{Path(path).stem}_{hashlib.sha1(path.encode()).hexdigest()[:8]}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise UsageError(f"cannot load {target}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _file_modules[path] = module
    return _file_modules[path]


def load(ref: str) -> Any:
    """What `ref` refers to: a module, or an instance of the named class (or the named object)."""
    target, attr, args, kwargs, called = parse(ref)
    module = load_module(target)
    if not attr:
        return module
    obj = module
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj(*args, **kwargs) if called or inspect.isclass(obj) else obj


def ref_for(obj: Any) -> tuple[str, str | None]:
    """A reference that re-creates `obj` (a module, a class, or an instance) in another process, and the
    directory to put on that process's path to import it, if any."""
    module = obj if inspect.ismodule(obj) else inspect.getmodule(obj if inspect.isclass(obj) else type(obj))
    file = getattr(module, "__file__", None)
    if module is None and not inspect.ismodule(obj):  # e.g. a script imported without registering it
        try:
            file = inspect.getfile(obj if inspect.isclass(obj) else type(obj))
        except (TypeError, OSError):
            file = None
    if file is None:
        raise UsageError(
            f"{obj!r} has no module or file another process could load it from; define it in a .py file "
            "(not in a notebook or the interactive prompt)"
        )
    if module is None or module.__name__.startswith("cpbenchy_plugin_") or module.__name__ == "__main__":
        target, root = file, None  # loaded from a file, or defined in a script
    else:
        target, root = module.__name__, _import_root(module.__name__, file)
    if inspect.ismodule(obj):
        return target, root
    cls = obj if inspect.isclass(obj) else type(obj)
    ref = f"{target}:{cls.__qualname__}"
    if isinstance(obj, Shippable):
        ref += f"({_arguments(obj)})"
    return ref, root


def root_of(ref: str) -> str | None:
    """The directory to put on another process's path to import `ref`'s module, if any."""
    target = parse(ref)[0]
    if target.endswith(".py"):
        return None
    module = load_module(target)
    return _import_root(module.__name__, module.__file__) if getattr(module, "__file__", None) else None


def short(ref: str) -> str:
    """`ref` without its module or file: what identifies an object across machines, e.g. `NQueens('pairwise')`."""
    return ref.partition(":")[2] or ref


def _import_root(name: str, file: str) -> str:
    root = Path(file).resolve().parent
    for _ in range(name.count(".") + (Path(file).name == "__init__.py")):
        root = root.parent
    return str(root)


def _arguments(obj: Shippable) -> str:
    values = [*obj._cpbenchy_args, *obj._cpbenchy_kwargs.values()]
    text = ", ".join([repr(a) for a in obj._cpbenchy_args] + [f"{k}={v!r}" for k, v in obj._cpbenchy_kwargs.items()])
    try:
        literal = all(ast.literal_eval(repr(v)) == v for v in values)
    except (SyntaxError, ValueError):
        literal = False
    if not literal:
        raise UsageError(
            f"{type(obj).__name__}'s arguments ({text}) can't be passed to the worker: use Python literals "
            "(strings, numbers, booleans, None, lists, tuples, dicts)"
        )
    return text
