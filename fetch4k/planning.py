from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from pathlib import Path

from .models import Settings, ValidationError
from .parsing import Clip, MediaMetadata

if TYPE_CHECKING:
    from .models import JobResult


@dataclass(frozen=True)
class JobItem:
    """One independently runnable source, including playlist provenance."""

    url: str
    metadata: MediaMetadata
    playlist_title: str | None = None
    playlist_folder: str | None = None
    playlist_position: int | None = None
    playlist_count: int | None = None
    preflight_error: str | None = None
    preflight_kind: str | None = None

    @property
    def output_prefix(self) -> str:
        if self.playlist_position is None:
            return ""
        width = max(3, len(str(self.playlist_count or self.playlist_position)))
        return f"{self.playlist_position:0{width}d} - "


@dataclass(frozen=True)
class JobPlan:
    destination: Path
    settings: Settings
    clip: Clip | None
    modifiers: tuple[str, ...]
    items: tuple[JobItem, ...]

    @property
    def urls(self) -> tuple[str, ...]:
        return tuple(item.url for item in self.items)

    @property
    def metadata(self) -> tuple[MediaMetadata, ...]:
        return tuple(item.metadata for item in self.items)

    @property
    def playlist_count(self) -> int:
        return sum(item.playlist_position is not None for item in self.items)

    @property
    def playlist_titles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(
            item.playlist_title for item in self.items if item.playlist_title
        ))

    @property
    def unavailable_count(self) -> int:
        return sum(item.preflight_kind == "unavailable" for item in self.items)

    def retryable(self, results: list["JobResult"]) -> "JobPlan":
        """Return only failed/cancelled items, retaining playlist ordinals."""
        if len(results) != len(self.items):
            raise ValueError("results do not match plan items")
        retry_items = tuple(
            item for item, result in zip(self.items, results)
            if result.status in {"failed", "cancelled"}
        )
        return replace(self, items=retry_items)


def build_job_plan(
    urls: tuple[str, ...],
    destination: Path,
    settings: Settings,
    clip: Clip | None,
    modifiers: tuple[str, ...],
    metadata: tuple[MediaMetadata, ...],
    items: tuple[JobItem, ...] | None = None,
) -> JobPlan:
    """Validate a parsed request against fetched metadata and build a plan."""
    if items is None and not urls:
        raise ValidationError("urls", "no URL found in the request")
    if items is None and len(metadata) != len(urls):
        raise ValidationError(
            "metadata", "metadata does not match the number of requested URLs"
        )
    if items is None:
        items = tuple(JobItem(url=url, metadata=info)
                      for url, info in zip(urls, metadata))
    if not items:
        raise ValidationError("urls", "playlist has no entries")
    checked: list[JobItem] = []
    for item in items:
        if clip is None or item.preflight_error:
            checked.append(item)
            continue
        try:
            clip.resolve(item.metadata.duration)
        except ValidationError as error:
            if item.playlist_position is None:
                raise
            checked.append(replace(item, preflight_error=error.message,
                                   preflight_kind="clip"))
        else:
            checked.append(item)
    return JobPlan(
        destination=destination,
        settings=settings,
        clip=clip,
        modifiers=modifiers,
        items=tuple(checked),
    )
