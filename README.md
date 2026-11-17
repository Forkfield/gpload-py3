# gpload-py3

Python 3 port of the Greenplum `gpload` utility. It loads CSV/text files
into Greenplum through `gpfdist`, supporting `insert`, `update` and `merge`
modes, reusable staging/external tables, `LOG_ERRORS`, transforms and SSL.

The code was migrated from the original Python 2 script and validated against
a live Greenplum 6.25.3 cluster.

## Origin and attribution

This project is a Python 3 port of the `gpload` utility shipped with
Greenplum Database. It is not an independent implementation: the original
`gpload` is copyright Greenplum, Inc. and is distributed as part of Greenplum
Database under the Apache License 2.0.

The Python 3 port, the programmatic API and the tests are maintained by
Vitchenko Kirill and are distributed under the same license. See `NOTICE` for
the attribution text and `LICENSE` for the full license.

## Repository layout

```
script/gpload.py        the loader (CLI and Python API, including GploadBatch)
script/load.sh          legacy batch launcher (kept for gpstall)
script/gpload.yaml.ori  control-file template used by GploadBatch and load.sh
gpload-test/p1_matrix.sh  regression matrix for Greenplum 6 (22 scenarios)
tests/                  unit tests, golden SQL baselines, fake pg/gpfdist
pyproject.toml          package metadata and build configuration
LICENSE                 Apache License 2.0
NOTICE                  attribution of the original gpload
requirements.txt        runtime dependencies
requirements-dev.txt    test dependencies (pytest)
```

## Installation

From PyPI:

```bash
pip install gpload-py3
```

The distribution name is `gpload-py3`; the import name is `gpload`:

```python
from gpload import Gpload, GploadBatch
```

The package installs the `gpload-py3` console command:

```bash
gpload-py3 -f config.yaml
```

or:

```bash
python -m gpload -f config.yaml
```

For development from a checkout:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[postgres]'
```

## Requirements

* Python 3.10+ (validated on CPython 3.10.15).
* `PyYAML` and a PostgreSQL driver. `requirements.txt` pins the versions used
  for validation (`PyYAML==6.0.3`, `psycopg2-binary==2.9.13`):

  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  ```

  On a Greenplum host the distro `psycopg2` is preferred; `psycopg2-binary`
  is only a convenience for local virtualenvs. If `psycopg2` is missing,
  `gpload.py` automatically falls back to `pygresql.pg` (shipped with
  Greenplum) or a plain `pg` module.
* `gpfdist` from the Greenplum installation.
* Development/tests: `.venv/bin/pip install -r requirements-dev.txt`.

## Usage

From an installed package:

```bash
gpload-py3 -f gpload.yaml [options]
# or
python -m gpload -f gpload.yaml [options]
```

From the repository without installing:

```bash
python3 script/gpload.py -f gpload.yaml [options]
```

Options:

```
-h hostname     host to connect to
-p port         port to connect to
-U username     user to connect as
-d database     database to connect to
-W              force password authentication
-q              quiet mode
-D              do not actually load data (generate SQL only)
-v              verbose
-V              very verbose
-l logfile      log output to logfile
--no_auto_trans do not wrap gpload in transaction
--gpfdist_timeout timeout
--version       print version number and exit
--help          print this help and exit
-?              help
```

Minimal control file:

```yaml
VERSION: 1.0.0.1
DATABASE: mydb
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /data/input.csv
    - FORMAT: csv
    - DELIMITER: ','
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.my_table
    - MODE: insert
```

## Programmatic interface

`script/gpload.py` can be imported and called from Python code. The module is
import-safe (`if __name__ == '__main__'` guard), but the API runs every load
in a child process: gpload calls `sys.exit()` on errors and replaces process
signal handlers, so calling it in-process would affect the host application.

```python
from gpload import Gpload, run_gpload   # after pip install gpload-py3

gpload = Gpload()                        # Gpload(python=..., timeout=900)
result = gpload.load(
    "/path/to/config.yaml",
    log="/var/log/gpload.log",
    host="127.0.0.1",
    port=5432,
    user="gpadmin",
    database="mydb",
    quiet=True,
)

result.returncode   # 0 success, 1 warnings, 2 failure, 124 timeout
result.ok
result.has_warnings
result.failed
result.stdout       # captured child stdout
result.stderr
result.log_file
result.command      # the command line that was executed
result.raise_for_status()   # raises GploadError when returncode != 0
```

If you use the standalone `script/gpload.py` without installing the package,
add its directory to `sys.path` first, or load it with `importlib.util`.

`run_gpload(config, **kwargs)` is a shortcut for `Gpload().load(...)`.
`Gpload.build_command(...)` returns the command line without running it.
To load a whole `<database>/<table>/*.csv` tree, use `GploadBatch`
(see below).

Importing `gpload` does not require a database driver: `psycopg2`/PyGreSQL is
imported when a load actually runs (or when `db_connect()` is called). The
calling process therefore only needs the standard library and `PyYAML`.

The child inherits the environment; `env={...}` merges extra variables and
`cwd=...` sets the working directory (use absolute `FILE:` paths in YAML).
On timeout the whole child process group is killed, including `gpfdist`.
Interrupting the caller (`Ctrl-C`) kills it the same way instead of leaving
gpload running in the background.

## Batch loading from Python

`GploadBatch` is the programmatic equivalent of `load.sh`. It scans
`<data_dir>/<database>/<table>/*.csv`, renders the control file for every
table (using the CSV header for `HEADER`/`COLUMNS`) and loads each table in a
child process. No `load.sh` command line has to be assembled by the caller.

```python
from gpload import GploadBatch

batch = GploadBatch(
    "/opt/gpstall/data",             # <database>/<table>/*.csv
    log_dir="/var/log/gpstall",      # default: <data_dir>/../log
    config_template="/opt/gpstall/bin/gpload.yaml.ori",
    user="gpadmin",
    password="secret",               # or PGPASSWORD from the environment
    host="127.0.0.1",
    port=5432,
    gpfdist_host="127.0.0.1",
    port_range="[8081,8082]",
    error_limit=50000,
    timeout=600,                     # per table
)

result = batch.load(on_table=lambda table: print(table.table, table.returncode))

result.returncode            # 0 all clean, 1 rejected rows, 2 failure
result.ok
result.has_warnings
result.failed
result.loaded_tables
result.warning_tables
result.failed_tables
result.raise_for_status()    # GploadError when returncode != 0
```

Defaults: `log_dir` is `<data_dir>/../log`, `config_template` is resolved
next to `gpload.py` or from the installed
`share/gpload-py3/gpload.yaml.ori`, `user` comes from `PGUSER`, `password`
from `PGPASSWORD`, `host` from `PGHOST` (else `127.0.0.1`), `port` from
`PGPORT` (else `5432`), `gpfdist_host` is the database host, `port_range` is
`[8081,8082]`, `error_limit` is `50000`, `timeout` is 600 seconds per table.

Each table result describes what happened:

```python
table = result.tables[0]
table.database
table.table
table.files                 # every CSV found in the table directory
table.loaded_files          # deleted after a clean load
table.failed_files          # moved to <table>/failed/
table.error_file            # from "error file:" in the gpload output
table.error_line            # from "error line:"
table.gpload_result         # GploadResult of the child process
table.config_text           # rendered control file (for debugging)
table.message
```

File lifecycle matches `load.sh`:

* exit code 0 - all CSV files of the table are deleted;
* exit code 1 or 2 - the failing CSV is moved to `<table>/failed/`, with the
  error line appended when known (`file.csv_3`); the path is written to
  `<log_dir>/latest_failed_file`;
* a timeout (exit code 124) is reported as a failure;
* tables with an empty CSV header are reported as failed and their files are
  left in place.

The lower-level pieces are public as well:

```python
batch.scan()                    # [(database, table, [files]), ...]
batch.table_files(table_dir)    # CSV files of one directory
batch.render_config(db, table, files)
batch.load_table(db, table)     # load a single table
batch.load_dir()                # alias for batch.load()
run_gpload_batch(data_dir, ...) # shortcut for GploadBatch(...).load()
```

`env={...}` is not needed: `PGPASSWORD` and the `LD_LIBRARY_PATH` cleanup
that `load.sh` performs are applied automatically to the child environment.
The child gpload processes still need `psycopg2`/PyGreSQL and `GPHOME` (or
`GPHOME_LOADERS`), exactly like the command-line tool; only the calling
process is driver-free. Concurrent batches should use different `log_dir`
directories, because `gpload.log` and `latest_failed_file` live there.

## Batch loading with `load.sh`

`GploadBatch` above implements the same behavior without a shell script. The
section below documents the legacy `load.sh` entry point used by `gpstall`.

```bash
./script/load.sh <data_dir> <log_dir> <config_template> <user> <password> \
    <host> <port> <gpfdist_host> <port_range> <error_limit> <suffix>
```

`load.sh` scans `<data_dir>/<database>/<table>/*.csv`, renders a control file
from the template by substituting `{DATABASE}`, `{TABLE}`, `{FILE}`,
`{HEADER}`, `{GPUSER}`, `{GPHOST}`, `{GPPORT}`, `{GPDHOST}`,
`{GPDPORT_RANGE}` and `{ERROR_LIMIT}`, then runs the local `gpload.py` through
`python3` (falling back to `gpload` from `PATH` if the script is absent).

Exit codes:

* `0` — success; loaded CSV files are removed;
* `1` — load succeeded with rejected rows ("succeeded with warnings");
* `2` — load failed.

On exit code 1 or 2 the affected CSV files are moved to `failed/` (with the
error line appended to the name when known) so a rerun cannot duplicate the
already-loaded rows. The failing file is also recorded in
`<log_dir>/latest_failed_file`.

`load.sh` removes `$GPHOME/*` entries from `LD_LIBRARY_PATH` for the Python
process because the system `psycopg2` cannot load the older Greenplum `libpq`.
`gpfdist` is started by `gpload.py` in its own shell, which sources the
Greenplum environment separately.

## Greenplum 6 compatibility fixes (over the Python 2 original)

Each fix was verified on Greenplum 6.25.3:

* **Catalog auto-detection**: `gp_distribution_policy` `attrnums`/`distkey`
  (renamed in GP 6.25+) and `pg_exttable` `location`/`fmterrtbl` vs
  `urilocation`/`logerrors` (GP 6). Without this, UPDATE mode and
  `REUSE_TABLES` crash on GP 6.
* **`gp_read_error_log` file names** are parsed in the GP 6 format
  (`gpfdist://host:port/path/file.csv [path/file.csv]`).
* **Bad rows without `LOG_ERRORS`** are counted from the
  `NOTICE: found N data formatting errors` message. On GP 6 the error log
  stays empty in that mode; the Python 2 original silently reported 0 rows
  and exited 0.
* **COPY option values** (`NULL_AS`, `ESCAPE`, `DELIMITER`, `QUOTE`) are
  emitted as `E'...'` SQL literals. The Python 2 original doubled
  backslashes, which broke text-format loads with the default
  `NULL_AS`/`ESCAPE` and made `\N` in CSV loads a literal value instead of
  NULL.
* **Clean reuse load**: an empty `gp_read_error_log` result on a reused
  external table no longer raises `IndexError` in `count_errors`.

## Validation

* **Unit tests** — 27 tests covering SQL generation, GP 6 error-log handling,
  fake `psycopg2`/PyGreSQL drivers, fake gpfdist and pure functions:

  ```bash
  .venv/bin/python -m pytest -q
  ```

* **P1 regression matrix** — 22/22 on Greenplum 6.25.3: text format, serial
  columns, distribution keys, `UPDATE_CONDITION`, merge duplicates and NULL
  keys, `PRELOAD` TRUNCATE/BEFORE/AFTER, `--no_auto_trans`, quoting/encoding,
  `FORCE_NOT_NULL`, table reuse, concurrency, multiple sources, `-W`, `-q`.

  Run it inside the container with the repository mounted at `/work`
  (database `gpload_test`, role `gpadmin`, Greenplum environment available):

  ```bash
  docker exec -u gpadmin -w /work gp6-gpload-test \
      bash /work/gpload-test/p1_matrix.sh
  ```

  The script creates and drops `public.p1_*` tables, keeps temporary data in
  `/tmp/p1` and prints a `RESULT|...` line per scenario plus a pass/fail
  summary. `GPLOAD=/path/to/gpload.py` overrides the script under test.

* **Environment checks** — SSL `gpfdists://`, `TRANSFORM`, FQDN, busy
  gpfdist port, and passwords via YAML / `PGPASSWORD` / `.pgpass` / `-W`.

* **Differential run against the original Python 2 gpload** on the same
  cluster: 16 scenarios — 9 identical (SQL, table state, exit codes),
  7 by-design differences (all places where the Python 2 original is broken
  on GP 6), 0 regressions.

## Known limitations and operational notes

* `INCLUDING_DEFAULTS` is not supported: a dead upstream option, absent from
  the GP 6 docs.
* `NULL` in `MATCH_COLUMNS` never matches: repeated merge loads insert a new
  row instead of updating (standard SQL behavior).
* `ESCAPE: off` is rejected in CSV format.
* `gpfdists://` (SSL) requires `client.crt`, `client.key` and `root.crt` in
  every segment's `<datadir>/gpfdists/` directory — gpload cannot create
  them (certificate verification is configured on the cluster side).
* Only a superuser can create gpfdist external tables.
* `-W` prompts for a password only when none was supplied via YAML,
  `PGPASSWORD` or `.pgpass`; with no TTY and no password gpload exits with
  code 2.
* Several `LOCAL_HOSTNAME` values do not reload the same file: Greenplum
  reads it once.

## Building and publishing

```bash
python3 -m venv .venv-build
. .venv-build/bin/activate
pip install -U build twine

rm -rf dist build
python -m build
python -m twine check dist/*
```

Test the install from a clean environment:

```bash
python3 -m venv /tmp/gpload-test
/tmp/gpload-test/bin/pip install dist/gpload_py3-*.whl
/tmp/gpload-test/bin/python -c "from gpload import Gpload; print(Gpload)"
```

Upload to TestPyPI first, then to PyPI:

```bash
python -m twine upload --repository testpypi dist/*
python -m twine upload dist/*
```

Bump `__version__` in `script/gpload.py` before each upload: `pyproject.toml`
reads it, and PyPI does not allow replacing a version that has already been
published.
