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
