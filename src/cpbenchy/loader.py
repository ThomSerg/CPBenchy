"""Loaders: how an instance becomes a CPMpy model, in the measured worker process.

By default cpbenchy uses CPMpy's loader for the instance's format (from its file name). To load
instances your own way, subclass `Loader` and override `load`:

    class KnapsackJSON(cpbenchy.Loader):
        def load(self, instance):
            data = json.loads(self.read(instance.path))
            ...
            return model

and use it with `--loader "file.py:KnapsackJSON"` (with arguments: `"file.py:MyLoader(k=1)"`), or
`loader=KnapsackJSON()` in Python. Constructor arguments must be Python literals: the worker creates
the loader again from them. The loader is part of what a run measures, so the same instance with
another loader is another run, and results record it as `loader`.

Imported inside the measured worker process: Python 3.10 compatible.
"""

import builtins
import bz2
import gzip
import lzma
from collections.abc import Callable
from typing import Any

from cpbenchy.refs import Shippable

_DECOMPRESS = {".lzma": lzma.open, ".xz": lzma.open, ".gz": gzip.open, ".bz2": bz2.open}


class Loader(Shippable):
    def load(self, instance) -> Any:
        """Return a `cpmpy.Model` for `instance` (an `Instance`: `path`, `name`, `format`, `metadata`).

        The default: CPMpy's `cpmpy.tools.io.load` for the instance's format, decompressing by extension.
        """
        from cpmpy.tools.io import load

        return load(instance.path, format=instance.format, open=self.opener(instance.path))

    def opener(self, path: str) -> Callable:
        """`open` that decompresses `.xz`, `.lzma`, `.gz` and `.bz2` files, for loaders taking `open=`."""
        for suffix, open_compressed in _DECOMPRESS.items():
            if path.endswith(suffix):
                return lambda p, mode="rt", **kw: open_compressed(p, mode, **kw)
        return builtins.open

    def read(self, path: str) -> str:
        """The (decompressed) contents of a file."""
        with self.opener(path)(path) as f:
            return f.read()
