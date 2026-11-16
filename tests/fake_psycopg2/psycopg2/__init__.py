"""Minimal psycopg2 stand-in for the gpload baseline harness.

It delegates SQL handling to the existing fake PyGreSQL module and exposes
the small DB-API surface used by gpload's psycopg2 adapter.
"""

import pg as _fake_pg


def connect(**kwargs):
    return Connection(
        _fake_pg.DB(
            dbname=kwargs.get("dbname"),
            host=kwargs.get("host"),
            port=kwargs.get("port"),
            user=kwargs.get("user"),
            passwd=kwargs.get("password"),
        )
    )


class Connection:
    def __init__(self, db):
        self._db = db
        self.autocommit = False

    @property
    def notices(self):
        return self._db.notices()

    def cursor(self):
        return Cursor(self._db)

    def close(self):
        self._db.close()


class Cursor:
    def __init__(self, db):
        self._db = db
        self.description = None
        self.rowcount = -1
        self._rows = []

    def execute(self, sql):
        result = self._db.query(sql)
        raw_rows = result.getresult()
        if raw_rows and isinstance(raw_rows[0], dict):
            columns = list(raw_rows[0].keys())
            self.description = [(name,) for name in columns]
            self._rows = [tuple(row[name] for name in columns) for row in raw_rows]
        elif raw_rows:
            width = len(raw_rows[0])
            self.description = [("column%d" % (i + 1),) for i in range(width)]
            self._rows = raw_rows
        else:
            self.description = None
            self._rows = []
        self.rowcount = len(self._rows)

    def fetchall(self):
        return self._rows

    def close(self):
        return None
