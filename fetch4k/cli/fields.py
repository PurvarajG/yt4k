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


def source_heights(metadata) -> set[int] | None:
    """Video heights the sources actually offer, or None when unknown.

    Playlist entries come from a flat listing without formats, so a plan with
    any such item keeps the full menu rather than guessing.
    """
    heights: set[int] = set()
    for info in metadata:
        formats = (info.raw or {}).get("formats")
        if not formats:
            return None
        heights |= {int(f["height"]) for f in formats
                    if f.get("vcodec") not in (None, "none")
                    and isinstance(f.get("height"), (int, float))}
    return heights or None


def source_codecs(metadata) -> set[str] | None:
    """Video codecs (by VIDEO_CODECS value) the sources can be fetched in."""
    prefixes = {"av01": "av1", "vp9": "vp9", "vp09": "vp9", "avc1": "h264"}
    found: set[str] = set()
    for info in metadata:
        formats = (info.raw or {}).get("formats")
        if not formats:
            return None
        for f in formats:
            vcodec = str(f.get("vcodec") or "").lower()
            for prefix, value in prefixes.items():
                if vcodec.startswith(prefix):
                    found.add(value)
    return found


def resolution_choices(heights: set[int] | None) -> list[tuple[int, str]]:
    """RESOLUTIONS trimmed to what the source can deliver.

    A 1080p TikTok never gets a 4K row: only caps below the source's best
    are real choices, and "best available" names the height it will get.
    """
    if not heights:
        return RESOLUTIONS
    top = max(heights)
    below = [(v, label) for v, label in RESOLUTIONS if v and v < top]
    return [(0, f"best available ({top}p)")] + below


def codec_choices(codecs: set[str] | None) -> list[tuple[str, str]]:
    """Drop "no re-encode" codecs the source doesn't offer; re-encodes stay."""
    if codecs is None:
        return VIDEO_CODECS
    return [(v, label) for v, label in VIDEO_CODECS
            if v == "source" or is_reencode(v) or v in codecs]


def cycle_choice(settings: Settings, key: str, values: list, step: int) -> Settings:
    """Advance `settings.<key>` through an explicit list of values."""
    current = getattr(settings, key)
    index = values.index(current) if current in values else 0
    return replace(settings, **{key: values[(index + step) % len(values)]})


def effective_choice(value, values: list, fallback):
    """The value if it's on offer, else what the job will actually use."""
    return value if value in values else fallback
