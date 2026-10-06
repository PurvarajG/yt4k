from __future__ import annotations

import subprocess

import pytest

from fetch4k.selfupdate import SKIP_ENV, SelfUpdater, parse_version


class FakeBrew:
    """Scripted subprocess.run: records calls, answers `brew list --versions`."""

    def __init__(self, installed_after="fetch4k 1.0.1", fail=()):
        self.installed_after = installed_after
        self.fail = set(fail)
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        if cmd[:2] == ["brew", "list"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.installed_after,
                                               stderr="")
        failed = any(part in self.fail for part in cmd[:3])
        return subprocess.CompletedProcess(cmd, 1 if failed else 0, stdout="",
                                           stderr="")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(SKIP_ENV, raising=False)
    monkeypatch.delenv("FETCH4K_NO_SELF_UPDATE", raising=False)


def brew_root(tmp_path):
    root = tmp_path / "Cellar" / "fetch4k" / "1.0.0" / "libexec"
    root.mkdir(parents=True)
    return root


def make(tmp_path, latest="v1.0.1", current="1.0.0", run=None, kind="brew",
         root=None, fetch_latest=None):
    root = root or (brew_root(tmp_path) if kind == "brew" else tmp_path)
    if kind == "git":
        (root / ".git").mkdir(exist_ok=True)
    said, restarted = [], []
    updater = SelfUpdater(
        current=current, root=root, state_path=tmp_path / "state.json",
        say=said.append, fetch_latest=fetch_latest or (lambda timeout: latest),
        run=run or FakeBrew(), which=lambda name: f"/usr/bin/{name}",
        now=lambda: 1000.0, execv=lambda path, argv: restarted.append((path, argv)))
    return updater, said, restarted


# ------------------------------------------------------------------ versions

@pytest.mark.parametrize("text, expected", [
    ("v1.2.3", (1, 2, 3)), ("1.0.0", (1, 0, 0)), ("v2", (2,)), ("nonsense", None),
    (None, None),
])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_numeric_not_lexical_ordering(tmp_path):
    updater, *_ = make(tmp_path, current="1.9.0")

    assert updater.is_newer("v1.10.0")
    assert not updater.is_newer("v1.9.0")
    assert not updater.is_newer("v1.8.9")


# ------------------------------------------------------------------- homebrew

def test_newer_release_upgrades_with_brew_and_restarts(tmp_path):
    brew = FakeBrew()
    updater, said, restarted = make(tmp_path, run=brew)

    updater.run()

    assert ["brew", "update", "--quiet"] in brew.calls
    assert ["brew", "upgrade", "fetch4k"] in brew.calls
    assert any("1.0.0 -> 1.0.1" in line for line in said)
    assert len(restarted) == 1
    assert restarted[0][0] == "/usr/bin/fetch4k"


def test_restart_passes_the_original_arguments_through(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["fetch4k", "https://youtu.be/a", "--res", "1080"])
    updater, _, restarted = make(tmp_path)

    updater.run()

    assert restarted[0][1] == ["/usr/bin/fetch4k", "https://youtu.be/a", "--res", "1080"]


def test_already_current_does_nothing(tmp_path):
    brew = FakeBrew()
    updater, said, restarted = make(tmp_path, latest="v1.0.0", run=brew)

    assert not updater.run()
    assert brew.calls == [] and said == [] and restarted == []


def test_tap_that_has_not_caught_up_is_reported_and_not_restarted(tmp_path):
    brew = FakeBrew(installed_after="fetch4k 1.0.0")
    updater, said, restarted = make(tmp_path, run=brew)

    updater.run()

    assert restarted == []
    assert any("doesn't have 1.0.1 yet" in line for line in said)


def test_failed_brew_upgrade_keeps_running_the_current_version(tmp_path):
    updater, said, restarted = make(tmp_path, run=FakeBrew(fail={"upgrade"}))

    updater.run()

    assert restarted == []
    assert any("couldn't update" in line for line in said)


def test_multiple_installed_versions_use_the_highest(tmp_path):
    updater, _, restarted = make(tmp_path, run=FakeBrew("fetch4k 1.0.1 1.0.0"))

    updater.run()

    assert len(restarted) == 1


# ------------------------------------------------------- back-off and opt-outs

def test_a_lagging_tap_is_not_retried_on_every_launch(tmp_path):
    brew = FakeBrew(installed_after="fetch4k 1.0.0")
    updater, *_ = make(tmp_path, run=brew)
    updater.run()
    before = len(brew.calls)

    updater.run()

    assert len(brew.calls) == before


def test_force_ignores_the_back_off(tmp_path):
    brew = FakeBrew(installed_after="fetch4k 1.0.0")
    updater, *_ = make(tmp_path, run=brew)
    updater.run()
    before = len(brew.calls)

    updater.run(force=True)

    assert len(brew.calls) > before


def test_restarted_process_never_updates_again(tmp_path, monkeypatch):
    monkeypatch.setenv(SKIP_ENV, "1")
    brew = FakeBrew()
    updater, _, restarted = make(tmp_path, run=brew)

    assert not updater.run()
    assert brew.calls == [] and restarted == []


def test_opt_out_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("FETCH4K_NO_SELF_UPDATE", "1")
    brew = FakeBrew()
    updater, *_ = make(tmp_path, run=brew)

    assert not updater.run()
    assert brew.calls == []


def test_offline_check_is_silent_and_harmless(tmp_path):
    def offline(timeout):
        raise OSError("no network")

    brew = FakeBrew()
    updater, said, restarted = make(tmp_path, run=brew, fetch_latest=offline)

    assert not updater.run()
    assert brew.calls == [] and said == [] and restarted == []


def test_garbage_from_github_is_ignored(tmp_path):
    updater, *_ = make(tmp_path, latest="not a version")

    assert updater.latest() is None
    assert not updater.run()


# ------------------------------------------------------------------ other installs

def test_unknown_install_is_left_alone(tmp_path):
    brew = FakeBrew()
    updater, _, restarted = make(tmp_path, kind=None, root=tmp_path, run=brew)

    assert updater.install_kind() is None
    assert not updater.run()
    assert brew.calls == [] and restarted == []


def test_git_clone_pulls_and_reinstalls(tmp_path):
    (tmp_path / "install.sh").write_text("")
    (tmp_path / "fetch4k").mkdir()
    (tmp_path / "fetch4k" / "__init__.py").write_text('__version__ = "1.0.1"\n')
    brew = FakeBrew()
    updater, _, restarted = make(tmp_path, kind="git", run=brew)

    updater.run()

    assert ["git", "-C", str(tmp_path), "pull", "--ff-only"] in brew.calls
    assert ["bash", str(tmp_path / "install.sh")] in brew.calls
    assert len(restarted) == 1


def test_dirty_clone_that_cannot_fast_forward_is_left_alone(tmp_path):
    updater, said, restarted = make(tmp_path, kind="git", run=FakeBrew(fail={"pull"}))

    updater.run()

    assert restarted == []
    assert any("couldn't update" in line for line in said)


# ------------------------------------------------------------- GitHub lookup

def test_falls_back_to_plain_tags_when_there_is_no_release(monkeypatch):
    import urllib.error

    from fetch4k import selfupdate

    def fake_get(url, timeout):
        if url == selfupdate.LATEST_RELEASE_URL:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return [{"name": "v1.0.0"}, {"name": "v1.10.0"}, {"name": "v1.9.0"},
                {"name": "nightly"}]

    monkeypatch.setattr(selfupdate, "_get_json", fake_get)

    assert selfupdate._fetch_latest_tag(1.0) == "v1.10.0"
