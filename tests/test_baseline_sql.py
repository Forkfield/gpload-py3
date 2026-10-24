from pathlib import Path

import run_baseline


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "baseline"


def _expected(name):
    return (BASELINE / (name + ".sql.txt")).read_text(encoding="utf-8")


def _render(statements):
    return "".join(statement + "\n" for statement in statements)


def test_golden_sql_for_all_cases():
    for name, fixture, extra_args in run_baseline.CASES:
        completed, statements = run_baseline.run_case(
            str(ROOT), name, fixture, extra_args, write_output=False
        )

        assert completed.returncode == 0, (name, completed.stderr)
        assert _render(statements) == _expected(name), name


def test_golden_sql_with_boolean_has_sequence(monkeypatch):
    monkeypatch.setenv("FAKE_PG_HAS_SEQUENCE_STYLE", "bool")
    name, fixture, extra_args = run_baseline.CASES[0]

    completed, statements = run_baseline.run_case(
        str(ROOT), name, fixture, extra_args, write_output=False
    )

    assert completed.returncode == 0, completed.stderr
    assert _render(statements) == _expected(name)


def test_log_errors_exits_1(monkeypatch):
    monkeypatch.setenv(
        "FAKE_PG_CATALOG", str(ROOT / "tests" / "fixtures" / "catalog_errors.json")
    )
    name, fixture, extra_args = next(
        case for case in run_baseline.CASES if case[0] == "log_errors"
    )

    completed, statements = run_baseline.run_case(
        str(ROOT), name, fixture, extra_args, write_output=False
    )

    assert completed.returncode == 1, completed.stderr
    assert any("gp_read_error_log" in statement for statement in statements)


def test_insert_failure_exits_2_and_cleans_up(monkeypatch):
    monkeypatch.setenv("FAKE_PG_FAIL_INSERT", "1")
    name, fixture, extra_args = run_baseline.CASES[0]

    completed, statements = run_baseline.run_case(
        str(ROOT), name, fixture, extra_args, write_output=False
    )

    assert completed.returncode == 2
    assert any(statement.startswith("drop external table") for statement in statements)
