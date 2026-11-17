import os
import subprocess
import sys
from pathlib import Path

import pytest

from gpload_loader import load_gpload

ROOT = Path(__file__).resolve().parents[1]
FAKE_PYTHONPATH = os.pathsep.join([
    str(ROOT / "tests" / "fake_psycopg2"),
    str(ROOT / "tests" / "fake_pg" / "pygresql"),
])


def test_import_does_not_require_db_driver():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import gpload; print(gpload.Gpload.__name__)"
        % str(ROOT / "script")
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "Gpload"


def test_result_flags():
    gp = load_gpload()
    assert gp.GploadResult(0).ok
    assert not gp.GploadResult(0).has_warnings
    assert not gp.GploadResult(0).failed

    warned = gp.GploadResult(1)
    assert not warned.ok
    assert warned.has_warnings
    assert not warned.failed

    failed = gp.GploadResult(2)
    assert not failed.ok
    assert not failed.has_warnings
    assert failed.failed


def test_raise_for_status():
    gp = load_gpload()
    result = gp.GploadResult(2, stderr="boom")

    with pytest.raises(gp.GploadError) as exc:
        result.raise_for_status()

    assert exc.value.result is result
    assert "exit code 2" in str(exc.value)
    assert gp.GploadResult(0).raise_for_status().ok


def test_build_command():
    gp = load_gpload()
    api = gp.Gpload(script="/opt/gpload.py", python="/usr/bin/python3")

    cmd = api.build_command(
        "/tmp/config.yaml",
        log="/tmp/gpload.log",
        host="db.example.com",
        port=6432,
        user="gpadmin",
        database="testdb",
        dry_run=True,
        quiet=True,
        no_auto_trans=True,
        gpfdist_timeout=120,
        extra_args=["-W"],
    )

    assert cmd == [
        "/usr/bin/python3", "/opt/gpload.py", "-f", "/tmp/config.yaml",
        "-h", "db.example.com", "-p", "6432", "-U", "gpadmin",
        "-d", "testdb", "-l", "/tmp/gpload.log",
        "-D", "-q", "--no_auto_trans", "--gpfdist_timeout", "120", "-W",
    ]


def test_load_returns_structured_failure(tmp_path):
    gp = load_gpload()
    config = tmp_path / "bad.yaml"
    config.write_text("VERSION: 1.0.0.1\n", encoding="utf-8")

    result = gp.Gpload().load(str(config), quiet=True,
                              env={"PYTHONPATH": FAKE_PYTHONPATH})

    assert result.returncode == 2
    assert result.failed
    assert "gpload:output" in result.stdout
    assert result.command[0] == sys.executable
    assert result.command[1] == str(ROOT / "script" / "gpload.py")
    assert result.log_file is None


def test_run_gpload_shortcut(tmp_path):
    gp = load_gpload()
    config = tmp_path / "bad.yaml"
    config.write_text("VERSION: 1.0.0.1\n", encoding="utf-8")

    result = gp.run_gpload(str(config), quiet=True,
                           env={"PYTHONPATH": FAKE_PYTHONPATH})

    assert isinstance(result, gp.GploadResult)
    assert result.returncode == 2


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_load_kills_child_on_keyboard_interrupt(gpload, monkeypatch):
    killed = []

    class FakeProc:
        pid = 4321
        returncode = -9

        def __init__(self, *args, **kwargs):
            pass

        def communicate(self, timeout=None):
            if timeout is not None:
                raise KeyboardInterrupt
            return "", ""

    monkeypatch.setattr(gpload.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(
        gpload.os, "killpg", lambda pid, sig: killed.append((pid, sig))
    )

    with pytest.raises(KeyboardInterrupt):
        gpload.Gpload(script="/tmp/gpload.py").load("config.yaml")

    assert killed == [(4321, gpload.signal.SIGKILL)]


def test_load_timeout_kills_child(tmp_path):
    gp = load_gpload()
    slow_script = tmp_path / "slow.py"
    slow_script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")

    result = gp.Gpload(script=str(slow_script), timeout=1).load("ignored.yaml")

    assert result.returncode == 124
    assert result.failed
