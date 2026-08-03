from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


class Yt4kError(Exception):
    """A recoverable yt4k domain or job error."""


class ValidationError(Yt4kError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class Settings:
    mode: Literal["video", "audio"] = "video"
    res: int = 2160
    codec: str = "source"
    container: str = "auto"
    crf: int = 18
    preset: str = "slow"
    hardware: bool = False
    audio_format: str = "m4a"
    audio_bitrate: str = "192k"
    keep_source: bool = False
    clip_precise: bool = True
    output_dir: str = "~/Downloads/YouTube 4K"
    recent_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigNotice:
    message: str
    backup_path: Path | None = None


class JobStage(str, Enum):
    METADATA = "metadata"
    DOWNLOADING = "downloading"
    CLIPPING = "clipping"
    REMUXING = "remuxing"
    ENCODING = "encoding"
    FINALIZING = "finalizing"


@dataclass(frozen=True)
class ProgressEvent:
    item_index: int
    item_count: int
    stage: JobStage
    fraction: float | None
    downloaded_bytes: float | None = None
    total_bytes: float | None = None
    speed: float | None = None
    eta: float | None = None
    message: str = ""


@dataclass(frozen=True)
class JobResult:
    url: str
    status: Literal["success", "failed", "cancelled"]
    output_path: Path | None
    message: str
    technical_detail: str = ""


@dataclass
class SessionState:
    settings: Settings
    destination: Path | None = None
    request_draft: str = ""
    results: list["JobResult"] = field(default_factory=list)
