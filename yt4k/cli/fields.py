from __future__ import annotations

from dataclasses import replace

from ..models import Settings

RESOLUTIONS = [
    (2160, "2160p (4K)"), (1440, "1440p (2K)"), (1080, "1080p"),
    (720, "720p"), (480, "480p"), (0, "best available"),
]
VIDEO_CODECS = [
    ("source", "keep source (no re-encode)"),
    ("av1", "AV1 (no re-encode)"),
    ("vp9", "VP9 (no re-encode)"),
    ("h264", "H.264 (no re-encode)"),
    ("h264x", "H.264 (re-encode)"),
    ("hevc", "H.265 / HEVC (re-encode)"),
]
CONTAINERS = [("auto", "auto (mp4 when safe)"), ("mp4", "mp4"), ("mkv", "mkv")]
AUDIO_FORMATS = [
    ("source", "keep source"), ("wav", "wav · lossless"), ("flac", "flac · lossless"),
    ("m4a", "m4a · aac"), ("mp3", "mp3"), ("opus", "opus"),
]
AUDIO_BITRATES = ["320k", "256k", "192k", "128k", "96k"]
PRESETS = ["ultrafast", "veryfast", "fast", "medium", "slow", "slower"]
MODES = [("video", "video"), ("audio", "audio only")]

_LOSSY_FORMATS = {"m4a", "mp3", "opus"}
_REENCODE_CODECS = {"h264x", "hevc"}

_CYCLE_KEYS = {
    "mode": [m[0] for m in MODES],
    "res": [r[0] for r in RESOLUTIONS],
    "codec": [c[0] for c in VIDEO_CODECS],
    "container": [c[0] for c in CONTAINERS],
    "audio_format": [a[0] for a in AUDIO_FORMATS],
    "audio_bitrate": AUDIO_BITRATES,
    "preset": PRESETS,
}


def label_of(table, value) -> str:
    for item_value, label in table:
        if item_value == value:
            return label
    return str(value)


def is_lossy(audio_format: str) -> bool:
    return audio_format in _LOSSY_FORMATS


def is_reencode(codec: str) -> bool:
    return codec in _REENCODE_CODECS


def cycle_field(settings: Settings, key: str, step: int) -> Settings:
    """Advance `settings.<key>` by `step` through its allowed values."""
    if key == "crf":
        return replace(settings, crf=min(51, max(0, settings.crf + step)))
    if key in ("hardware", "keep_source", "clip_precise"):
        return replace(settings, **{key: not getattr(settings, key)})
    values = _CYCLE_KEYS.get(key)
    if not values:
        return settings
    current = getattr(settings, key)
    index = values.index(current) if current in values else 0
    return replace(settings, **{key: values[(index + 1 * step) % len(values)]})
