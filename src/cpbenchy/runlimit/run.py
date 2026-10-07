import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


class Run:
    """A run in progress, from `start`."""

    def __init__(self, request: dict, timeout: float):
        self._timeout = timeout
        # The child moves itself into a fresh systemd scope for cgroup delegation; the caller must not.
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "cpbenchy.runlimit._child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(request))  # small, so this can't block on a full pipe
        self._proc.stdin.close()
        self._proc.stdin = None  # done with it: communicate() on Python 3.10 would flush the closed pipe

    def result(self) -> dict:
        """Wait for the run to end and return its result (see `run`)."""
        stdout, stderr = self._proc.communicate(timeout=self._timeout)
        lines = stdout.strip().splitlines()
        if not lines:
            raise RuntimeError(f"runlimit child produced no result (rc={self._proc.returncode}):\n{stderr}")
        reply = json.loads(lines[-1])
        if not reply["ok"]:
            raise RuntimeError(f"runlimit child failed: {reply['error']}\n{reply.get('traceback', '')}")
        return reply["result"]

    def terminate(self) -> None:
        """Stop the run early; `result()` then reports terminationreason "killed"."""
        if self._proc.poll() is None:
            self._proc.terminate()


def start(
    cmd: Sequence[str],
    *,
    output_file: Path,
    walltime: float | None = None,
    cputime: float | None = None,
    soft_cputime: float | None = None,
    memlimit_mib: int | None = None,
    cores: Sequence[int] | None = None,
    memory_nodes: Sequence[int] | None = None,
    container: bool = False,
    writable_dirs: Sequence[Path] = (),
    workdir: Path | None = None,
    env: dict | None = None,
) -> Run:
    """Start `cmd` under runexec without waiting for it; the arguments are those of `run`."""
    request = {
        "cmd": [str(c) for c in cmd],
        "output_file": str(Path(output_file).resolve()),
        "walltime": walltime,
        "cputime": cputime,
        "soft_cputime": soft_cputime,
        "memlimit_mib": memlimit_mib,
        "cores": list(cores) if cores is not None else None,
        "memory_nodes": list(memory_nodes) if memory_nodes is not None else None,
        "container": container,
        "writable_dirs": [str(Path(d).resolve()) for d in writable_dirs],
        "workdir": str(Path(workdir).resolve()) if workdir is not None else None,
        "env": env or {},
    }
    return Run(request, timeout=(walltime or 24 * 3600) + 300)


def run(cmd: Sequence[str], *, output_file: Path, **kwargs) -> dict:
    """Run `cmd` under runexec and return a normalized, JSON-safe result.

    `cores` pins the run to those CPU ids; `memory_nodes` restricts its memory to those NUMA nodes (use the
    nodes of `cores`, so a run doesn't reach across sockets).

    `cputime` kills the run after that much CPU time (of all its processes); `soft_cputime` sends it SIGTERM
    after that much, so it can stop by itself (terminationreason "cputime-soft" if it then does).

    The command's stdout and stderr go to `output_file`. With `container=True` the run has no network,
    sees `/` read-only (with a private, empty /tmp and home), and can only write to `writable_dirs`.

    Returned keys: walltime, cputime (seconds), memory (bytes), terminationreason (None if the
    command exited by itself, else e.g. "walltime", "memory" or "killed"), exitcode ({"code", "signal"}),
    mode ("python_api" or "cli"), raw (everything runexec reported).
    """
    return start(cmd, output_file=output_file, **kwargs).result()
