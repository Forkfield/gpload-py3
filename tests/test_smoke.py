import os
import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "gpload.py"


def test_py_compile(tmp_path):
    py_compile.compile(str(SCRIPT), cfile=str(tmp_path / "gpload.pyc"), doraise=True)


def test_help():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "tests" / "fake_pg"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "-?"],
        cwd=str(ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.returncode == 2
    assert "gpload [options] -f configuration file" in completed.stdout
