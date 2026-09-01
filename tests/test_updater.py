from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from yt4k.updater import Updater, looks_stale


class FakePip:
    """Scripted subprocess.run for the version + pip calls the Updater makes."""

    def __init__(self, versions, install_returncode=0, install_stderr=""):
        self._versions = list(versions)
        self._install_returncode = install_returncode
        self._install_stderr = install_stderr
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if "pip" in cmd:
            return subprocess.CompletedProcess(
                cmd, self._install_returncode, stdout="",
                stderr=self._install_stderr,
            )
        version = self._versions.pop(0) if self._versions else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=version + "\n", stderr="")


def make(tmp_path, run, now=lambda: 1000.0, owned=True, **kwargs):
    updater = Updater(state_path=tmp_path / "update-state.json", run=run,
                      now=now, python=str(tmp_path / "python3"), **kwargs)
    updater.manages_own_env = lambda: owned
    return updater


# ------------------------------------------------------------- stale sniffing

@pytest.mark.parametrize("message", [
    "ERROR: ffmpeg exited with code 8",
    "HTTP Error 403: Forbidden",
    "n challenge solving failed",
    "Signature solving failed",
    "Requested format is not available",
])
def test_recognises_outdated_ytdlp_failures(message):
    assert looks_stale(message)


@pytest.mark.parametrize("message", [
    "no space left on device",
    "cancelled",
    "",
])
def test_leaves_unrelated_failures_alone(message):
    assert not looks_stale(message)


# -------------------------------------------------------------------- updates

def test_update_reports_the_version_change(tmp_path):
    pip = FakePip(["2026.7.4", "2026.8.19"])
    result = make(tmp_path, pip).update_now()

    assert result.changed
    assert result.old_version == "2026.7.4"
    assert result.new_version == "2026.8.19"
    assert "2026.8.19" in result.describe()


def test_update_is_a_no_op_when_already_current(tmp_path):
    result = make(tmp_path, FakePip(["2026.8.19", "2026.8.19"])).update_now()

    assert not result.changed
    assert result.error is None


def test_failed_pip_is_reported_not_raised(tmp_path):
    pip = FakePip(["2026.7.4", "2026.7.4"], install_returncode=1,
                  install_stderr="network is unreachable")
    result = make(tmp_path, pip).update_now()

    assert not result.changed
    assert "network is unreachable" in result.error


def test_declines_to_touch_an_env_it_does_not_own(tmp_path):
    pip = FakePip([])
    result = make(tmp_path, pip, owned=False).update_now()

    assert not result.changed
    assert pip.calls == []


# ---------------------------------------------------------------------- clock

def test_first_run_is_due(tmp_path):
    assert make(tmp_path, FakePip([])).due()


def test_not_due_again_within_the_interval(tmp_path):
    clock = [1000.0]
    updater = make(tmp_path, FakePip(["1", "2"]), now=lambda: clock[0])
    updater.update_now()

    clock[0] += 3600
    assert not updater.due()


def test_due_again_after_the_interval(tmp_path):
    clock = [1000.0]
    updater = make(tmp_path, FakePip(["1", "2"]), now=lambda: clock[0])
    updater.update_now()

    clock[0] += 24 * 60 * 60 + 1
    assert updater.due()


def test_check_if_due_skips_when_recently_checked(tmp_path):
    pip = FakePip(["1", "2"])
    updater = make(tmp_path, pip)
    updater.update_now()
    before = len(pip.calls)

    assert updater.check_if_due() is None
    assert len(pip.calls) == before


def test_unreadable_state_file_does_not_break_the_check(tmp_path):
    state = tmp_path / "update-state.json"
    state.write_text("{ not json")
    updater = make(tmp_path, FakePip(["1", "2"]))

    assert updater.due()


def test_state_records_the_installed_version(tmp_path):
    updater = make(tmp_path, FakePip(["2026.7.4", "2026.8.19"]))
    updater.update_now()

    saved = json.loads((tmp_path / "update-state.json").read_text())
    assert saved["version"] == "2026.8.19"
    assert saved["last_check"] == 1000.0


# ----------------------------------------------------------------- background

def test_background_check_notifies_only_on_a_real_change(tmp_path):
    seen = []
    thread = make(tmp_path, FakePip(["2026.7.4", "2026.8.19"])).check_in_background(seen.append)
    thread.join(timeout=5)

    assert [r.new_version for r in seen] == ["2026.8.19"]


def test_background_check_is_silent_when_nothing_changed(tmp_path):
    seen = []
    thread = make(tmp_path, FakePip(["2026.8.19", "2026.8.19"])).check_in_background(seen.append)
    thread.join(timeout=5)

    assert seen == []


def test_background_check_does_nothing_when_not_due(tmp_path):
    updater = make(tmp_path, FakePip(["1", "2"]))
    updater.update_now()

    assert updater.check_in_background(lambda r: None) is None
