"""Locating the external tools yt4k drives: yt-dlp, ffmpeg, ffprobe.

yt4k ships these itself. The installer pip-installs `yt-dlp` and
`static-ffmpeg` into yt4k's own venv, so a fresh machine needs nothing but
Python — no Homebrew, no apt, no manual PATH surgery.

Resolution order:

- **yt-dlp**: the copy next to the running interpreter (yt4k's venv) first.
  A stale yt-dlp is the single most common cause of "this video won't
  download", so the one we keep updated wins over whatever an old Homebrew
  or distro install left on PATH.
- **ffmpeg/ffprobe**: PATH first, then the static build. ffmpeg is stable
  across versions and a system build is usually better tuned for the box
  (hardware encoders), so we only fall back to the bundled binaries.
"""

from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

BUNDLED_FIRST = ("yt-dlp",)
STATIC_FFMPEG_TOOLS = ("ffmpeg", "ffprobe")

_static_ffmpeg_added = False
_static_ffmpeg_lock = threading.Lock()


def _sibling_of_interpreter(tool: str) -> str | None:
    """The tool as installed beside the running python (i.e. in its venv)."""
    candidate = Path(sys.executable).with_name(tool)
    return str(candidate) if candidate.exists() else None


def _add_static_ffmpeg_to_path() -> None:
    """Put the pip-installed static ffmpeg/ffprobe on PATH, once.

    `weak=True` leaves a system ffmpeg alone; on first use with no system
    copy this downloads the static build, which is why the installer warms
    it up rather than letting it happen mid-download.

    Batch downloads run several items concurrently, and each one calls this
    on its very first step - without the lock, they'd all race into
    static_ffmpeg's own extraction-to-disk at once and could hand back a
    half-written binary to whichever item lost the race.
    """
    global _static_ffmpeg_added
    if _static_ffmpeg_added:
        return
    with _static_ffmpeg_lock:
        if _static_ffmpeg_added:
            return
        _static_ffmpeg_added = True
        try:
            import static_ffmpeg

            static_ffmpeg.add_paths(weak=True)
        except Exception:
            pass


def find_tool(tool: str) -> str | None:
    """Return an absolute path to `tool`, or None if it can't be found."""
    if tool in BUNDLED_FIRST:
        bundled = _sibling_of_interpreter(tool)
        if bundled:
            return bundled
    found = shutil.which(tool)
    if found:
        return found
    if tool in STATIC_FFMPEG_TOOLS:
        _add_static_ffmpeg_to_path()
        return shutil.which(tool)
    return None
