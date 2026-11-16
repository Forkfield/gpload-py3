"""Minimal PyGreSQL stand-in used by the gpload baseline harness.

The fake never talks to a database. It answers the catalog queries gpload
issues from a JSON description and records every SQL statement it receives.
"""

import json
import os
import sys


def _tests_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _catalog_path():
    return os.environ.get(
        "FAKE_PG_CATALOG",
        os.path.join(_tests_dir(), "fixtures", "catalog.json"),
    )


def _load_catalog():
    with open(_catalog_path(), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _sql_text(sql):
    if isinstance(sql, (bytes, bytearray)):
        return sql.decode("utf-8")
    return str(sql)


def _record(sql):
    log_path = os.environ.get("FAKE_PG_QUERY_LOG")
    if not log_path:
        return
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"sql": _sql_text(sql)}, sort_keys=True) + "\n")


class Result:
    def __init__(self, rows):
        self.rows = rows

    def getresult(self):
        return self.rows

    def dictresult(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


def _metadata_rows(catalog):
    legacy_has_sequence = os.environ.get("FAKE_PG_HAS_SEQUENCE_STYLE", "legacy") == "legacy"
    rows = []
    for column in catalog["columns"]:
        has_sequence = column.get("has_sequence", False)
        if legacy_has_sequence:
            has_sequence = "t" if has_sequence else "f"
        rows.append(
            {
                "table_schema": catalog.get("schema", "public"),
                "table_name": catalog.get("table_name", "load_test"),
                "column_name": column["name"],
                "ordinal_position": len(rows) + 1,
                "data_type": column["type"],
                "is_updatable": True,
                "has_sequence": has_sequence,
            }
        )
    return rows


def escape_string(value):
    text = _sql_text(value)
    return text.replace("\\", "\\\\").replace("'", "''")


class DB:
    def __init__(self, dbname=None, host=None, port=None, user=None, passwd=None):
        self.dbname = dbname
        self.host = host
        self.port = port
        self.user = user
        self.passwd = passwd
        self._catalog = _load_catalog()

    def close(self):
        return None

    def notices(self):
        return list(self._catalog.get("notices", []))

    def query(self, sql):
        _record(sql)
        text = " ".join(_sql_text(sql).split())
        low = text.lower()

        if os.environ.get("FAKE_PG_FAIL_INSERT") and low.startswith("insert into"):
            raise RuntimeError("simulated insert failure")

        if low.startswith("select n.nspname"):
            return Result([[self._catalog.get("schema", "public")]])

        if "from pg_catalog.pg_class c join" in low and "has_sequence" in low:
            return Result(_metadata_rows(self._catalog))

        if low.startswith("select nt.nspname"):
            return Result(_metadata_rows(self._catalog))

        if low.startswith("select 1 from pg_class c, pg_namespace n"):
            return Result([[1]])

        if "gp_distribution_policy" in low and low.startswith("select attname from pg_catalog.pg_attribute"):
            return Result([[self._catalog.get("dist_key_column", "distkey")]])

        if "gp_distribution_policy" in low and "select attname" in low:
            return Result([[name] for name in self._catalog.get("dist_key", [])])

        if low.startswith("select attname from pg_catalog.pg_attribute") and "pg_exttable" in low:
            return Result([[name] for name in self._catalog.get("pg_exttable_columns", ["urilocation", "logerrors"])])

        if "ext_gpload_reusable_" in low and "pg_exttable" in low:
            return Result([[name] for name in self._catalog.get("reuse_external_tables", [])])

        if "temp_gpload_reusable_" in low:
            return Result([])

        if "staging_gpload_reusable_" in low:
            return Result([[name] for name in self._catalog.get("reuse_staging_tables", [])])

        if "::regclass::oid" in low:
            return Result([[self._catalog.get("table_oid", 12345)]])

        if low.startswith("select count(*) from gp_read_error_log"):
            return Result([[self._catalog.get("error_count", 0)]])

        if low.startswith("select cmdtime, count(*) from gp_read_error_log"):
            return Result(
                [[self._catalog.get("cmdtime", "2026-01-01 00:00:00"), self._catalog.get("error_count", 0)]]
            )

        if low.startswith("select filename, linenum from gp_read_error_log"):
            rows = self._catalog.get("error_rows", [])
            return Result([rows[0] if rows else ["gpfdist://gpload-test/error.csv", 1]])

        if low.startswith("select * from pg_class where relname like 'temp_gpload_reusable_"):
            return Result([])

        return Result([])


if __name__ == "__main__":
    catalog = _load_catalog()
    print(json.dumps({"catalog": catalog, "python": sys.version}))
