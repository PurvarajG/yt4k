from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def run_cli(tmp_path: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run the public script with isolated configuration and plain output."""

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        home = tmp_path / "home"
        config = tmp_path / "config"
        home.mkdir(exist_ok=True)
        config.mkdir(exist_ok=True)
        env.update({
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "NO_COLOR": "1",
        })
        return subprocess.run(
            [sys.executable, str(ROOT / "yt4k.py"), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    return run


@pytest.fixture(autouse=True)
def _no_real_updates(monkeypatch):
    """Keep the test suite off pip and off the network.

    The app kicks off a daily yt-dlp update on mount; left alone, every test
    that starts the workbench would shell out to pip. Only the app's own
    reference is swapped, so tests of the updater itself still exercise the
    real class.
    """
    from yt4k.cli import app as app_module
    from yt4k.updater import UpdateResult

    class OfflineUpdater:
        def check_in_background(self, on_done=None):
            return None

        def manages_own_env(self):
            return True

        def update_now(self):
            return UpdateResult(False, error="disabled in tests")

    monkeypatch.setattr(app_module, "Updater", OfflineUpdater)
