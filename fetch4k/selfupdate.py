"""Keeping fetch4k itself current.

updater.py keeps yt-dlp fresh between releases; this keeps fetch4k's own code
fresh. On launch it asks GitHub for the newest release and, when it is newer
than the running version, updates the way the install was made - `brew
upgrade` for a Homebrew install, `git pull` for a clone - with the output
shown live, then restarts into the new version. The user types `fetch4k` and
ends up on the latest one.

Everything here fails soft: no network, a rate-limited API, a Homebrew tap
that hasn't caught up yet, a dirty clone - each leaves the current version
running untouched, because an updater that blocks the tool is worse than a
stale tool.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__

REPO = "PurvarajG/yt4k"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
FORMULA = "fetch4k"
CHECK_TIMEOUT_SECONDS = 3.0
UPDATE_TIMEOUT_SECONDS = 900
# If Homebrew's tap hasn't been bumped yet, don't run a slow `brew update` on
# every launch while waiting for it.
RETRY_AFTER_SECONDS = 60 * 60

# Set on the restarted process so a failed or lagging update can never loop.
SKIP_ENV = "FETCH4K_SKIP_SELFUPDATE"
OPT_OUT_ENV = "FETCH4K_NO_SELF_UPDATE"

Version = tuple[int, ...]


def parse_version(text: str | None) -> Version | None:
    """"v1.2.3" / "1.2.3" -> (1, 2, 3); anything else -> None."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def _get_json(url: str, timeout: float):
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": f"fetch4k/{__version__}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.load(response)


def _fetch_latest_tag(timeout: float) -> str | None:
    """The newest release tag, falling back to plain tags.

    A tag pushed without a GitHub Release page has no "latest release", and
    that shouldn't stop the update from being found.
    """
    try:
        tag = _get_json(LATEST_RELEASE_URL, timeout).get("tag_name")
        if parse_version(tag):
            return tag
    except urllib.error.HTTPError:
        pass
    tags = [t.get("name") for t in _get_json(TAGS_URL, timeout)]
    return max((t for t in tags if parse_version(t)), key=parse_version, default=None)


class SelfUpdater:
    """Checks for, installs, and restarts into a newer fetch4k. Injectable."""

    def __init__(
        self,
        current: str = __version__,
        root: Path | None = None,
        state_path: Path | None = None,
        say: Callable[[str], None] = lambda message: None,
        fetch_latest: Callable[[float], str | None] = _fetch_latest_tag,
        run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        now: Callable[[], float] = time.time,
        execv: Callable[[str, list[str]], None] = os.execv,
    ) -> None:
        self.current = current
        # The folder holding fetch4k.py: libexec for Homebrew, the clone for git.
        self.root = root or Path(__file__).resolve().parents[1]
        self.state_path = state_path or Path(
            "~/.config/fetch4k/selfupdate-state.json").expanduser()
        self._say = say
        self._fetch_latest = fetch_latest
        self._run = run
        self._which = which
        self._now = now
        self._execv = execv

    # ------------------------------------------------------------- discovery

    def install_kind(self) -> str | None:
        """"brew", "git", or None when we don't know how to update this copy."""
        if "/Cellar/" in os.path.realpath(self.root) and self._which("brew"):
            return "brew"
        if (self.root / ".git").exists() and self._which("git"):
            return "git"
        return None

    def latest(self) -> str | None:
        """The newest released version on GitHub, or None if unreachable."""
        try:
            tag = self._fetch_latest(CHECK_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - offline, rate-limited, bad JSON...
            return None
        return tag if parse_version(tag) else None

    def is_newer(self, tag: str | None) -> bool:
        latest, current = parse_version(tag), parse_version(self.current)
        return bool(latest and current and latest > current)

    # ----------------------------------------------------------------- state

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
                json.dump(data, handle)
            os.replace(temp, self.state_path)
        except OSError:
            pass

    def _recently_tried(self, tag: str) -> bool:
        state = self._read_state()
        tried_at = state.get("tried_at")
        return (state.get("tried") == tag and isinstance(tried_at, (int, float))
                and self._now() - tried_at < RETRY_AFTER_SECONDS)

    def _mark_tried(self, tag: str) -> None:
        self._write_state({"tried": tag, "tried_at": self._now()})

    # ---------------------------------------------------------------- update

    def _stream(self, cmd: list[str], **kwargs) -> bool:
        """Run a command with its output going straight to the terminal."""
        try:
            return self._run(cmd, timeout=UPDATE_TIMEOUT_SECONDS,
                             **kwargs).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _brew_installed_version(self) -> str | None:
        try:
            out = self._run(["brew", "list", "--versions", FORMULA],
                            capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        versions = [v for v in (out.stdout or "").split()[1:] if parse_version(v)]
        return max(versions, key=parse_version, default=None)

    def _upgrade_brew(self) -> str | None:
        # Cleanup is deferred so Homebrew doesn't delete the folder this very
        # process is still running from before we restart out of it.
        env = {**os.environ, "HOMEBREW_NO_INSTALL_CLEANUP": "1",
               "HOMEBREW_NO_ENV_HINTS": "1", "HOMEBREW_NO_AUTO_UPDATE": "1"}
        if not self._stream(["brew", "update", "--quiet"], env=env):
            return None
        if not self._stream(["brew", "upgrade", FORMULA], env=env):
            return None
        return self._brew_installed_version()

    def _upgrade_git(self) -> str | None:
        if not self._stream(["git", "-C", str(self.root), "pull", "--ff-only"]):
            return None
        installer = self.root / "install.sh"
        if installer.exists() and not self._stream(["bash", str(installer)],
                                                    cwd=str(self.root)):
            return None
        try:
            text = (self.root / "fetch4k" / "__init__.py").read_text()
        except OSError:
            return None
        match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        return match.group(1) if match else None

    def update(self, tag: str) -> bool:
        """Install the release `tag`. True only if a newer version landed."""
        kind = self.install_kind()
        if kind is None:
            return False
        self._say(f"fetch4k {tag.lstrip('v')} is out (you have {self.current}) "
                  f"- updating...")
        installed = self._upgrade_brew() if kind == "brew" else self._upgrade_git()
        if installed and self.is_newer(installed):
            self._say(f"fetch4k updated {self.current} -> {installed.lstrip('v')}")
            return True
        if installed is None:
            self._say("couldn't update fetch4k right now - continuing with "
                      f"{self.current}")
        else:
            self._say(f"{kind} doesn't have {tag.lstrip('v')} yet - continuing "
                      f"with {self.current}")
        return False

    def restart(self) -> None:
        """Replace this process with the freshly installed fetch4k."""
        target = self._which("fetch4k") or sys.argv[0]
        os.environ[SKIP_ENV] = "1"
        self._execv(target, [target, *sys.argv[1:]])

    def run(self, force: bool = False) -> bool:
        """Check, update if there's something newer, and restart into it.

        With `force` (fetch4k --update) the hourly back-off is ignored. Returns
        True if an update was installed (only reachable when `execv` is faked).
        """
        if os.environ.get(SKIP_ENV) or os.environ.get(OPT_OUT_ENV):
            return False
        if self.install_kind() is None:
            return False
        tag = self.latest()
        if not self.is_newer(tag):
            return False
        if not force and self._recently_tried(tag):
            return False
        self._mark_tried(tag)
        if not self.update(tag):
            return False
        self.restart()
        return True
