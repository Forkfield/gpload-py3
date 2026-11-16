from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class FakeGpload:
    ERROR = 1

    def __init__(self):
        self.messages = []

    def log(self, _level, message):
        self.messages.append(message)


def test_quote(gpload):
    assert gpload.quote("plain") == "'plain'"
    assert gpload.quote("O'Reilly") == "'O''Reilly'"
    assert gpload.quote("a\\b") == "'a\\\\b'"
    assert gpload.quote("a\\b'c") == "'a\\\\b''c'"


def test_decode_unicode_escape(gpload):
    assert gpload.decode_unicode_escape(r"\x1c") == "\x1c"
    assert gpload.decode_unicode_escape(r"\u001c") == "\x1c"
    assert (
        gpload.decode_unicode_escape(r"E'\x1c'".lstrip("E'").rstrip("'"))
        == "\x1c"
    )


def test_quote_copy_value_keeps_backslashes(gpload):
    assert gpload.quote_copy_value("|") == "'|'"
    assert gpload.quote_copy_value("\\N") == "E'\\\\N'"
    assert gpload.quote_copy_value("\\") == "E'\\\\'"
    assert gpload.quote_copy_value("a'b") == "'a''b'"


def test_error_log_filename(gpload):
    assert (
        gpload.error_log_filename(
            "gpfdist://localhost:8000/data/db/table/1.csv [data/db/table/1.csv]"
        )
        == "1.csv"
    )
    assert gpload.error_log_filename("gpfdist://host:8000/dir/ [2.csv]") == "2.csv"
    assert gpload.error_log_filename("data/db/table/3.csv") == "3.csv"
    assert gpload.error_log_filename("") == ""


def test_report_errors_sets_summary_count_for_non_reuse(gpload):
    obj = object.__new__(gpload.gpload)
    obj.log_errors = True
    obj.reuse_tables = False
    obj.exitValue = 0
    obj.WARN = 2
    obj.messages = []
    obj.log = lambda _level, message: obj.messages.append(message)
    obj.count_errors = lambda: 1

    gpload.NUM_WARN_ROWS = 0
    obj.report_errors()

    assert gpload.NUM_WARN_ROWS == 1
    assert obj.exitValue == 1


def test_report_errors_uses_notice_count_without_log_errors(gpload):
    obj = object.__new__(gpload.gpload)
    obj.log_errors = False
    obj.reuse_tables = False
    obj.exitValue = 0
    obj.WARN = 2
    obj.messages = []
    obj.log = lambda _level, message: obj.messages.append(message)
    obj.count_errors = lambda: 0

    gpload.NUM_WARN_ROWS = 2
    obj.report_errors()

    assert obj.exitValue == 1
    assert gpload.NUM_WARN_ROWS == 2


def test_database_text_helpers(gpload):
    assert gpload.to_text(b"text") == "text"
    assert gpload.to_text("text") == "text"
    assert gpload.to_bool(True) is True
    assert gpload.to_bool(False) is False
    assert gpload.to_bool(b"t") is True
    assert gpload.to_bool(b"f") is False
    assert gpload.to_bool("true") is True
    assert gpload.to_bool("false") is False


def test_quote_ident_and_unident(gpload):
    assert gpload.quote_ident("col") == '"col"'
    assert gpload.quote_ident('a"b') == '"a""b"'
    assert gpload.quote_unident('"a""b"') == 'a"b'
    assert gpload.quote_unident("plain") == "plain"
    assert gpload.quote_unident(None) is None
    assert gpload.quote_unident("") == ""


def test_is_delimited(gpload):
    assert gpload.isDelimited('"abc"') is True
    assert gpload.isDelimited("abc") is False
    assert gpload.isDelimited('""') is True
    assert gpload.isDelimited("") is False


def test_split_multipart_identifier(gpload):
    assert gpload.splitUpMultipartIdentifier("table") == ["table"]
    assert gpload.splitUpMultipartIdentifier("public.load_test") == [
        "public",
        "load_test",
    ]
    assert gpload.splitUpMultipartIdentifier('"My Schema"."My.Table"') == [
        '"My Schema"',
        '"My.Table"',
    ]
    assert gpload.splitUpMultipartIdentifier('public."My.Table"') == [
        "public",
        '"My.Table"',
    ]


def test_split_into_literals_and_non_literals(gpload):
    assert gpload.splitIntoLiteralsAndNonLiterals("a='b''c' and d='e'") == [
        "a=",
        "'b''c'",
        " and d=",
        "'e'",
    ]
    assert gpload.splitIntoLiteralsAndNonLiterals('"a"."b"', quoteValue='"') == [
        " ",
        '"a"',
        ".",
        '"b"',
    ]
    assert gpload.splitIntoLiteralsAndNonLiterals("") == []


def test_split_pgpass_line(gpload):
    assert gpload.splitPgpassLine("host:5432:db:user:pass") == [
        "host",
        "5432",
        "db",
        "user",
        "pass",
    ]
    assert gpload.splitPgpassLine(r"host:5432:db:user:pa\:ss") == [
        "host",
        "5432",
        "db",
        "user",
        "pa:ss",
    ]
    assert gpload.splitPgpassLine("host:5432:db:user:pass\\")[-1] == "pass\\"


def test_bytestr(gpload):
    assert gpload.bytestr(1) == "1 byte"
    assert gpload.bytestr(1024) == "1 kB"
    assert gpload.bytestr(1536) == "1.5 kB"
    assert gpload.bytestr(1024 ** 2) == "1 MB"
    assert gpload.bytestr(1024 ** 3 + 512 * 1024 ** 2) == "1.5 GB"


def test_jenkins_empty(gpload):
    assert gpload.jenkins("") == 0


def test_shortname_compatibility(gpload):
    assert gpload.shortname("mytable") == "my3cbb7ba8"
    assert gpload.shortname("some_pretty_long_test_table_name") == "so9068664a"
    assert gpload.shortname("t") == "006742be70"
    assert gpload.shortname("my table") == "my3cbb7ba8"


def test_staging_conditions_hash_ascii(gpload):
    obj = object.__new__(gpload.gpload)
    conditions = obj.get_staging_conditions_string(
        "t", [["a", "int4"], ["b", "text"]], ["a"]
    )
    assert conditions == "t:2:'a'-'int4'-'b'-'text':'a'"
    assert (
        gpload.staging_conditions_hash(conditions)
        == "f5f18fa6ce286af2a589cdb2d37636b7"
    )


def test_notice_processor_supports_notice_receiver(gpload):
    class Notice:
        def __init__(self, message):
            self.message = message

    class ModernDB:
        def __init__(self):
            self.receiver = None

        def set_notice_receiver(self, receiver):
            self.receiver = receiver

    class FakeGploadWithDB:
        db = ModernDB()

    gpload.NUM_WARN_ROWS = 0
    gpload._install_notice_receiver(FakeGploadWithDB.db)
    FakeGploadWithDB.db.receiver(
        Notice(
            "NOTICE:  found 7 data formatting errors "
            "(7 or more input rows), rejected related input data"
        )
    )

    gpload.notice_processor(FakeGploadWithDB())
    assert gpload.NUM_WARN_ROWS == 7

    gpload.NUM_WARN_ROWS = 0
    gpload.PG_NOTICES = ["NOTICE:  Found 3 data formatting errors (3 rows)"]
    gpload.notice_processor(FakeGploadWithDB())
    assert gpload.NUM_WARN_ROWS == 3


def test_valid_tokens_shape(gpload):
    assert gpload.valid_tokens["version"] == {
        "parse_children": True,
        "parent": None,
    }
    assert gpload.valid_tokens["source"]["parent"] == "input"
    assert gpload.valid_tokens["reuse_tables"]["parent"] == "preload"


def test_yaml_walk_accepts_reference_fixture(gpload):
    document = (ROOT / "tests" / "fixtures" / "insert_text.yaml").read_text(
        encoding="utf-8"
    )
    fake = FakeGpload()

    gpload.yaml_walk(fake, yaml.compose(document).value, [])

    assert fake.messages == []


def test_yaml_walk_reports_key_in_wrong_parent(gpload):
    document = """VERSION: 1.0.0.1
GPLOAD:
  INPUT:
    - TABLE: public.load_test
"""
    fake = FakeGpload()

    gpload.yaml_walk(fake, yaml.compose(document).value, [])

    assert fake.messages == ['unexpected key: "table"']
