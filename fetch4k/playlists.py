"""Classify and expand YouTube playlist URLs without downloading media."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any
from urllib.parse import parse_qs, urlparse

from .models import Fetch4kError
from .parsing import MediaMetadata, normalize_metadata
from .planning import JobItem


class URLKind(str, Enum):
    VIDEO = "video"
    PLAYLIST = "playlist"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class PlaylistExpansion:
    source_url: str
    title: str
    items: tuple[JobItem, ...]

    @property
    def unavailable_count(self) -> int:
        return sum(item.preflight_error is not None for item in self.items)


_INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACE = re.compile(r"\s+")


def _truncate_utf8(text: str, limit: int) -> str:
    return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def safe_playlist_name(title: str | None) -> str:
    """Return one bounded, portable path component derived from a title."""
    cleaned = _INVALID_COMPONENT.sub(" ", title or "")
    cleaned = _truncate_utf8(_SPACE.sub(" ", cleaned).strip(" ."), 120).strip(" .")
    return cleaned if cleaned and cleaned not in {".", ".."} else "Playlist"


def classify_url(url: str) -> URLKind:
    """Classify only URLs that carry a playlist identifier.

    A watch or youtu.be link plus `list` can mean either one video or the
    surrounding playlist. A playlist endpoint with only `list` is unambiguous.
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if not query.get("list", [""])[0]:
        return URLKind.VIDEO
    path = parsed.path.rstrip("/")
    is_watch = path.endswith("/watch") or bool(query.get("v"))
    is_short = parsed.netloc.lower().endswith("youtu.be") and bool(path.strip("/"))
    return URLKind.AMBIGUOUS if is_watch or is_short else URLKind.PLAYLIST


def _entry_url(entry: dict[str, Any]) -> str | None:
    video_id = entry.get("id")
    if isinstance(video_id, str) and re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
        return f"https://www.youtube.com/watch?v={video_id}"
    candidate = entry.get("webpage_url") or entry.get("url")
    if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        return f"https://www.youtube.com/watch?v={candidate}"
    if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
        parsed = urlparse(candidate)
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id and re.fullmatch(r"[A-Za-z0-9_-]+", video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
    return None


def _is_known_unavailable(entry: dict[str, Any]) -> bool:
    availability = str(entry.get("availability") or "").lower()
    if availability and availability not in {"public", "unlisted"}:
        return True
    if availability in {"public", "unlisted"}:
        return False
    title = str(entry.get("title") or "").strip().lower()
    return title in {"private video", "deleted video", "[private video]", "[deleted video]"}


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _playlist_id(source_url: str, raw: dict[str, Any]) -> str | None:
    value = raw.get("id") or raw.get("playlist_id") or parse_qs(urlparse(source_url).query).get("list", [None])[0]
    return (_truncate_utf8(value, 48) if isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9_-]+", value) else None)


def expand_playlist(source_url: str, raw: dict[str, Any]) -> PlaylistExpansion:
    """Turn yt-dlp's flat playlist JSON into ordered, independently runnable items.

    Flat playlists may contain null entries for videos which are unavailable to
    the current account. Keep those positions as failed jobs rather than
    silently renumbering every later item.
    """
    title = str(raw.get("title") or "Playlist")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        entries = []
    positions = [(_positive_int(entry.get("playlist_index")) if isinstance(entry, dict) else None)
                 for entry in entries]
    count = _positive_int(raw.get("playlist_count")) or max(
        [len(entries), *(position or 0 for position in positions)]
    )
    list_id = _playlist_id(source_url, raw)
    folder = safe_playlist_name(title) + (f" [{list_id}]" if list_id else "")
    items: list[JobItem] = []
    used_positions: set[int] = set()
    for position, raw_entry in enumerate(entries, start=1):
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        item_url = _entry_url(entry)
        unavailable = _is_known_unavailable(entry)
        if item_url and not unavailable:
            metadata = normalize_metadata(item_url, entry)
            error = None
            kind = None
        else:
            metadata = MediaMetadata(
                url="", title=str(entry.get("title") or "Unavailable playlist item"),
                channel=None, duration=None, raw=entry,
            )
            error = "Unavailable, private, or deleted playlist item"
            kind = "unavailable"
        item_position = positions[position - 1] or position
        while item_position in used_positions:
            item_position += 1
        used_positions.add(item_position)
        items.append(JobItem(
            url=item_url or source_url,
            metadata=metadata,
            playlist_title=title,
            playlist_folder=folder,
            playlist_position=item_position,
            playlist_count=count,
            preflight_error=error,
            preflight_kind=kind,
        ))
    return PlaylistExpansion(source_url=source_url, title=title, items=tuple(items))


def resolve_source_items(
    urls: tuple[str, ...], runner: Any, scopes: tuple[URLKind, ...], clip: Any,
) -> tuple[JobItem, ...]:
    """Fetch source metadata and expand only playlists selected by the caller."""
    if scopes and len(scopes) != len(urls):
        raise ValueError("playlist scopes do not match URLs")
    items: list[JobItem] = []
    folder_counts: dict[str, int] = {}
    for index, url in enumerate(urls):
        kind = classify_url(url)
        scope = scopes[index] if scopes else kind
        if kind is URLKind.AMBIGUOUS and scope not in {URLKind.VIDEO, URLKind.PLAYLIST}:
            raise Fetch4kError("This link contains both a video and a playlist; choose --video or --playlist.")
        if scope is URLKind.PLAYLIST:
            expansion = expand_playlist(url, runner.playlist_info(url))
            folder = expansion.items[0].playlist_folder if expansion.items else None
            if folder:
                folder_counts[folder] = folder_counts.get(folder, 0) + 1
                if folder_counts[folder] > 1:
                    instance_folder = f"{folder} ({folder_counts[folder]})"
                    items.extend(replace(item, playlist_folder=instance_folder)
                                 for item in expansion.items)
                else:
                    items.extend(expansion.items)
            else:
                items.extend(expansion.items)
        else:
            items.append(JobItem(url=url, metadata=normalize_metadata(url, runner.video_info(url))))

    if clip is None or getattr(clip, "tail", None) is None:
        return tuple(items)
    refreshed: list[JobItem] = []
    for item in items:
        if item.preflight_error or item.metadata.duration is not None:
            refreshed.append(item)
            continue
        try:
            metadata = normalize_metadata(item.url, runner.video_info(item.url))
            refreshed.append(JobItem(
                url=item.url, metadata=metadata, playlist_title=item.playlist_title,
                playlist_folder=item.playlist_folder, playlist_position=item.playlist_position,
                playlist_count=item.playlist_count,
            ))
        except Fetch4kError as error:
            refreshed.append(JobItem(
                url=item.url, metadata=item.metadata, playlist_title=item.playlist_title,
                playlist_folder=item.playlist_folder, playlist_position=item.playlist_position,
                playlist_count=item.playlist_count,
                preflight_error=f"Could not read duration for clip: {error}",
                preflight_kind="metadata",
            ))
    return tuple(refreshed)
