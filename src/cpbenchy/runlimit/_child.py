"""Executes one runlimit request (JSON on stdin) and prints one JSON reply line on stdout.

Ported from cpbenchy's RunExecResourceManager (`_runexec_worker` and helpers): first try BenchExec's
in-process RunExecutor inside a fresh delegated systemd scope; if BenchExec cannot use cgroups, fall back
to the `runexec` CLI wrapped in `systemd-run --user --scope -p Delegate=yes`.
"""

import json
import logging
import math
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import traceback

MIB = 1024 * 1024

# What to stop when this process gets SIGTERM or SIGINT: the RunExecutor or the runexec CLI process.
_running = None


def ensure_systemd_scope() -> bool:
    """Move this process into its own transient systemd scope with cgroup delegation (cgroups v2)."""
    try:
        with open("/proc/self/cgroup") as f:
            if "runlimit_" in f.read():
                return True
    except OSError:
        pass

    scope_name = f"runlimit_{secrets.token_urlsafe(8)}.scope"

    def start_scope(user_bus: bool, slice_name: str) -> str:
        cmd = (
            ["busctl"]
            + (["--user"] if user_bus else [])
            + [
                "call",
                "org.freedesktop.systemd1",
                "/org/freedesktop/systemd1",
                "org.freedesktop.systemd1.Manager",
                "StartTransientUnit",
                "ssa(sv)a(sa(sv))",
                scope_name,
                "fail",
                "3",
                "PIDs",
                "au",
                "1",
                str(os.getpid()),
                "Delegate",
                "b",
                "true",
                "Slice",
                "s",
                slice_name,
                "0",
            ]
        )
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return "" if res.returncode == 0 else (res.stderr or res.stdout or "failed").strip()

    errors = []
    for user_bus, slice_name in ((True, "benchexec.slice"), (False, "system.slice")):
        try:
            err = start_scope(user_bus, slice_name)
        except FileNotFoundError:
            logging.warning("busctl not found, cannot create systemd scope")
            return False
        except Exception as e:
            err = str(e)
        if not err:
            time.sleep(0.1)  # give systemd time to move the process
            return True
        errors.append(f"{'user' if user_bus else 'system'}-bus: {err}")
    logging.warning("Failed to create systemd scope (%s)", " | ".join(errors))
    return False


def to_json_safe(value):
    from datetime import datetime
    from decimal import Decimal

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    # ProcessExitCode is a NamedTuple, so check it before the generic tuple case
    if hasattr(value, "raw") and hasattr(value, "value") and hasattr(value, "signal"):
        return {"raw": value.raw, "code": value.value, "signal": value.signal}
    if isinstance(value, dict):
        return {k: to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def parse_runexec_output(stdout: str) -> dict:
    """Parse the key=value lines printed by the `runexec` CLI into RunExecutor-like values."""
    result = {}
    for line in stdout.strip().splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        try:
            if key in ("walltime", "cputime") or key.startswith("cputime-"):
                result[key] = float(value.rstrip("s"))
            elif key in ("memory", "blkio-read", "blkio-write"):
                result[key] = int(value.rstrip("B"))
            elif key == "returnvalue":
                result.setdefault("exitcode", {})["code"] = int(value)
            elif key == "exitsignal":
                result.setdefault("exitcode", {})["signal"] = int(value)
            elif key in ("terminationreason", "starttime"):
                result[key] = value
            else:
                result[key] = float(value.rstrip("sJB"))
        except ValueError:
            result[key] = value
    return result


def normalize(raw: dict, mode: str) -> dict:
    exitcode = raw.get("exitcode") or {}
    return {
        "walltime": raw.get("walltime"),
        "cputime": raw.get("cputime"),
        "memory": raw.get("memory"),
        "terminationreason": raw.get("terminationreason"),
        "exitcode": {"code": exitcode.get("code"), "signal": exitcode.get("signal")},
        "mode": mode,
        "raw": raw,
    }


def run_python_api(req: dict) -> dict:
    from benchexec.container import DIR_FULL_ACCESS, DIR_HIDDEN, DIR_READ_ONLY
    from benchexec.runexecutor import RunExecutor

    if not ensure_systemd_scope():
        logging.warning("No delegated systemd scope; RunExecutor may fail to initialize cgroups.")
    kwargs = {"use_namespaces": req["container"]}
    if req["container"]:
        # Read-only root instead of BenchExec's default overlay: fuse-overlayfs over / can hang.
        dir_modes = {"/": DIR_READ_ONLY, "/run": DIR_HIDDEN, "/tmp": DIR_HIDDEN}
        for d in req["writable_dirs"]:
            dir_modes[d] = DIR_FULL_ACCESS
        kwargs.update(dir_modes=dir_modes, network_access=False)
    global _running
    executor = _running = RunExecutor(**kwargs)
    raw = executor.execute_run(
        args=req["cmd"],
        output_filename=req["output_file"],
        walltimelimit=req["walltime"],
        hardtimelimit=req.get("cputime"),
        softtimelimit=req.get("soft_cputime"),
        cores=req["cores"],
        memory_nodes=req.get("memory_nodes"),
        memlimit=req["memlimit_mib"] * MIB if req["memlimit_mib"] else None,
        workingDir=req["workdir"],
        environments={"newEnv": req["env"]} if req["env"] else {},
        write_header=False,
    )
    return normalize(to_json_safe(dict(raw)), "python_api")


def run_cli(req: dict) -> dict:
    cmd = ["runexec", "--output", req["output_file"]]
    if req["walltime"] is not None:
        cmd += ["--walltimelimit", str(int(req["walltime"]))]
    if req.get("cputime") is not None:
        cmd += ["--timelimit", str(math.ceil(req["cputime"]))]
    if req.get("soft_cputime") is not None:
        cmd += ["--softtimelimit", str(math.ceil(req["soft_cputime"]))]
    if req["memlimit_mib"]:
        cmd += ["--memlimit", str(req["memlimit_mib"] * MIB)]
    if req["cores"]:
        cmd += ["--cores", ",".join(map(str, req["cores"]))]
    if req.get("memory_nodes"):
        cmd += ["--memoryNodes", ",".join(map(str, req["memory_nodes"]))]
    if req["workdir"]:
        cmd += ["--dir", req["workdir"]]
    if req["container"]:
        cmd += ["--read-only-dir", "/", "--hidden-dir", "/run", "--hidden-dir", "/tmp"]
        for d in req["writable_dirs"]:
            cmd += ["--full-access-dir", d]
    else:
        cmd += ["--no-container"]
    cmd += ["--"]
    if req["env"]:
        cmd += ["env"] + [f"{k}={v}" for k, v in req["env"].items()]
    cmd += req["cmd"]
    scope = (
        ["systemd-run"]
        + (["--user"] if os.geteuid() != 0 else [])
        + [
            "--scope",
            "--slice=benchexec",
            "-p",
            "Delegate=yes",
        ]
    )
    global _running
    proc = _running = subprocess.Popen(scope + cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate(timeout=(req["walltime"] or 3600) + 120)
    if proc.returncode != 0 and not stdout.strip():
        raise RuntimeError(f"runexec CLI failed (rc={proc.returncode}):\n{stderr}")
    return normalize(parse_runexec_output(stdout), "cli")


def is_cgroup_failure(exc: BaseException) -> bool:
    return isinstance(exc, SystemExit) and "not able to use cgroups" in str(exc.code or "")


def stop(signum, frame):
    """Stop the run, which then ends with terminationreason "killed" and a normal reply."""
    if _running is None:
        raise KeyboardInterrupt(f"stopped by signal {signum} before the run started")
    if isinstance(_running, subprocess.Popen):
        _running.send_signal(signal.SIGTERM)  # runexec stops the run itself
    else:
        # Not from this handler: it interrupts the main thread, which may hold the lock stop() takes.
        threading.Thread(target=_running.stop, daemon=True).start()


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    req = json.load(sys.stdin)
    try:
        try:
            result = run_python_api(req)
        except SystemExit as e:
            if not is_cgroup_failure(e):
                raise
            result = run_cli(req)
        reply = {"ok": True, "result": result}
    except BaseException as e:
        reply = {"ok": False, "error": str(e), "traceback": traceback.format_exc()}
    sys.stdout.write("\n" + json.dumps(reply) + "\n")


if __name__ == "__main__":
    main()
