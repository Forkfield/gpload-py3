import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

TEMPLATE = """---
VERSION: 1.0.0.1
DATABASE: {DATABASE}
USER: {GPUSER}
HOST: {GPHOST}
PORT: {GPPORT}
GPLOAD:
   INPUT:
    - SOURCE:
         LOCAL_HOSTNAME:
           - {GPDHOST}
         PORT_RANGE: {GPDPORT_RANGE}
         FILE:{FILE}
    - FORMAT: csv
    - QUOTE: '"'
    {HEADER}
    - ERROR_LIMIT: {ERROR_LIMIT}
   OUTPUT:
    - TABLE: {TABLE}
"""


class FakeLoader:
    """Stand-in for Gpload that returns a prepared result."""

    def __init__(self, module, handler):
        self.module = module
        self.handler = handler
        self.calls = []

    def load(self, config, **kwargs):
        text = Path(config).read_text(encoding="utf-8")
        self.calls.append({"config": config, "text": text, "kwargs": kwargs})
        returncode, stdout = self.handler(text)
        return self.module.GploadResult(returncode, stdout=stdout)


def write_table(root, database, table, files):
    table_dir = Path(root) / database / table
    table_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (table_dir / name).write_text(content, encoding="utf-8")
    return table_dir


def make_batch(gp, tmp_path, **kwargs):
    template = tmp_path / "gpload.yaml.ori"
    template.write_text(TEMPLATE, encoding="utf-8")
    script = tmp_path / "gpload.py"
    script.write_text("# placeholder, replaced by a fake loader\n", encoding="utf-8")

    options = {
        "log_dir": tmp_path / "log",
        "config_template": template,
        "script": script,
        "python": sys.executable,
        "user": "gpadmin",
        "password": "secret",
        "host": "db.example.com",
        "port": 5432,
        "gpfdist_host": "127.0.0.1",
        "port_range": "[8081,8082]",
        "error_limit": 42,
    }
    options.update(kwargs)
    return gp.GploadBatch(tmp_path / "data", **options)


def test_scan_finds_only_tables_with_files(gpload, tmp_path):
    data = tmp_path / "data"
    write_table(data, "db1", "t1", {
        "b.csv": "id,name\n2,b\n",
        "a.csv": "id,name\n1,a\n",
        "notes.txt": "ignored\n",
    })
    write_table(data, "db1", "empty", {"readme.txt": "no csv here\n"})
    write_table(data, "db2", "t2", {"data.csv": "id\n3\n"})
    (data / "README").write_text("not a database\n", encoding="utf-8")

    batch = make_batch(gpload, tmp_path)

    assert batch.scan() == [
        ("db1", "t1", [
            str(data / "db1" / "t1" / "a.csv"),
            str(data / "db1" / "t1" / "b.csv"),
        ]),
        ("db2", "t2", [str(data / "db2" / "t2" / "data.csv")]),
    ]


def test_scan_missing_data_dir(gpload, tmp_path):
    batch = make_batch(gpload, tmp_path)

    with pytest.raises(FileNotFoundError):
        batch.scan()


def test_render_config_substitutes_all_placeholders(gpload, tmp_path):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {
        "a.csv": "id,name,email\n1,a,a@example.com\n",
    })
    batch = make_batch(gpload, tmp_path)

    config = batch.render_config(
        "db1", "t1", [str(table_dir / "a.csv")]
    )

    assert "DATABASE: db1" in config
    assert "USER: gpadmin" in config
    assert "HOST: db.example.com" in config
    assert "PORT: 5432" in config
    assert "           - 127.0.0.1" in config
    assert "PORT_RANGE: [8081,8082]" in config
    assert "- ERROR_LIMIT: 42" in config
    assert "    - TABLE: t1" in config
    assert (
        "         FILE:\n"
        "          - %s/*.csv\n" % table_dir
    ) in config
    assert (
        "    - HEADER: true\n"
        "    - COLUMNS:\n"
        "         - id:\n"
        "         - name:\n"
        "         - email:\n"
    ) in config


def test_render_config_parses_quoted_csv_header(gpload, tmp_path):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {
        "a.csv": '"id","full name"\n1,Alice\n',
    })
    batch = make_batch(gpload, tmp_path)

    config = batch.render_config("db1", "t1", [str(table_dir / "a.csv")])

    assert "         - full name:" in config


def test_real_template_renders_valid_yaml(gpload, tmp_path):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {
        "a.csv": "id,name\n1,Alice\n",
    })
    batch = gpload.GploadBatch(
        data,
        log_dir=tmp_path / "log",
        config_template=ROOT / "script" / "gpload.yaml.ori",
        script=ROOT / "script" / "gpload.py",
        user="gpadmin",
        host="127.0.0.1",
        port=5432,
        gpfdist_host="127.0.0.1",
    )

    parsed = yaml.safe_load(
        batch.render_config("db1", "t1", [str(table_dir / "a.csv")])
    )

    inputs = parsed["GPLOAD"]["INPUT"]
    source = next(item["SOURCE"] for item in inputs if "SOURCE" in item)
    assert source["FILE"] == [str(table_dir / "*.csv")]
    assert {"HEADER": True} in inputs
    columns = next(item["COLUMNS"] for item in inputs if "COLUMNS" in item)
    assert columns == [{"id": None}, {"name": None}]
    assert parsed["GPLOAD"]["OUTPUT"][0]["TABLE"] == "t1"


def test_render_config_rejects_empty_header(gpload, tmp_path):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {"a.csv": ""})
    batch = make_batch(gpload, tmp_path)

    with pytest.raises(ValueError, match="empty CSV header"):
        batch.render_config("db1", "t1", [str(table_dir / "a.csv")])


def test_success_removes_files_and_prepares_environment(
        gpload, tmp_path, monkeypatch):
    monkeypatch.setenv("GPHOME", "/opt/gpdb")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/gpdb/lib:/usr/lib")

    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {
        "a.csv": "id,name\n1,a\n",
        "b.csv": "id,name\n2,b\n",
    })
    batch = make_batch(gpload, tmp_path)
    loader = FakeLoader(gpload, lambda text: (0, ""))
    batch.loader = loader

    result = batch.load()

    assert result.returncode == 0
    assert result.ok
    assert not result.has_warnings
    assert len(result.tables) == 1

    table = result.tables[0]
    assert table.ok
    assert table.database == "db1"
    assert table.table == "t1"
    assert table.loaded_files == [
        str(table_dir / "a.csv"), str(table_dir / "b.csv")
    ]
    assert not (table_dir / "a.csv").exists()
    assert not (table_dir / "b.csv").exists()
    assert not Path(table.config_path).exists()
    assert "DATABASE: db1" in table.config_text

    assert len(loader.calls) == 1
    kwargs = loader.calls[0]["kwargs"]
    assert kwargs["log"] == str(batch.log_file)
    assert kwargs["timeout"] == 600
    assert kwargs["env"]["PGPASSWORD"] == "secret"
    assert "/opt/gpdb/lib" not in kwargs["env"]["LD_LIBRARY_PATH"]
    assert "/usr/lib" in kwargs["env"]["LD_LIBRARY_PATH"]

    assert batch.log_file == str(tmp_path / "log" / "gpload.log")
    assert Path(batch.log_file).read_text(encoding="utf-8") == (
        "------------------------------\n"
    )


def test_warning_quarantines_error_file_with_line(
        gpload, tmp_path, monkeypatch):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {
        "a.csv": "id,name\n1,a\n",
        "b.csv": "id,name\n2,b\n",
    })
    batch = make_batch(gpload, tmp_path)

    def handler(text):
        return 1, (
            "2026-01-01 00:00:00|WARN|error file: a.csv\n"
            "2026-01-01 00:00:00|WARN|error line: 3\n"
        )

    batch.loader = FakeLoader(gpload, handler)

    result = batch.load()

    assert result.returncode == 1
    assert result.has_warnings
    table = result.tables[0]
    assert table.has_warnings
    assert table.error_file == "a.csv"
    assert table.error_line == "3"
    assert table.failed_files == [str(table_dir / "failed" / "a.csv_3")]
    assert not (table_dir / "a.csv").exists()
    assert (table_dir / "failed" / "a.csv_3").exists()
    # load.sh only moves the file named by the error log.
    assert (table_dir / "b.csv").exists()

    latest = Path(batch.latest_failed_file).read_text(encoding="utf-8")
    assert latest == str(table_dir / "failed" / "a.csv_3") + "\n"


def test_error_location_is_read_from_the_current_log_chunk(
        gpload, tmp_path):
    data = tmp_path / "data"
    first_dir = write_table(data, "db1", "t1", {"one.csv": "id\n1\n"})
    second_dir = write_table(data, "db2", "t2", {"two.csv": "id\n2\n"})
    batch = make_batch(gpload, tmp_path)

    class LoggingLoader:
        def load(self, config, **kwargs):
            text = Path(config).read_text(encoding="utf-8")
            name = "one.csv" if "TABLE: t1" in text else "two.csv"
            with open(kwargs["log"], "a", encoding="utf-8") as handle:
                handle.write(
                    "2026-01-01 00:00:00|WARN|error file: %s\n" % name)
                handle.write(
                    "2026-01-01 00:00:00|WARN|error line: 9\n")
            return gpload.GploadResult(1)

    batch.loader = LoggingLoader()

    result = batch.load()

    assert result.returncode == 1
    assert result.tables[0].error_file == "one.csv"
    assert result.tables[1].error_file == "two.csv"
    assert result.tables[0].failed_files == [
        str(first_dir / "failed" / "one.csv_9")
    ]
    assert result.tables[1].failed_files == [
        str(second_dir / "failed" / "two.csv_9")
    ]


def test_failure_without_error_location_moves_all_files(gpload, tmp_path):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {
        "a.csv": "id,name\n1,a\n",
        "b.csv": "id,name\n2,b\n",
    })
    failed_dir = table_dir / "failed"
    failed_dir.mkdir()
    (failed_dir / "old.csv").write_text("old\n", encoding="utf-8")

    batch = make_batch(gpload, tmp_path)
    batch.loader = FakeLoader(gpload, lambda text: (2, "boom\n"))

    result = batch.load()

    assert result.returncode == 2
    assert result.failed
    table = result.tables[0]
    assert table.failed
    assert table.error_file is None
    assert table.error_line is None
    assert sorted(table.failed_files) == [
        str(failed_dir / "a.csv"),
        str(failed_dir / "b.csv"),
    ]
    assert not (table_dir / "a.csv").exists()
    assert not (table_dir / "b.csv").exists()

    # load.sh lists every file in failed/, including older quarantined files.
    latest = Path(batch.latest_failed_file).read_text(encoding="utf-8")
    assert latest.splitlines() == [
        str(failed_dir / "a.csv"),
        str(failed_dir / "b.csv"),
        str(failed_dir / "old.csv"),
    ]


def test_timeout_maps_to_failure_and_quarantines_files(gpload, tmp_path):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {"a.csv": "id\n1\n"})
    batch = make_batch(gpload, tmp_path)
    batch.loader = FakeLoader(gpload, lambda text: (124, ""))

    result = batch.load()

    assert result.returncode == 2
    table = result.tables[0]
    assert table.gpload_result.returncode == 124
    assert "timed out" in table.message
    assert table.failed_files == [str(table_dir / "failed" / "a.csv")]


def test_mixed_tables_are_loaded_independently(gpload, tmp_path):
    data = tmp_path / "data"
    good_dir = write_table(data, "db1", "good", {"a.csv": "id\n1\n"})
    bad_dir = write_table(data, "db2", "bad", {"b.csv": "id\n2\n"})
    batch = make_batch(gpload, tmp_path)

    def handler(text):
        if "TABLE: bad" in text:
            return 2, "failed\n"
        return 0, ""

    batch.loader = FakeLoader(gpload, handler)

    result = batch.load()

    assert result.returncode == 2
    assert len(result.loaded_tables) == 1
    assert len(result.failed_tables) == 1
    assert result.loaded_tables[0].table == "good"
    assert result.failed_tables[0].table == "bad"
    assert not (good_dir / "a.csv").exists()
    assert not (bad_dir / "b.csv").exists()
    assert (bad_dir / "failed" / "b.csv").exists()


def test_header_error_keeps_files_in_place(gpload, tmp_path):
    data = tmp_path / "data"
    table_dir = write_table(data, "db1", "t1", {"a.csv": ""})
    batch = make_batch(gpload, tmp_path)
    loader = FakeLoader(gpload, lambda text: (0, ""))
    batch.loader = loader

    result = batch.load()

    assert result.returncode == 2
    table = result.tables[0]
    assert table.failed
    assert "empty CSV header" in table.message
    assert table.failed_files == []
    assert (table_dir / "a.csv").exists()
    assert loader.calls == []


def test_on_table_callback(gpload, tmp_path):
    data = tmp_path / "data"
    write_table(data, "db1", "t1", {"a.csv": "id\n1\n"})
    write_table(data, "db2", "t2", {"b.csv": "id\n2\n"})
    batch = make_batch(gpload, tmp_path)
    batch.loader = FakeLoader(gpload, lambda text: (0, ""))
    seen = []

    batch.load(on_table=seen.append)

    assert [(table.database, table.table) for table in seen] == [
        ("db1", "t1"), ("db2", "t2")
    ]


def test_batch_runs_gpload_in_child_process(gpload, tmp_path):
    data = tmp_path / "data"
    good_dir = write_table(data, "db1", "good", {"a.csv": "id\n1\n"})
    bad_dir = write_table(data, "db2", "bad", {"b.csv": "id\n2\n"})

    fake_script = tmp_path / "fake_gpload.py"
    fake_script.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "text = Path(args[args.index('-f') + 1]).read_text(encoding='utf-8')\n"
        "if 'TABLE: bad' in text:\n"
        "    print('2026-01-01 00:00:00|WARN|error file: b.csv')\n"
        "    print('2026-01-01 00:00:00|WARN|error line: 2')\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    batch = make_batch(
        gpload, tmp_path, script=fake_script, keep_temp_configs=False)

    result = batch.load()

    assert result.returncode == 1
    assert result.loaded_tables[0].database == "db1"
    assert result.warning_tables[0].database == "db2"
    assert result.failed_tables == []
    assert not (good_dir / "a.csv").exists()
    assert (bad_dir / "failed" / "b.csv_2").exists()
    assert Path(result.tables[0].config_path).exists() is False
    assert Path(batch.log_file).exists()


def test_batch_result_aggregates_returncodes(gpload):
    good = gpload.GploadTableResult("db", "ok", returncode=0)
    warn = gpload.GploadTableResult("db", "warn", returncode=1)
    bad = gpload.GploadTableResult("db", "bad", returncode=2)

    assert gpload.GploadBatchResult([]).returncode == 0
    assert gpload.GploadBatchResult([good]).returncode == 0
    assert gpload.GploadBatchResult([good, warn]).returncode == 1
    assert gpload.GploadBatchResult([warn, bad]).returncode == 2

    assert gpload.GploadBatchResult([good]).raise_for_status().ok
    with pytest.raises(gpload.GploadError):
        gpload.GploadBatchResult([warn]).raise_for_status()
