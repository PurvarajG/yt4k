from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from .models import Settings, ValidationError

URL_RE = re.compile(r"https?://\S+")

_UNITS = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
}

_CLOCK_RE = re.compile(r"\d{1,3}(?::[0-5]?\d){1,2}(?:\.\d+)?")
_UNIT_PART = r"\d+(?:\.\d+)?\s*(?:h|hrs?|hours?|m|mins?|minutes?|s|secs?|seconds?)"
_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)", re.I)

_TS = (rf"(?:{_CLOCK_RE.pattern}|(?:{_UNIT_PART})(?:\s*{_UNIT_PART})*"
       r"|\d+(?:\.\d+)?(?![\w:.]))")

_SEP = r"(?:to|until|till|through|thru|->|-->|–|—|→|\.\.+|-)"

_AT_START = r"(?:the\s+)?(?:start|beginning|begin|top)"
_AT_END = r"(?:the\s+)?(?:end|ending|finish|last\s+frame)"
_FROM = rf"(?:{_TS}|{_AT_START})"
_TO = rf"(?:{_TS}|{_AT_END})"

EDGE_START = "start"
EDGE_END = "end"


def parse_timestamp(text: str) -> float | None:
    """'1:20' / '0:01:20' / '1m20s' / '90s' / '90' -> seconds."""
    t = text.strip().lower()
    if not t:
        return None
    if re.fullmatch(_CLOCK_RE.pattern, t):
        secs = 0.0
        for part in t.split(":"):
            secs = secs * 60 + float(part)
        return secs
    compact = re.sub(r"\s+", "", t)
    if re.fullmatch(rf"(?:{_UNIT_PART})+".replace(r"\s*", ""), compact):
        total = 0.0
        for val, unit in _UNIT_RE.findall(compact):
            if unit not in _UNITS:
                return None
            total += float(val) * _UNITS[unit]
        return total
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t)
    return None


def stamp(secs: float) -> str:
    """Seconds -> a filename-safe '1h02m03s' / '3m45s' / '20s'."""
    secs = max(0, int(round(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s" if m else f"{s}s"


def human_time(secs: float | None) -> str:
    if secs is None or secs < 0 or secs != secs or secs == float("inf"):
        return "--:--"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@dataclass(frozen=True)
class Clip:
    """A requested slice of a video, possibly relative to its end."""

    start: float | None = None
    end: float | None = None
    tail: float | None = None

    def resolve(self, duration: float | None) -> tuple[float, float | None]:
        """Absolute (start, end) seconds. `end` is None for 'through the end'."""
        if self.tail is not None:
            if not duration:
                raise ValidationError(
                    "clip",
                    "'last ...' needs the video length, which wasn't reported "
                    "- use an explicit range like 12:00 to 14:00",
                )
            return max(0.0, duration - self.tail), None
        start = self.start or 0.0
        if self.end is not None and self.end <= start:
            raise ValidationError(
                "clip",
                f"that range ends before it starts "
                f"({human_time(start)} -> {human_time(self.end)})",
            )
        if duration and start >= duration:
            raise ValidationError(
                "clip",
                f"clip starts at {human_time(start)} but the video is only "
                f"{human_time(duration)} long",
            )
        return start, self.end

    def label(self, duration: float | None = None) -> str:
        if self.tail is not None:
            return f"last {human_time(self.tail)}"
        if self.start and self.end is None:
            return f"{human_time(self.start)} → end"
        if not self.start and self.end is not None:
            return f"first {human_time(self.end)}"
        return f"{human_time(self.start or 0)} → {human_time(self.end)}"


def clip_tag(start: float, end: float | None, to_end: bool = False) -> str:
    if to_end or end is None:
        return f"{stamp(start)}-end"
    return f"{stamp(start)}-{stamp(end)}"


def clip_section(start: float, end: float | None) -> str:
    return f"*{start:.3f}-{'inf' if end is None else f'{end:.3f}'}"


def parse_edge(text: str) -> float | str | None:
    t = text.strip().lower()
    if re.fullmatch(_AT_START, t, re.I):
        return EDGE_START
    if re.fullmatch(_AT_END, t, re.I):
        return EDGE_END
    return parse_timestamp(t)


_RANGE_RULES = [
    ("range", re.compile(rf"\b(?:from\s+)?({_FROM})\s*{_SEP}\s*({_TO})", re.I)),
    ("first", re.compile(rf"\bfirst\s+({_TS})", re.I)),
    ("tail", re.compile(rf"\blast\s+({_TS})", re.I)),
    ("start", re.compile(rf"\b(?:from|after|start(?:ing)?(?:\s+(?:at|from))?)"
                          rf"\s+({_TS})(?:\s+(?:onwards?|on))?", re.I)),
    ("end", re.compile(rf"\b(?:until|till|up\s+to|before|ending\s+at)"
                        rf"\s+({_TS})", re.I)),
]


def parse_clip(text: str) -> tuple[Clip | None, str]:
    """Pull a time range out of `text`. Returns (clip, text-without-range)."""
    for kind, rx in _RANGE_RULES:
        m = rx.search(text)
        if not m:
            continue
        times = [parse_edge(g) if kind == "range" else parse_timestamp(g)
                 for g in m.groups()]
        if any(t is None for t in times):
            continue
        rest = (text[:m.start()] + " " + text[m.end():])
        if kind == "range":
            if times[0] == EDGE_END or times[1] == EDGE_START:
                continue
            start = 0.0 if times[0] == EDGE_START else times[0]
            end = None if times[1] == EDGE_END else times[1]
            if not start and end is None:
                return None, rest
            return Clip(start=start, end=end), rest
        if kind == "first":
            return Clip(start=0.0, end=times[0]), rest
        if kind == "tail":
            return Clip(tail=times[0]), rest
        if kind == "start":
            return Clip(start=times[0]), rest
        return Clip(start=0.0, end=times[0]), rest
    return None, text


_INTENT_RULES: list[tuple[str, dict, str]] = [
    (r"\b(?:4k|uhd|2160p?)\b", {"mode": "video", "res": 2160}, "4K"),
    (r"\b(?:1440p?|2k|qhd)\b", {"mode": "video", "res": 1440}, "1440p"),
    (r"\b(?:1080p?|full\s*hd|fhd)\b", {"mode": "video", "res": 1080}, "1080p"),
    (r"\b720p?\b", {"mode": "video", "res": 720}, "720p"),
    (r"\b480p?\b", {"mode": "video", "res": 480}, "480p"),
    (r"\b(?:best|max(?:imum)?|highest)\s+(?:quality|res(?:olution)?|available)\b",
     {"mode": "video", "res": 0}, "best available"),
    (r"\b(?:av1|av01)\b", {"mode": "video", "codec": "av1"}, "av1"),
    (r"\b(?:vp9|vp09)\b", {"mode": "video", "codec": "vp9"}, "vp9"),
    (r"\b(?:h\.?264|avc1?|x264)\b", {"mode": "video", "codec": "h264"}, "h264"),
    (r"\b(?:h\.?265|hevc|x265)\b", {"mode": "video", "codec": "hevc"}, "h265"),
    (r"\b(?:keep\s+source|no\s+re-?encode|as-?is|untouched|original\s+stream)\b",
     {"mode": "video", "codec": "source"}, "keep source"),
    (r"\bmp4\b", {"mode": "video", "container": "mp4"}, "mp4"),
    (r"\b(?:mkv|matroska)\b", {"mode": "video", "container": "mkv"}, "mkv"),
    (r"\b(?:audio[\s-]*only|just\s+(?:the\s+)?audio|only\s+(?:the\s+)?audio"
     r"|no\s+video|sound\s+only|rip\s+(?:the\s+)?audio)\b",
     {"mode": "audio"}, "audio only"),
    (r"\bmp3\b", {"mode": "audio", "audio_format": "mp3"}, "mp3"),
    (r"\bwav\b", {"mode": "audio", "audio_format": "wav"}, "wav"),
    (r"\bflac\b", {"mode": "audio", "audio_format": "flac"}, "flac"),
    (r"\b(?:m4a|aac)\b", {"mode": "audio", "audio_format": "m4a"}, "m4a"),
    (r"\bopus\b", {"mode": "audio", "audio_format": "opus"}, "opus"),
    (r"\b(320|256|192|128|96)\s*k(?:bps)?\b", {"audio_bitrate": None}, "{0}k"),
    (r"\b(?:fast|quick(?:ly)?|hardware|hurry|speed)\b",
     {"hardware": True, "preset": "veryfast"}, "fast encode"),
    (r"\b(?:small(?:er)?\s+file|compress(?:ed)?|save\s+space|tiny|lightweight)\b",
     {"crf": 24, "preset": "medium"}, "smaller file"),
    (r"\b(?:high|best|max(?:imum)?)\s+quality\b|\barchival\b",
     {"crf": 16, "preset": "slow", "hardware": False}, "high quality"),
]

_REENCODE_RE = re.compile(r"\b(?:re-?encode|transcode|convert(?:ed)?|force)\b", re.I)


def parse_intent(text: str) -> tuple[dict, list[str]]:
    """Read format words out of `text`. Returns (settings patch, chips)."""
    patch: dict = {}
    chips: list[str] = []
    for pattern, delta, chip in _INTENT_RULES:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        if "audio_bitrate" in delta and delta["audio_bitrate"] is None:
            patch["audio_bitrate"] = f"{m.group(1)}k"
            chips.append(chip.format(m.group(1)))
            continue
        patch.update(delta)
        chips.append(chip)

    if patch.get("codec") == "h264" and _REENCODE_RE.search(text):
        patch["codec"] = "h264x"
        chips = ["h264 re-encode" if c == "h264" else c for c in chips]

    if patch.get("mode") == "audio":
        for key in ("res", "codec", "container"):
            patch.pop(key, None)
        chips = [c for c in chips
                 if c not in ("4K", "1440p", "1080p", "720p", "480p",
                              "mp4", "mkv", "best available")]
    return patch, chips


@dataclass(frozen=True)
class ParsedRequest:
    raw: str
    urls: tuple[str, ...]
    settings: Settings
    clip: Clip | None
    modifiers: tuple[str, ...]


def parse_request(raw: str, base: Settings) -> ParsedRequest:
    """Split one line of input into links, settings, and an optional clip."""
    urls = tuple(URL_RE.findall(raw))
    rest = URL_RE.sub(" ", raw)
    clip, rest = parse_clip(rest)
    patch, chips = parse_intent(rest)
    settings = replace(base, **patch) if patch else base
    return ParsedRequest(raw=raw, urls=urls, settings=settings, clip=clip,
                          modifiers=tuple(chips))


@dataclass(frozen=True)
class MediaMetadata:
    url: str
    title: str
    channel: str | None
    duration: float | None
    raw: dict[str, Any] = None  # type: ignore[assignment]


def normalize_metadata(url: str, raw: dict[str, Any]) -> MediaMetadata:
    def num(value: Any) -> float | None:
        try:
            v = float(value)
            return v if v == v else None
        except (TypeError, ValueError):
            return None

    return MediaMetadata(
        url=url,
        title=raw.get("title") or "video",
        channel=raw.get("channel") or raw.get("uploader"),
        duration=num(raw.get("duration")),
        raw=raw,
    )
