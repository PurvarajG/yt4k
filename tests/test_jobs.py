from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest

from yt4k.jobs import CancellationToken, JobRunner
from yt4k.models import JobStage, Settings
from yt4k.parsing import Clip, MediaMetadata
from yt4k.planning import build_job_plan


def meta(url="https://youtu.be/a", duration=10.0, title="video"):
    return MediaMetadata(url=url, title=title, channel=None, duration=duration, raw={})


class FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        for line in self._lines:
            yield line + "\n"


class FakeStderr:
    def __init__(self, text=""):
        self._text = text

    def read(self):
        return self._text


class FakeProc:
    def __init__(self, lines, returncode=0, stderr="", pid=111, on_wait=None):
        self.stdout = FakeStdout(lines)
        self.stderr = FakeStderr(stderr)
        self.returncode = returncode
        self.pid = pid
        self._on_wait = on_wait
        self.terminated_with = []

    def wait(self, timeout=None):
        if self._on_wait:
            self._on_wait()
        return self.returncode


class FakeRunner:
    """Builds a JobRunner with scripted Popen calls and run() calls."""

    def __init__(self, procs, run_results=None, which_ok=True):
        self._procs = list(procs)
        self._run_results = list(run_results or [])
        self.killpg_calls = []
        self.popen_calls = []
        self.which_ok = which_ok

    def which(self, tool):
        return f"/usr/bin/{tool}" if self.which_ok else None

    def popen(self, cmd, **kwargs):
        self.popen_calls.append(cmd)
        return self._procs.pop(0)

    def run(self, cmd, **kwargs):
        if self._run_results:
            return self._run_results.pop(0)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def killpg(self, pid, sig):
        self.killpg_calls.append((pid, sig))

    def build(self, grace_period=1.0):
        return JobRunner(popen=self.popen, run=self.run, which=self.which,
                          killpg=self.killpg, grace_period=grace_period)


def make_plan(tmp_path, settings=None, clip=None, urls=("https://youtu.be/a",),
              durations=None):
    settings = settings or Settings()
    durations = durations or [10.0] * len(urls)
    metadata = tuple(meta(url=u, duration=d) for u, d in zip(urls, durations))
    return build_job_plan(urls, tmp_path, settings, clip, (), metadata)


@pytest.fixture(autouse=True)
def _download_produces_file(monkeypatch):
    """yt-dlp's fake process doesn't touch disk, so make the fetch step drop a
    placeholder file into the workdir the way real yt-dlp would."""
    from yt4k import jobs as jobs_module

    original_fetch = jobs_module.JobRunner._fetch

    def patched(self, url, workdir, fmt, merge, item_index, item_count, stage,
                emit, cancel, section=None, precise=True):
        (workdir / "video [id].mkv").write_bytes(b"0" * 32)
        return original_fetch(self, url, workdir, fmt, merge, item_index,
                               item_count, stage, emit, cancel, section, precise)

    monkeypatch.setattr(jobs_module.JobRunner, "_fetch", patched)
    yield


def test_yt_dlp_progress_events_reported(tmp_path):
    plan = make_plan(tmp_path, settings=Settings(codec="source", container="mkv"))
    procs = [
        FakeProc(["YT4K 512000 1000000 1000000 100000 5"], returncode=0),
    ]
    runner = FakeRunner(procs).build()
    events = []
    runner.probe = lambda path: {"duration": 10.0, "vcodec": "vp9", "acodec": "opus"}
    runner.supports_sections = lambda: False
    results = runner.run(plan, events.append, CancellationToken())

    assert results[0].status == "success"
    download_events = [e for e in events if e.stage == JobStage.DOWNLOADING]
    assert download_events
    assert download_events[0].downloaded_bytes == 512000.0
    assert download_events[0].speed == 100000.0
    assert download_events[0].eta == 5.0


def test_ffmpeg_out_time_progress_parsed(tmp_path):
    plan = make_plan(tmp_path, settings=Settings(codec="hevc", container="mp4",
                                                  hardware=False))
    procs = [
        FakeProc(["YT4K 1000 1000 1000 NA NA"]),  # download
        FakeProc(["out_time_us=5000000", "progress=continue"]),  # transcode
    ]
    runner = FakeRunner(procs).build()
    runner.probe = lambda path: {"duration": 10.0, "vcodec": "vp9", "acodec": "opus"}
    runner.supports_sections = lambda: False
    runner.has_encoder = lambda name: True
    events = []
    results = runner.run(plan, events.append, CancellationToken())

    assert results[0].status == "success"
    encode_events = [e for e in events if e.stage == JobStage.ENCODING]
    assert encode_events
    assert encode_events[0].fraction == pytest.approx(0.5)


def test_stderr_tail_captured_on_failure(tmp_path):
    plan = make_plan(tmp_path)
    procs = [FakeProc(["YT4K 0 0 0 NA NA"], returncode=1, stderr="boom\nline2\n")]
    runner = FakeRunner(procs).build()
    runner.probe = lambda path: {}
    results = runner.run(plan, lambda e: None, CancellationToken())

    assert results[0].status == "failed"
    assert "boom" in results[0].technical_detail or "exit 1" in results[0].message


def test_batch_continues_after_one_failure(tmp_path):
    plan = make_plan(tmp_path, urls=("https://youtu.be/a", "https://youtu.be/b"),
                      durations=[10.0, 10.0])
    procs = [
        FakeProc(["YT4K 0 0 0 NA NA"], returncode=1, stderr="bad"),
        FakeProc(["YT4K 1000 1000 1000 NA NA"], returncode=0),
        FakeProc([], returncode=0),
    ]
    runner = FakeRunner(procs).build()
    runner.probe = lambda path: {"duration": 10.0, "vcodec": "h264", "acodec": "aac"}
    results = runner.run(plan, lambda e: None, CancellationToken())

    assert results[0].status == "failed"
    assert results[1].status == "success"


def test_cancellation_sends_sigterm_then_waits(tmp_path):
    plan = make_plan(tmp_path)
    proc = FakeProc(["YT4K 0 0 0 NA NA", "YT4K 100 1000 1000 NA NA"])
    fake = FakeRunner([proc])
    runner = fake.build(grace_period=1.0)
    cancel = CancellationToken()

    events = []

    def emit(event):
        events.append(event)
        if len(events) == 1:
            cancel.cancel()

    results = runner.run(plan, emit, cancel)
    assert results[0].status == "cancelled"
    assert (proc.pid, signal.SIGTERM) in fake.killpg_calls


def test_cancellation_escalates_to_sigkill_after_grace(tmp_path):
    plan = make_plan(tmp_path)
    proc = FakeProc(["YT4K 0 0 0 NA NA"])

    def hang(timeout=None):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=timeout or 0)

    call_count = {"n": 0}

    def wait(timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=timeout or 0)
        return 0

    proc.wait = wait
    fake = FakeRunner([proc])
    runner = fake.build(grace_period=0.01)
    cancel = CancellationToken()

    def emit(event):
        cancel.cancel()

    runner.run(plan, emit, cancel)
    sigs = [sig for _pid, sig in fake.killpg_calls]
    assert signal.SIGTERM in sigs
    assert signal.SIGKILL in sigs


def test_cleanup_limited_to_current_job_temp_dir(tmp_path):
    plan = make_plan(tmp_path)
    procs = [
        FakeProc(["YT4K 1000 1000 1000 NA NA"]),
        FakeProc([], returncode=0),
    ]
    runner = FakeRunner(procs).build()
    runner.probe = lambda path: {"duration": 10.0, "vcodec": "h264", "acodec": "aac"}

    untouched = tmp_path / "keep-me"
    untouched.mkdir()
    (untouched / "file.txt").write_text("hello")

    runner.run(plan, lambda e: None, CancellationToken())

    assert untouched.exists()
    assert (untouched / "file.txt").read_text() == "hello"
    leftover_temp_dirs = [p for p in tmp_path.iterdir()
                          if p.is_dir() and p.name.startswith(".yt4k-")]
    assert leftover_temp_dirs == []


class KeyedFakeRunner:
    """A runner whose fake yt-dlp download resolves by URL (the last cmd
    argument), so multiple items can be driven concurrently and
    deterministically without depending on call order across threads."""

    def __init__(self, procs_by_url, gate=None):
        self._procs_by_url = {u: list(p) for u, p in procs_by_url.items()}
        self.popen_calls = []
        self._gate = gate  # optional threading.Barrier to prove concurrency

    def which(self, tool):
        return f"/usr/bin/{tool}"

    def popen(self, cmd, **kwargs):
        self.popen_calls.append(cmd)
        if self._gate is not None:
            self._gate.wait(timeout=2)
        url = cmd[-1]
        return self._procs_by_url[url].pop(0)

    def run(self, cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def build(self):
        return JobRunner(popen=self.popen, run=self.run, which=self.which)


def _no_reencode_plan(tmp_path, urls):
    settings = Settings(codec="source", container="mkv")
    metadata = tuple(meta(url=u, duration=10.0) for u in urls)
    return build_job_plan(urls, tmp_path, settings, None, (), metadata)


@pytest.fixture
def _download_writes_mkv(monkeypatch):
    from yt4k import jobs as jobs_module

    original_fetch = jobs_module.JobRunner._fetch

    def patched(self, url, workdir, fmt, merge, item_index, item_count, stage,
                emit, cancel, section=None, precise=True):
        (workdir / "video [id].mkv").write_bytes(b"0" * 32)
        return original_fetch(self, url, workdir, fmt, merge, item_index,
                               item_count, stage, emit, cancel, section, precise)

    monkeypatch.setattr(jobs_module.JobRunner, "_fetch", patched)
    yield


def test_run_concurrent_downloads_urls_at_the_same_time(tmp_path, _download_writes_mkv):
    import threading

    urls = ("https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/c")
    plan = _no_reencode_plan(tmp_path, urls)
    gate = threading.Barrier(3, timeout=2)
    procs = {u: [FakeProc(["YT4K 1000 1000 1000 NA NA"])] for u in urls}
    fake = KeyedFakeRunner(procs, gate=gate)
    runner = fake.build()
    runner.probe = lambda path: {"duration": 10.0}

    results = runner.run_concurrent(plan, lambda e: None, CancellationToken())

    assert [r.status for r in results] == ["success", "success", "success"]
    # The barrier only releases once all three threads reached popen() at
    # once - if this passed, all three downloads really ran concurrently.


def test_run_concurrent_preserves_result_order(tmp_path, _download_writes_mkv):
    urls = ("https://youtu.be/a", "https://youtu.be/b")
    plan = _no_reencode_plan(tmp_path, urls)
    procs = {
        urls[0]: [FakeProc(["YT4K 1000 1000 1000 NA NA"], returncode=1, stderr="bad")],
        urls[1]: [FakeProc(["YT4K 1000 1000 1000 NA NA"])],
    }
    fake = KeyedFakeRunner(procs)
    runner = fake.build()
    runner.probe = lambda path: {"duration": 10.0}

    results = runner.run_concurrent(plan, lambda e: None, CancellationToken())

    assert results[0].url == urls[0]
    assert results[0].status == "failed"
    assert results[1].url == urls[1]
    assert results[1].status == "success"


def test_run_concurrent_single_url_falls_back_to_run(tmp_path, _download_writes_mkv):
    urls = ("https://youtu.be/a",)
    plan = _no_reencode_plan(tmp_path, urls)
    procs = {urls[0]: [FakeProc(["YT4K 1000 1000 1000 NA NA"])]}
    fake = KeyedFakeRunner(procs)
    runner = fake.build()
    runner.probe = lambda path: {"duration": 10.0}

    results = runner.run_concurrent(plan, lambda e: None, CancellationToken())

    assert len(results) == 1
    assert results[0].status == "success"
