from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import Settings, ValidationError
from .parsing import Clip, MediaMetadata


@dataclass(frozen=True)
class JobPlan:
    urls: tuple[str, ...]
    destination: Path
    settings: Settings
    clip: Clip | None
    modifiers: tuple[str, ...]
    metadata: tuple[MediaMetadata, ...]


def build_job_plan(
    urls: tuple[str, ...],
    destination: Path,
    settings: Settings,
    clip: Clip | None,
    modifiers: tuple[str, ...],
    metadata: tuple[MediaMetadata, ...],
) -> JobPlan:
    """Validate a parsed request against fetched metadata and build a plan."""
    if not urls:
        raise ValidationError("urls", "no URL found in the request")
    if len(metadata) != len(urls):
        raise ValidationError(
            "metadata", "metadata does not match the number of requested URLs"
        )
    if clip is not None:
        # Validates clip bounds against the first item's duration; raises
        # ValidationError on an impossible range.
        clip.resolve(metadata[0].duration)
    return JobPlan(
        urls=urls,
        destination=destination,
        settings=settings,
        clip=clip,
        modifiers=modifiers,
        metadata=metadata,
    )
