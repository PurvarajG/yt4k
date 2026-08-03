from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ConfigNotice, Settings, ValidationError


_ALLOWED = {
    "mode": {"video", "audio"},
    "res": {0, 480, 720, 1080, 1440, 2160},
    "codec": {"source", "av1", "vp9", "h264", "h264x", "hevc"},
    "container": {"auto", "mp4", "mkv"},
    "preset": {"ultrafast", "veryfast", "fast", "medium", "slow", "slower"},
    "audio_format": {"source", "wav", "flac", "m4a", "mp3", "opus"},
    "audio_bitrate": {"320k", "256k", "192k", "128k", "96k"},
}


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or Path("~/.config/yt4k/config.json").expanduser()

    def load(self) -> tuple[Settings, ConfigNotice | None]:
        if not self.path.exists():
            return Settings(), None
        try:
            raw = json.loads(self.path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("configuration must be an object")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_name(f"{self.path.name}.invalid-{stamp}")
            try:
                os.replace(self.path, backup)
            except OSError:
                backup = None
            return Settings(), ConfigNotice(f"Invalid settings were reset: {error}", backup)
        return _settings_from_mapping(raw), None

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(settings)
        payload["recent_dirs"] = list(settings.recent_dirs)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        try:
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)


def _settings_from_mapping(raw: dict[str, Any]) -> Settings:
    defaults = Settings()
    values = asdict(defaults)
    for key, default in values.items():
        value = raw.get(key, default)
        if key in _ALLOWED and value not in _ALLOWED[key]:
            continue
        if key == "crf" and (not isinstance(value, int) or not 0 <= value <= 51):
            continue
        if key in {"hardware", "keep_source", "clip_precise"} and not isinstance(value, bool):
            continue
        if key == "output_dir" and (not isinstance(value, str) or not value.strip()):
            continue
        if key == "recent_dirs":
            if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
                continue
            value = tuple(value[:6])
        values[key] = value
    return Settings(**values)


def validate_destination(raw: str, create: bool = True) -> Path:
    if not raw or not raw.strip():
        raise ValidationError("destination", "Choose a destination folder.")
    path = Path(raw.strip()).expanduser()
    if path.exists() and not path.is_dir():
        raise ValidationError("destination", f"Destination is not a directory: {path}")
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise OSError("directory does not exist")
        with tempfile.NamedTemporaryFile(dir=path, prefix=".yt4k-write-check-", delete=True):
            pass
    except OSError as error:
        raise ValidationError("destination", f"Destination is not writable: {path} ({error})") from error
    return path


def remember_destination(settings: Settings, path: Path) -> Settings:
    value = str(path.expanduser())
    recent = tuple(item for item in settings.recent_dirs if item != value)
    return replace(settings, recent_dirs=(value, *recent)[:6])
