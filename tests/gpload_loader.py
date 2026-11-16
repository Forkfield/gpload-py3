"""Load script/gpload.py for unit tests before and after the Python 3 migration.

While the source still contains Python 2 syntax it is converted in memory with
lib2to3. The conversion is only a test helper; after step 1.7 the module is
compiled directly.
"""

import sys
import types
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "gpload.py"
FAKE_PG = ROOT / "tests" / "fake_pg"
FAKE_PSYCOPG2 = ROOT / "tests" / "fake_psycopg2"


def _converted_source(source):
    source = source.replace('quote("\\N")', 'quote(r"\\N")')
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        from lib2to3.refactor import RefactoringTool, get_fixers_from_package

        tool = RefactoringTool(get_fixers_from_package("lib2to3.fixes"))
        tree = tool.refactor_string(source, str(SCRIPT))
    return str(tree)


def load_gpload():
    source = SCRIPT.read_text(encoding="utf-8")
    try:
        code = compile(source, str(SCRIPT), "exec")
    except SyntaxError:
        code = compile(_converted_source(source), str(SCRIPT), "exec")

    fake_pg = str(FAKE_PG / "pygresql")
    if fake_pg not in sys.path:
        sys.path.insert(0, fake_pg)
    fake_psycopg2 = str(FAKE_PSYCOPG2)
    if fake_psycopg2 not in sys.path:
        sys.path.insert(0, fake_psycopg2)

    module = types.ModuleType("gpload_under_test")
    module.__file__ = str(SCRIPT)
    module.__dict__["__name__"] = "gpload_under_test"
    exec(code, module.__dict__)
    return module
