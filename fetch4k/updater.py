"""Keeping yt-dlp current, because a stale yt-dlp is the usual breakage.

YouTube changes how it serves video every few weeks - a new signature
scheme, a new challenge, a new throttling trick. yt-dlp ships a fix within
days, but fetch4k pins nothing to that release cadence on its own, so an
install that worked in July starts answering "ffmpeg exited with code 8" in
September and the user has no reason to suspect a dependency.

Two triggers, both aimed at never making someone diagnose that themselves:

- **Daily**: a background check on startup, at most once every 24h. It is
  silent, off the UI thread, and its failure is a no-op - a machine with no
  network still gets a working workbench.
- **On failure**: when a download dies with the fingerprint of an outdated
  yt-dlp, update immediately regardless of the daily clock, so the retry the
  user is about to attempt is the one that works.

Two kinds of install are updated, each by its own package manager:

- **fetch4k's own venv** (the installer): `pip install --upgrade yt-dlp`.
- **Homebrew** (the formula depends on Homebrew's yt-dlp): `brew upgrade
  yt-dlp`. pip would be refused there under PEP 668, and would be rude anyway.

Anything else - a distro package, a pipx shim - is somebody else's to
upgrade, so we detect that and decline.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_TIMEOUT_SECONDS = 120
# brew refreshes its own formula index before upgrading, which is slower.
BREW_TIMEOUT_SECONDS = 300

# What an out-of-date yt-dlp looks like from the outside. YouTube answers a
# request signed with a scheme yt-dlp no longer implements by refusing it, so
# the visible failure is a 403 (or the exit code of whichever tool was holding
# the socket when it arrived), plus yt-dlp's own warnings about giving up on
# the challenge.
_STALE_MARKERS = (
    "403",
    "forbidden",
    "challenge",
    "signature",
    "nsig",
    "unable to extract",
    "player response",
    "requested format is not available",
    "ffmpeg exited with code 8",
    "update to the latest version",
)


@dataclass(frozen=True)
class UpdateResult:
    """What an update attempt did. `changed` is the only thing worth showing."""

    changed: bool
    old_version: str | None = None
    new_version: str | None = None
    error: str | None = None

    def describe(self) -> str:
        if self.changed:
            return f"yt-dlp updated {self.old_version} -> {self.new_version}"
        if self.error:
            return f"yt-dlp update failed: {self.error}"
        return "yt-dlp is already up to date"


def looks_stale(message: str) -> bool:
    """True when a failure smells like YouTube outrunning our yt-dlp.

    Deliberately generous: updating yt-dlp costs a few seconds and breaks
    nothing, while missing a stale-yt-dlp failure costs the user an
    afternoon of debugging their own installation.
    """
    text = (message or "").lower()
    return any(marker in text for marker in _STALE_MARKERS)


class Updater:
    """Owns the update clock and the pip call. Injectable for tests."""

    def __init__(
        self,
        state_path: Path | None = None,
        run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
        now: Callable[[], float] = time.time,
        python: str | None = None,
        interval: float = CHECK_INTERVAL_SECONDS,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.state_path = state_path or Path(
            "~/.config/fetch4k/update-state.json").expanduser()
        self._run = run
        self._now = now
        self._python = python or sys.executable
        self._interval = interval
        self._which = which

    # ------------------------------------------------------------ ownership

    def manages_own_env(self) -> bool:
        """True when yt-dlp lives beside our interpreter, i.e. in fetch4k's venv."""
        return Path(self._python).with_name("yt-dlp").exists()

    def _brew_ytdlp(self) -> str | None:
        """The Homebrew-installed yt-dlp on PATH, or None.

        Homebrew keeps every formula under a `Cellar` directory, and PATH
        entries are symlinks into it, so resolving the link is a reliable
        tell that brew - not pip, not a distro - owns this copy.
        """
        found = self._which("yt-dlp")
        if not found or not self._which("brew"):
            return None
        return found if "/Cellar/" in os.path.realpath(found) else None

    def manager(self) -> str | None:
        """Who upgrades yt-dlp here: "pip", "brew", or None (not ours to touch).

        The venv wins, mirroring tools.find_tool: that copy is the one used.
        """
        if self.manages_own_env():
            return "pip"
        if self._brew_ytdlp():
            return "brew"
        return None

    def can_update(self) -> bool:
        return self.manager() is not None

    # ----------------------------------------------------------------- clock

    def _read_state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_state(self, data: dict) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temp = Path(handle.name)
                json.dump(data, handle, indent=2)
                handle.write("\n")
            os.replace(temp, self.state_path)
        except OSError:
            # A read-only config dir means we re-check every launch. That is a
            # few wasted seconds a day, not a reason to fail.
            pass

    def due(self) -> bool:
        last = self._read_state().get("last_check")
        if not isinstance(last, (int, float)):
            return True
        return (self._now() - last) >= self._interval

    def _mark_checked(self, result: UpdateResult) -> None:
        state = self._read_state()
        state["last_check"] = self._now()
        if result.new_version:
            state["version"] = result.new_version
        self._write_state(state)

    # ---------------------------------------------------------------- update

    def _version(self, manager: str = "pip") -> str | None:
        cmd = ([self._brew_ytdlp() or "yt-dlp", "--version"] if manager == "brew"
               else [self._python, "-m", "yt_dlp", "--version"])
        try:
            out = self._run(cmd,
                            capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return (out.stdout or "").strip() or None

    def _upgrade_command(self, manager: str) -> tuple[list[str], dict, int]:
        if manager == "brew":
            env = {**os.environ, "HOMEBREW_NO_ENV_HINTS": "1",
                   "HOMEBREW_NO_INSTALL_CLEANUP": "1"}
            return (["brew", "upgrade", "yt-dlp"], env, BREW_TIMEOUT_SECONDS)
        return ([self._python, "-m", "pip", "install", "--upgrade", "--quiet",
                 "--disable-pip-version-check", "yt-dlp"], os.environ.copy(),
                UPDATE_TIMEOUT_SECONDS)

    def update_now(self) -> UpdateResult:
        """Upgrade yt-dlp with whichever tool installed it, whatever the clock says."""
        manager = self.manager()
        if manager is None:
            return UpdateResult(False, error="yt-dlp isn't managed by fetch4k or Homebrew")
        before = self._version(manager)
        cmd, env, timeout = self._upgrade_command(manager)
        try:
            out = self._run(cmd, capture_output=True, text=True, timeout=timeout,
                            env=env)
        except (OSError, subprocess.SubprocessError) as error:
            result = UpdateResult(False, before, before, str(error))
            self._mark_checked(result)
            return result
        if out.returncode != 0:
            tail = _last_line(out.stderr or out.stdout or "")
            result = UpdateResult(False, before, before, tail or f"{manager} failed")
            self._mark_checked(result)
            return result
        after = self._version(manager)
        result = UpdateResult(bool(after and after != before), before, after)
        self._mark_checked(result)
        return result

    def check_if_due(self) -> UpdateResult | None:
        """The daily path: update only when the interval has elapsed."""
        if not self.due():
            return None
        return self.update_now()

    def check_in_background(
        self, on_done: Callable[[UpdateResult], None] | None = None,
    ) -> threading.Thread | None:
        """Run the daily check off the calling thread, or not at all.

        Returns the thread so tests (and shutdown) can join it; None when
        nothing was due.
        """
        if not self.due() or not self.can_update():
            return None

        def work() -> None:
            try:
                result = self.update_now()
            except Exception:  # noqa: BLE001 - never take the app down
                return
            if on_done and result.changed:
                on_done(result)

        thread = threading.Thread(target=work, name="fetch4k-update", daemon=True)
        thread.start()
        return thread


def _last_line(text: str) -> str:
    lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    return lines[-1] if lines else ""
