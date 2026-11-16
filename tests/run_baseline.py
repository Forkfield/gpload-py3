#!/usr/bin/env python3
"""Capture the SQL statements gpload sends to the database for fixture configs.

The harness is intentionally driver-free: tests/fake_pg answers catalog
queries and appends every statement to FAKE_PG_QUERY_LOG. Captured output is
normalized (random UUIDs become <UUID>) and written to tests/baseline/.

The original gpload.py is Python 2, so this script is expected to fail until
the syntax migration is complete. That is the baseline for step 0.2.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

UUID_RE = re.compile(r"[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{4}_[0-9a-f]{12}")


CASES = [
    ("insert_text", "tests/fixtures/insert_text.yaml", []),
    ("insert_csv", "tests/fixtures/insert_csv.yaml", []),
    ("columns_mapping", "tests/fixtures/columns_mapping.yaml", []),
    ("update", "tests/fixtures/update.yaml", []),
    ("merge", "tests/fixtures/merge.yaml", []),
    ("reuse_tables", "tests/fixtures/reuse_tables.yaml", []),
    ("ssl", "tests/fixtures/ssl.yaml", []),
    ("sql_before_after", "tests/fixtures/sql_before_after.yaml", []),
    ("delimiter_escape", "tests/fixtures/delimiter_escape.yaml", []),
    ("log_errors", "tests/fixtures/log_errors.yaml", []),
    ("dry_run", "tests/fixtures/dry_run.yaml", ["-D"]),
]


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalize(sql):
    return UUID_RE.sub("<UUID>", sql)


def run_case(root, name, fixture, extra_args, write_output=True):
    case_dir = tempfile.mkdtemp(prefix="gpload-baseline-%s-" % name)
    query_log = os.path.join(case_dir, "queries.jsonl")
    home_dir = os.path.join(case_dir, "home")
    os.makedirs(home_dir)

    env = os.environ.copy()
    env.update(
        {
            "HOME": home_dir,
            "PGPASSWORD": "fake-password",
            "PYTHONPATH": os.pathsep.join(
                [
                    os.path.join(root, "tests", "fake_psycopg2"),
                    os.path.join(root, "tests", "fake_pg", "pygresql"),
                    os.path.join(root, "tests", "fake_pg"),
                    env.get("PYTHONPATH", ""),
                ]
            ).rstrip(os.pathsep),
            "GPHOME": os.path.join(root, "tests", "fake_greenplum"),
            "PATH": os.pathsep.join(
                [os.path.join(root, "tests", "fake_bin"), env.get("PATH", "")]
            ),
            "FAKE_PG_QUERY_LOG": query_log,
            "FAKE_PG_CATALOG": env.get(
                "FAKE_PG_CATALOG",
                os.path.join(root, "tests", "fixtures", "catalog.json"),
            ),
            "FAKE_PG_HAS_SEQUENCE_STYLE": env.get(
                "FAKE_PG_HAS_SEQUENCE_STYLE", "legacy"
            ),
        }
    )

    command = [
        sys.executable,
        os.path.join(root, "script", "gpload.py"),
        "-f",
        fixture,
        "-l",
        os.path.join(case_dir, "gpload.log"),
        "-U",
        "testuser",
        "-d",
        "testdb",
        "-h",
        "localhost",
        "-p",
        "5432",
    ] + extra_args

    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    statements = []
    if os.path.exists(query_log):
        with open(query_log, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    statements.append(normalize(json.loads(line)["sql"]))

    output_dir = os.path.join(root, "tests", "baseline")
    if write_output:
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, name + ".sql.txt")
        with open(output_path, "w", encoding="utf-8") as handle:
            for statement in statements:
                handle.write(statement + "\n")

    shutil.rmtree(case_dir, ignore_errors=True)
    return completed, statements


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="run only the given case")
    args = parser.parse_args()

    root = repo_root()
    selected = [case for case in CASES if not args.case or case[0] in args.case]
    failures = 0

    for name, fixture, extra_args in selected:
        completed, statements = run_case(root, name, fixture, extra_args)
        print(
            "%-18s exit=%d sql=%d"
            % (name, completed.returncode, len(statements))
        )
        if completed.returncode != 0:
            failures += 1
            tail = (completed.stderr or completed.stdout).strip().splitlines()
            for line in tail[-5:]:
                print("  " + line)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
