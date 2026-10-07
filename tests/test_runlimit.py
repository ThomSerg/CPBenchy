import subprocess
import sys
import time
import uuid

import pytest

from cpbenchy.runlimit import run, start
from cpbenchy.runlimit._child import normalize, parse_runexec_output, run_cli

PY = sys.executable

# Most of these start real runs, so they need working runexec.
pytestmark = pytest.mark.runexec


def test_parse_runexec_output():
    raw = parse_runexec_output(
        "starttime=2026-09-29T10:00:00\nreturnvalue=0\nwalltime=1.5s\ncputime=1.2s\nmemory=1024B\n"
        "terminationreason=walltime\nexitsignal=9\n"
    )
    assert raw["walltime"] == 1.5
    assert raw["cputime"] == 1.2
    assert raw["memory"] == 1024
    assert raw["exitcode"] == {"code": 0, "signal": 9}
    out = normalize(raw, "cli")
    assert out["terminationreason"] == "walltime"
    assert out["exitcode"] == {"code": 0, "signal": 9}


def test_output_and_exit_code(tmp_path):
    out = tmp_path / "out.log"
    res = run([PY, "-c", "print('hello'); raise SystemExit(3)"], output_file=out, walltime=30)
    assert res["terminationreason"] is None
    assert res["exitcode"]["code"] == 3
    assert "hello" in out.read_text()
    assert res["walltime"] > 0


def test_walltime_limit(tmp_path):
    res = run([PY, "-c", "import time; time.sleep(30)"], output_file=tmp_path / "out.log", walltime=2)
    assert res["terminationreason"] == "walltime"
    assert res["walltime"] < 10


def test_memory_limit(tmp_path):
    res = run(
        [PY, "-c", "x = bytearray(1024 * 1024 * 1024); import time; time.sleep(5)"],
        output_file=tmp_path / "out.log",
        walltime=30,
        memlimit_mib=200,
    )
    assert res["terminationreason"] == "memory"


def test_env_is_passed(tmp_path):
    out = tmp_path / "out.log"
    run([PY, "-c", "import os; print(os.environ['RUNLIMIT_TEST'])"], output_file=out, env={"RUNLIMIT_TEST": "xyz"})
    assert "xyz" in out.read_text()


def test_container_has_no_network(tmp_path):
    out = tmp_path / "out.log"
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3); print('NET_OK')\n"
        "except OSError:\n"
        "    print('NET_BLOCKED')\n"
    )
    run([PY, "-c", code], output_file=out, walltime=30, container=True)
    assert "NET_BLOCKED" in out.read_text()


def test_container_can_only_write_to_writable_dirs(tmp_path):
    keep, other = tmp_path / "keep", tmp_path / "other"
    keep.mkdir()
    other.mkdir()
    code = (
        f"open('{keep}/a.txt', 'w').write('x')\n"
        "try:\n"
        f"    open('{other}/b.txt', 'w').write('x'); print('OTHER_WRITTEN')\n"
        "except OSError:\n"
        "    print('OTHER_BLOCKED')\n"
    )
    out = tmp_path / "out.log"
    res = run([PY, "-c", code], output_file=out, walltime=30, container=True, writable_dirs=[keep])
    assert res["exitcode"]["code"] == 0
    assert (keep / "a.txt").exists()
    assert "OTHER_BLOCKED" in out.read_text()
    assert not (other / "b.txt").exists()


def cli_request(tmp_path, cmd, **overrides):
    req = {
        "cmd": cmd,
        "output_file": str(tmp_path / "out.log"),
        "walltime": 10,
        "memlimit_mib": 500,
        "cores": None,
        "memory_nodes": None,
        "container": False,
        "writable_dirs": [],
        "workdir": None,
        "env": {},
    }
    req.update(overrides)
    return req


def test_cli_fallback(tmp_path):
    res = run_cli(cli_request(tmp_path, [PY, "-c", "import time; print('cli'); time.sleep(30)"], walltime=2))
    assert res["mode"] == "cli"
    assert res["terminationreason"] == "walltime"
    assert "cli" in (tmp_path / "out.log").read_text()


def test_cli_fallback_container(tmp_path):
    keep = tmp_path / "keep"
    keep.mkdir()
    code = f"open('{keep}/a.txt', 'w').write('x')"
    res = run_cli(cli_request(tmp_path, [PY, "-c", code], container=True, writable_dirs=[str(keep)]))
    assert res["exitcode"]["code"] == 0
    assert (keep / "a.txt").exists()


def test_cores_and_memory_nodes(tmp_path):
    import os

    cpus = sorted(os.sched_getaffinity(0))[:2]
    out = tmp_path / "out.log"
    code = "import os; print('AFFINITY', sorted(os.sched_getaffinity(0)))"
    res = run([PY, "-c", code], output_file=out, walltime=30, cores=cpus, memory_nodes=[0])
    assert res["exitcode"]["code"] == 0
    assert f"AFFINITY {cpus}" in out.read_text()


def test_cli_fallback_cores_and_memory_nodes(tmp_path):
    import os

    cpus = sorted(os.sched_getaffinity(0))[:1]
    code = "import os; print('AFFINITY', sorted(os.sched_getaffinity(0)))"
    res = run_cli(cli_request(tmp_path, [PY, "-c", code], cores=cpus, memory_nodes=[0]))
    assert res["exitcode"]["code"] == 0
    assert f"AFFINITY {cpus}" in (tmp_path / "out.log").read_text()


@pytest.mark.parametrize("delay", [0.5, 2])
def test_terminate_stops_the_run_and_its_process(tmp_path, delay):
    # a python child, so the RunExecutor is busy with more than a bare wait (it used to deadlock)
    marker = f"runlimit-test-{uuid.uuid4().hex}"
    script = "import time\nfor _ in range(600): time.sleep(0.1)"
    handle = start([PY, "-c", script, marker], output_file=tmp_path / "out.log", walltime=60)
    time.sleep(delay)
    handle.terminate()
    res = handle.result()
    assert res["terminationreason"] == "killed"
    assert res["walltime"] < 30
    assert subprocess.run(["pgrep", "-f", marker]).returncode == 1  # no process left behind


BUSY = "while True: pass"
ON_SIGTERM = (
    "import signal, sys\n"
    "signal.signal(signal.SIGTERM, lambda *_: (print('got SIGTERM', flush=True), sys.exit(0)))\n"
    "while True: pass"
)


def test_cputime_limit(tmp_path):
    res = run([PY, "-c", BUSY], output_file=tmp_path / "out.log", walltime=30, cputime=2)
    assert res["terminationreason"] == "cputime"
    assert 1.5 < res["cputime"] < 10


def test_soft_cputime_limit_sends_sigterm(tmp_path):
    out = tmp_path / "out.log"
    res = run([PY, "-c", ON_SIGTERM], output_file=out, walltime=30, cputime=10, soft_cputime=2)
    assert res["terminationreason"] == "cputime-soft"
    assert res["exitcode"]["code"] == 0
    assert "got SIGTERM" in out.read_text()


def test_cli_fallback_cputime_limits(tmp_path):
    res = run_cli(cli_request(tmp_path, [PY, "-c", ON_SIGTERM], walltime=30, cputime=10, soft_cputime=2))
    assert res["terminationreason"] == "cputime-soft"
    assert "got SIGTERM" in (tmp_path / "out.log").read_text()
