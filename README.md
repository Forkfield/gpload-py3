# gpload-py3

Python 3 port of the Greenplum `gpload` utility. It loads CSV/text files
into Greenplum through `gpfdist`, supporting `insert`, `update` and `merge`
modes, reusable staging/external tables, `LOG_ERRORS`, transforms and SSL.

The code was migrated from the original Python 2 script and validated against
a live Greenplum 6.25.3 cluster.

## Repository layout

```
script/gpload.py        the loader
script/load.sh          batch launcher (scans directories, renders YAML, runs gpload.py)
script/gpload.yaml.ori  control-file template used by load.sh
gpload-test/p1_matrix.sh  regression matrix for Greenplum 6 (22 scenarios)
tests/                  unit tests, golden SQL baselines, fake pg/gpfdist
requirements.txt        runtime dependencies
requirements-dev.txt    test dependencies (pytest)
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

## Batch loading with `load.sh`

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
