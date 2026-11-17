from pathlib import Path

import pytest


def test_default_template_prefers_source_checkout(gpload):
    template = Path(gpload.default_config_template())

    assert template.name == "gpload.yaml.ori"
    assert template.is_file()


def test_default_template_finds_installed_share(
        gpload, tmp_path, monkeypatch):
    prefix = tmp_path / "prefix"
    user_base = tmp_path / "user-base"
    share = prefix / "share" / "gpload-py3"
    share.mkdir(parents=True)
    installed_template = share / "gpload.yaml.ori"
    installed_template.write_text("VERSION: 1.0.0.1\n", encoding="utf-8")

    monkeypatch.setattr(
        gpload.sysconfig, "get_path", lambda name: str(prefix))
    monkeypatch.setattr(gpload.site, "USER_BASE", str(user_base))

    empty_script = tmp_path / "empty" / "gpload.py"
    empty_script.parent.mkdir()
    empty_script.write_text("", encoding="utf-8")

    assert gpload.default_config_template(
        str(empty_script)) == str(installed_template)


def test_main_entry_point_exists(gpload):
    assert callable(gpload.main)


def test_version_does_not_load_db_driver(gpload, monkeypatch, capsys):
    def fail():
        raise AssertionError("--version must not import a database driver")

    monkeypatch.setattr(gpload, "load_db_driver", fail)

    with pytest.raises(SystemExit) as exc:
        gpload.main(["--version"])

    assert exc.value.code == 0
    assert "gpload version" in capsys.readouterr().err


def test_help_does_not_load_db_driver(gpload, monkeypatch, capsys):
    def fail():
        raise AssertionError("-? must not import a database driver")

    monkeypatch.setattr(gpload, "load_db_driver", fail)

    with pytest.raises(SystemExit) as exc:
        gpload.main(["-?"])

    assert exc.value.code == 2
    assert "gpload [options] -f configuration file" in capsys.readouterr().out
