from __future__ import annotations

from pathlib import Path

from yt4k.cli.fields import (
    codec_choices, resolution_choices, source_codecs, source_heights,
)
from yt4k.cli.screens.review import ReviewScreen
from yt4k.models import Settings
from yt4k.parsing import MediaMetadata
from yt4k.pinterest import IMAGES_KEY
from yt4k.planning import JobItem, JobPlan


def _meta(raw):
    return MediaMetadata(url="https://x.test/v", title="t", channel=None,
                         duration=10.0, raw=raw)


TIKTOK = _meta({"formats": [
    {"vcodec": "h264", "height": 720}, {"vcodec": "avc1.64", "height": 1080},
    {"vcodec": "none", "acodec": "aac"},
]})


def _screen(*metas, settings=Settings(res=2160, codec="av1")):
    plan = JobPlan(destination=Path("/tmp"), settings=settings, clip=None,
                   modifiers=(), items=tuple(JobItem(url=m.url, metadata=m)
                                             for m in metas))
    return ReviewScreen(plan)


def test_heights_and_codecs_come_from_formats():
    assert source_heights([TIKTOK]) == {720, 1080}
    assert source_codecs([TIKTOK]) == {"h264"}


def test_unknown_formats_keep_full_menu():
    flat = _meta({"id": "abc"})
    assert source_heights([TIKTOK, flat]) is None
    assert codec_choices(source_codecs([flat])) == codec_choices(None)


def test_resolutions_trimmed_to_source():
    values = [v for v, _ in resolution_choices({720, 1080})]
    assert values == [0, 720, 480]
    assert resolution_choices({1080})[0][1] == "best available (1080p)"


def test_codecs_hide_unoffered_passthrough_but_keep_reencodes():
    values = [v for v, _ in codec_choices({"h264"})]
    assert values == ["source", "h264", "h264x", "hevc"]


def test_review_shows_effective_values_for_a_1080p_source():
    rows = {key: value for key, _l, value, _e in _screen(TIKTOK)._rows()}
    assert rows["res"] == "best available (1080p)"
    assert rows["codec"].startswith("keep source")


def test_review_cycles_only_through_offered_values():
    screen = _screen(TIKTOK)
    screen._highlighted_key = lambda: "res"
    screen._refresh_rows = lambda: None
    seen = set()
    for _ in range(4):
        screen._cycle(1)
        seen.add(screen.draft_settings.res)
    assert seen == {0, 720, 480}


def test_image_only_plan_has_no_video_options():
    image = _meta({IMAGES_KEY: ["https://i.pinimg.com/originals/a.jpg"]})
    rows = _screen(image)._rows()
    assert [(k, v) for k, _l, v, _e in rows] == [("_image", "image · original file")]
    screen = _screen(image)
    screen._highlighted_key = lambda: "_image"
    screen._cycle(1)
    assert screen.draft_settings == Settings(res=2160, codec="av1")
