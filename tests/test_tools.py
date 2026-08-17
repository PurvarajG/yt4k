from __future__ import annotations

import sys

from yt4k import tools


def test_yt_dlp_prefers_the_copy_in_yt4ks_own_venv(tmp_path, monkeypatch):
    """A stale system yt-dlp is the usual cause of a download breaking, so
    the copy install.sh keeps updated must win over whatever is on PATH."""
    venv_bin = tmp_path / "bin"
    venv_bin.mkdir()
    (venv_bin / "yt-dlp").write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(venv_bin / "python3"))
    monkeypatch.setattr(tools.shutil, "which", lambda tool: "/usr/bin/yt-dlp")

    assert tools.find_tool("yt-dlp") == str(venv_bin / "yt-dlp")


def test_yt_dlp_falls_back_to_path(monkeypatch):
    monkeypatch.setattr(sys, "executable", "/nowhere/python3")
    monkeypatch.setattr(tools.shutil, "which", lambda tool: "/usr/bin/yt-dlp")

    assert tools.find_tool("yt-dlp") == "/usr/bin/yt-dlp"


def test_ffmpeg_prefers_path_over_the_bundled_build(monkeypatch):
    """A system ffmpeg is usually better tuned for the machine (hardware
    encoders), so the static build is only a fallback."""
    monkeypatch.setattr(tools, "_static_ffmpeg_added", False)
    called = []
    monkeypatch.setattr(tools, "_add_static_ffmpeg_to_path",
                        lambda: called.append(True))
    monkeypatch.setattr(tools.shutil, "which", lambda tool: "/opt/bin/ffmpeg")

    assert tools.find_tool("ffmpeg") == "/opt/bin/ffmpeg"
    assert not called


def test_ffprobe_falls_back_to_the_bundled_build(monkeypatch):
    monkeypatch.setattr(tools, "_static_ffmpeg_added", False)
    found = {"value": None}

    def add_paths():
        found["value"] = "/bundled/ffprobe"

    monkeypatch.setattr(tools, "_add_static_ffmpeg_to_path", add_paths)
    monkeypatch.setattr(tools.shutil, "which", lambda tool: found["value"])

    assert tools.find_tool("ffprobe") == "/bundled/ffprobe"


def test_missing_tool_returns_none(monkeypatch):
    monkeypatch.setattr(sys, "executable", "/nowhere/python3")
    monkeypatch.setattr(tools.shutil, "which", lambda tool: None)
    monkeypatch.setattr(tools, "_add_static_ffmpeg_to_path", lambda: None)

    assert tools.find_tool("ffmpeg") is None
    assert tools.find_tool("some-other-tool") is None


def test_static_ffmpeg_import_failure_is_not_fatal(monkeypatch):
    """No network at install time shouldn't crash yt4k - it should surface as
    a plain 'tool is missing' error from JobRunner instead."""
    monkeypatch.setattr(tools, "_static_ffmpeg_added", False)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def boom(name, *args, **kwargs):
        if name == "static_ffmpeg":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", boom)
    tools._add_static_ffmpeg_to_path()  # must not raise
