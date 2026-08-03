from __future__ import annotations

import json
from pathlib import Path

import pytest

from yt4k.models import Settings, ValidationError
from yt4k.settings import SettingsStore, remember_destination, validate_destination


def test_defaults_and_unknown_keys_are_safe(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mode": "audio", "unknown": "ignored"}))

    settings, notice = SettingsStore(path).load()

    assert settings.mode == "audio"
    assert settings.res == Settings().res
    assert notice is None


def test_valid_legacy_json_and_invalid_values_fall_back(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"res": 1080, "codec": "not-a-codec", "crf": 99}))

    settings, _ = SettingsStore(path).load()

    assert settings.res == 1080
    assert settings.codec == "source"
    assert settings.crf == 18


def test_recent_destinations_are_deduplicated_and_capped():
    settings = Settings(recent_dirs=("/one", "/two", "/three", "/four", "/five", "/six"))

    remembered = remember_destination(settings, Path("/two"))

    assert remembered.recent_dirs == ("/two", "/one", "/three", "/four", "/five", "/six")
    assert len(remember_destination(remembered, Path("/seven")).recent_dirs) == 6


def test_save_is_atomic_and_creates_parent(tmp_path: Path):
    path = tmp_path / "nested" / "config.json"
    store = SettingsStore(path)

    store.save(Settings(mode="audio"))

    assert json.loads(path.read_text())["mode"] == "audio"
    assert not list(path.parent.glob("*.tmp"))


def test_invalid_json_is_backed_up(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("not json")

    settings, notice = SettingsStore(path).load()

    assert settings == Settings()
    assert notice is not None
    assert notice.backup_path is not None and notice.backup_path.exists()


def test_validate_destination_creates_missing_and_rejects_files(tmp_path: Path):
    created = validate_destination(str(tmp_path / "missing"))
    file_path = tmp_path / "a-file"
    file_path.write_text("x")

    assert created.is_dir()
    with pytest.raises(ValidationError):
        validate_destination(str(file_path))


def test_validate_destination_rejects_unwritable(tmp_path: Path, monkeypatch):
    target = tmp_path / "unwritable"
    target.mkdir()

    def raise_permission(*args, **kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr("yt4k.settings.tempfile.NamedTemporaryFile", raise_permission)
    with pytest.raises(ValidationError, match="writable"):
        validate_destination(str(target))
