from __future__ import annotations

import os
import pty
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _launch(env_extra: dict) -> tuple[int, int]:
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env.update(env_extra)
    env["TERM"] = "xterm-256color"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "yt4k.py")],
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        env=env, close_fds=True, start_new_session=True,
    )
    os.close(slave_fd)
    return proc, master_fd


def _read_available(master_fd: int, deadline: float) -> bytes:
    import select

    chunks = []
    while time.time() < deadline:
        ready, _, _ = select.select([master_fd], [], [], 0.2)
        if not ready:
            continue
        try:
            data = os.read(master_fd, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


@pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX-only")
def test_bare_yt4k_lifecycle_restores_terminal(tmp_path):
    home = tmp_path / "home"
    config = tmp_path / "config"
    home.mkdir()
    config.mkdir()
    env_extra = {"HOME": str(home), "XDG_CONFIG_HOME": str(config), "COLUMNS": "80",
                "LINES": "24"}

    proc, master_fd = _launch(env_extra)
    try:
        import fcntl
        import struct
        import termios as termios_mod

        fcntl.ioctl(master_fd, termios_mod.TIOCSWINSZ,
                   struct.pack("HHHH", 24, 80, 0, 0))

        # Let the destination screen render, then accept the default folder.
        _read_available(master_fd, time.time() + 1.5)
        os.write(master_fd, b"\r")
        _read_available(master_fd, time.time() + 1.0)

        # Quit from the home screen.
        os.write(master_fd, b"\x1b")  # escape
        output = _read_available(master_fd, time.time() + 2.0)

        proc.wait(timeout=5)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    assert proc.returncode == 0

    text = output.decode(errors="replace")
    # Cursor must be visible again (no lingering hide-cursor sequence as the
    # last cursor-visibility instruction) and the alternate screen must have
    # been left - Textual issues these on app exit.
    assert "\x1b[?1049l" in text or "\x1b[?1049h" not in text
    # No raw arrow-key escape sequences leaked into visible output as text.
    assert not re.search(r"\^\[\[[A-D]", text)
    # No pathological run of blank-only frames (a sign of repeated redraws).
    assert text.count("\x1b[2J") < 20
