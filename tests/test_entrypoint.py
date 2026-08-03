from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "args",
    [
        ("https://youtu.be/example", "2:10", "to", "4:05", "--explain"),
        ("https://youtu.be/example", "12:00", "to", "the", "end", "--explain"),
        ("https://youtu.be/example", "first", "30s", "in", "1080p", "mp4", "--explain"),
        ("https://youtu.be/example", "just", "the", "audio", "as", "mp3", "320k", "--explain"),
        ("https://youtu.be/example", "from", "12:00", "h265", "small", "file", "--explain"),
        ("https://youtu.be/example", "1:20-3:45", "--explain"),
    ],
)
def test_readme_one_shot_examples_explain_without_download(run_cli, args):
    result = run_cli(*args)

    assert result.returncode == 0, result.stderr
    assert "understood as" in result.stdout


def test_explain_parses_clip_and_quality(run_cli):
    result = run_cli("https://youtu.be/example", "1:20-3:45", "1080p", "--explain")

    assert result.returncode == 0
    assert "1080p" in result.stdout


def test_output_override_is_session_only(run_cli, tmp_path):
    result = run_cli("https://youtu.be/example", "--explain", "-o", str(tmp_path / "clips"))

    assert result.returncode == 0
    assert "this run only" in result.stdout


def test_words_without_url_are_rejected(run_cli):
    result = run_cli("first", "30s")

    assert result.returncode == 2
    assert "no URL found" in result.stderr
