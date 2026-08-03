from __future__ import annotations

from pathlib import Path

import pytest

from yt4k.models import Settings, ValidationError
from yt4k.parsing import Clip, MediaMetadata
from yt4k.planning import build_job_plan


def meta(url="https://youtu.be/a", duration=100.0):
    return MediaMetadata(url=url, title="video", channel=None, duration=duration, raw={})


def test_build_job_plan_success(tmp_path: Path):
    plan = build_job_plan(
        urls=("https://youtu.be/a",),
        destination=tmp_path,
        settings=Settings(),
        clip=None,
        modifiers=(),
        metadata=(meta(),),
    )
    assert plan.destination == tmp_path
    assert plan.urls == ("https://youtu.be/a",)


def test_build_job_plan_rejects_metadata_url_mismatch(tmp_path: Path):
    with pytest.raises(ValidationError):
        build_job_plan(
            urls=("https://youtu.be/a", "https://youtu.be/b"),
            destination=tmp_path,
            settings=Settings(),
            clip=None,
            modifiers=(),
            metadata=(meta(),),
        )


def test_build_job_plan_rejects_no_urls(tmp_path: Path):
    with pytest.raises(ValidationError):
        build_job_plan(
            urls=(),
            destination=tmp_path,
            settings=Settings(),
            clip=None,
            modifiers=(),
            metadata=(),
        )


def test_build_job_plan_validates_clip_bounds(tmp_path: Path):
    with pytest.raises(ValidationError):
        build_job_plan(
            urls=("https://youtu.be/a",),
            destination=tmp_path,
            settings=Settings(),
            clip=Clip(start=200.0),
            modifiers=(),
            metadata=(meta(duration=100.0),),
        )


def test_build_job_plan_accepts_valid_clip(tmp_path: Path):
    plan = build_job_plan(
        urls=("https://youtu.be/a",),
        destination=tmp_path,
        settings=Settings(),
        clip=Clip(start=10.0, end=20.0),
        modifiers=(),
        metadata=(meta(duration=100.0),),
    )
    assert plan.clip.start == 10.0
