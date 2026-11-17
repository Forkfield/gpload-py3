from pathlib import Path


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
