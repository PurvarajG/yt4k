from __future__ import annotations

import pytest

from yt4k.models import Settings
from yt4k.parsing import Clip, parse_clip, parse_intent, parse_request, parse_timestamp


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1:20", 80.0),
        ("0:01:20", 80.0),
        ("1m20s", 80.0),
        ("90s", 90.0),
        ("90", 90.0),
        ("2h", 7200.0),
    ],
)
def test_parse_timestamp_forms(text, expected):
    assert parse_timestamp(text) == expected


@pytest.mark.parametrize(
    "text,start,end",
    [
        ("2:10 to 4:05", 130.0, 245.0),
        ("2:10-4:05", 130.0, 245.0),
        ("from 12:00 to the end", 720.0, None),
        ("start to 4:05", 0.0, 245.0),
        ("until 0:45", 0.0, 45.0),
        ("from 12:00", 720.0, None),
    ],
)
def test_parse_clip_ranges(text, start, end):
    clip, _ = parse_clip(text)
    assert clip is not None
    assert clip.start == start
    assert clip.end == end


def test_parse_clip_first():
    clip, _ = parse_clip("first 30s")
    assert clip == Clip(start=0.0, end=30.0)


def test_parse_clip_tail():
    clip, _ = parse_clip("last 90s")
    assert clip == Clip(tail=90.0)


def test_parse_clip_whole_video_is_none():
    clip, _ = parse_clip("start to end")
    assert clip is None


@pytest.mark.parametrize(
    "text,expected_patch",
    [
        ("1080p", {"mode": "video", "res": 1080}),
        ("4k", {"mode": "video", "res": 2160}),
        ("h265 small file", {"mode": "video", "codec": "hevc", "crf": 24, "preset": "medium"}),
        ("just the audio as mp3 320k", {"mode": "audio", "audio_format": "mp3", "audio_bitrate": "320k"}),
        ("keep source", {"mode": "video", "codec": "source"}),
    ],
)
def test_parse_intent_format_words(text, expected_patch):
    patch, _ = parse_intent(text)
    for key, value in expected_patch.items():
        assert patch[key] == value


def test_parse_intent_convert_to_h264_reencodes():
    patch, chips = parse_intent("convert it to h264")
    assert patch["codec"] == "h264x"
    assert "h264 re-encode" in chips


def test_parse_intent_audio_drops_video_only_fields():
    patch, chips = parse_intent("just the audio 1080p mp4")
    assert "res" not in patch
    assert "container" not in patch
    assert "1080p" not in chips


def test_parse_request_multiple_urls():
    result = parse_request(
        "https://youtu.be/a https://youtu.be/b 1080p", Settings()
    )
    assert result.urls == ("https://youtu.be/a", "https://youtu.be/b")
    assert result.settings.res == 1080
    assert result.clip is None


def test_parse_request_explicit_flags_win_over_words():
    base = Settings(res=720)
    parsed = parse_request("https://youtu.be/a 1080p", base)
    # words parsed first; explicit CLI flags are applied afterward by the
    # caller, so the parser itself just reflects the words.
    assert parsed.settings.res == 1080


def test_parse_request_reversed_clip_is_still_valid_range():
    result = parse_request("https://youtu.be/a 4:05 to 2:10", Settings())
    assert result.clip is not None
    assert result.clip.start == 245.0
    assert result.clip.end == 130.0
