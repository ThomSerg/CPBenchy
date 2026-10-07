"""Run a command under BenchExec runexec resource limits, with a normalized JSON result.

Formerly the separate `runlimit` package. The child process (`_child`) moves itself into a systemd scope
with cgroup delegation and runs the command with runexec; `run` and `start` talk to it as JSON.
"""

from cpbenchy.runlimit.run import Run, run, start

__all__ = ["Run", "run", "start"]
