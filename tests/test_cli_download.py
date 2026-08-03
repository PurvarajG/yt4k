from __future__ import annotations

import threading
import time

import pytest

from yt4k.cli.app import Yt4kApp
from yt4k.cli.screens.download import DownloadScreen
from yt4k.cli.screens.home import HomeScreen
from yt4k.jobs import JobRunner
from yt4k.models import JobResult, JobStage, ProgressEvent, Settings, SessionState
from yt4k.parsing import MediaMetadata
from yt4k.planning import build_job_plan
from yt4k.settings import SettingsStore


def make_plan(tmp_path, urls=("https://youtu.be/a",), duration=100.0):
    metadata = tuple(
        MediaMetadata(url=u, title="A video", channel=None, duration=duration, raw={})
        for u in urls
    )
    return build_job_plan(urls, tmp_path / "out", Settings(), None, (), metadata)


class ScriptedRunner(JobRunner):
    """A runner whose .run() plays back a scripted sequence of events and
    results, checking `cancel` between steps like the real engine does."""

    def __init__(self, steps, results):
        self._steps = steps
        self._results = results
        self.ready = threading.Event()
        self.proceed = threading.Event()
        self.saw_cancel = threading.Event()

    def run(self, plan, emit, cancel):
        for step in self._steps:
            self.ready.set()
            self.proceed.wait(timeout=5)
            self.proceed.clear()
            if cancel.is_cancelled:
                self.saw_cancel.set()
                return [JobResult(url=u, status="cancelled", output_path=None,
                                  message="Cancelled") for u in plan.urls]
            emit(step)
        # A final gate so tests can inspect state after the last event and
        # before the job (and its UI transition) actually finishes.
        self.ready.set()
        self.proceed.wait(timeout=5)
        self.proceed.clear()
        if cancel.is_cancelled:
            self.saw_cancel.set()
            return [JobResult(url=u, status="cancelled", output_path=None,
                              message="Cancelled") for u in plan.urls]
        return self._results

    # DownloadScreen always calls run_concurrent(); for these deterministic,
    # single-threaded tests it behaves exactly like the scripted run() above
    # regardless of item count.
    def run_concurrent(self, plan, emit, cancel, max_workers=4):
        return self.run(plan, emit, cancel)


def make_app(tmp_path, runner):
    store = SettingsStore(tmp_path / "config.json")
    state = SessionState(settings=Settings(), destination=tmp_path / "out",
                         results=[])
    return Yt4kApp(state=state, store=store, runner=runner)


async def _wait_for(predicate, tries=40):
    for _ in range(tries):
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_progress_stage_speed_and_eta_shown(tmp_path):
    plan = make_plan(tmp_path)
    step = ProgressEvent(item_index=0, item_count=1, stage=JobStage.DOWNLOADING,
                         fraction=0.5, downloaded_bytes=512000, total_bytes=1024000,
                         speed=100000, eta=5)
    result = JobResult(url=plan.urls[0], status="success", output_path=tmp_path / "f.mp4",
                       message="Saved f.mp4")
    runner = ScriptedRunner([step], [result])
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        runner.ready.wait(timeout=2)
        runner.proceed.set()
        await pilot.pause(0.1)
        status = str(app.screen.query_one("#item-status-0").content)
        assert "50%" in status
        assert "eta" in status.lower()
        bar = app.screen.query_one("#item-progress-0")
        assert bar.percentage == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_unknown_total_bytes_does_not_crash(tmp_path):
    plan = make_plan(tmp_path)
    step = ProgressEvent(item_index=0, item_count=1, stage=JobStage.DOWNLOADING,
                         fraction=None, downloaded_bytes=None, total_bytes=None,
                         speed=None, eta=None)
    result = JobResult(url=plan.urls[0], status="success", output_path=tmp_path / "f.mp4",
                       message="Saved")
    runner = ScriptedRunner([step], [result])
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        runner.ready.wait(timeout=2)
        runner.proceed.set()
        await pilot.pause(0.1)
        status = str(app.screen.query_one("#item-status-0").content)
        assert "--:--" in status


@pytest.mark.asyncio
async def test_each_url_gets_its_own_row_and_progress_bar(tmp_path):
    plan = make_plan(tmp_path, urls=("https://youtu.be/a", "https://youtu.be/b"))
    step = ProgressEvent(item_index=1, item_count=2, stage=JobStage.DOWNLOADING,
                         fraction=0.4)
    results = [JobResult(url=u, status="success", output_path=tmp_path / "f.mp4",
                         message="Saved") for u in plan.urls]
    runner = ScriptedRunner([step], results)
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        # Both rows exist before either has progressed.
        assert app.screen.query_one("#item-progress-0")
        assert app.screen.query_one("#item-progress-1")
        runner.ready.wait(timeout=2)
        runner.proceed.set()
        await pilot.pause(0.1)
        # Only item 1's row reflects the event; item 0's is untouched.
        bar1 = app.screen.query_one("#item-progress-1")
        assert bar1.percentage == pytest.approx(0.4, abs=0.01)
        status0 = str(app.screen.query_one("#item-status-0").content)
        assert "Starting" in status0


@pytest.mark.asyncio
async def test_log_is_bounded(tmp_path):
    plan = make_plan(tmp_path)
    steps = [ProgressEvent(item_index=0, item_count=1, stage=JobStage.DOWNLOADING,
                           fraction=i / 300) for i in range(300)]
    result = JobResult(url=plan.urls[0], status="success", output_path=tmp_path / "f.mp4",
                       message="Saved")
    runner = ScriptedRunner(steps, [result])
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        screen = DownloadScreen(plan)
        app.push_screen(screen)
        await pilot.pause()
        for _ in steps:
            runner.ready.wait(timeout=2)
            runner.ready.clear()
            runner.proceed.set()
            await pilot.pause()  # let the queued call_from_thread callback run
        runner.ready.wait(timeout=2)  # the trailing finish gate
        runner.proceed.set()
        await pilot.pause(0.2)
        assert len(screen._log_lines) <= 200


@pytest.mark.asyncio
async def test_success_shows_home_action(tmp_path):
    plan = make_plan(tmp_path)
    result = JobResult(url=plan.urls[0], status="success", output_path=tmp_path / "f.mp4",
                       message="Saved f.mp4")
    runner = ScriptedRunner([], [result])
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        runner.ready.wait(timeout=2)
        runner.proceed.set()
        await pilot.pause(0.2)
        assert app.screen.query_one("#home-button")
        status = str(app.screen.query_one("#download-status").content)
        assert "Done" in status


@pytest.mark.asyncio
async def test_failure_shows_retry_and_edit_settings(tmp_path):
    plan = make_plan(tmp_path)
    result = JobResult(url=plan.urls[0], status="failed", output_path=None,
                       message="yt-dlp failed")
    runner = ScriptedRunner([], [result])
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        runner.ready.wait(timeout=2)
        runner.proceed.set()
        await pilot.pause(0.2)
        assert app.screen.query_one("#retry-button")
        assert app.screen.query_one("#edit-settings-button")
        assert app.screen.query_one("#home-button")


@pytest.mark.asyncio
async def test_first_ctrl_c_cancels(tmp_path):
    plan = make_plan(tmp_path)
    step = ProgressEvent(item_index=0, item_count=1, stage=JobStage.DOWNLOADING,
                         fraction=0.1)
    step2 = ProgressEvent(item_index=0, item_count=1, stage=JobStage.DOWNLOADING,
                          fraction=0.9)
    runner = ScriptedRunner([step, step2], [
        JobResult(url=plan.urls[0], status="cancelled", output_path=None,
                 message="Cancelled")
    ])
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        runner.ready.wait(timeout=2)
        runner.ready.clear()
        runner.proceed.set()
        await pilot.pause(0.05)
        await pilot.press("ctrl+c")
        await pilot.pause()
        status = str(app.screen.query_one("#download-status").content)
        assert "cancel" in status.lower()
        runner.ready.wait(timeout=2)
        runner.proceed.set()
        assert runner.saw_cancel.wait(timeout=2)
        await pilot.pause(0.2)
        final_status = str(app.screen.query_one("#download-status").content)
        assert "cancel" in final_status.lower()


@pytest.mark.asyncio
async def test_second_ctrl_c_forces_exit(tmp_path):
    plan = make_plan(tmp_path)
    step = ProgressEvent(item_index=0, item_count=1, stage=JobStage.DOWNLOADING,
                         fraction=0.1)
    runner = ScriptedRunner([step, step], [
        JobResult(url=plan.urls[0], status="cancelled", output_path=None,
                 message="Cancelled")
    ])
    app = make_app(tmp_path, runner)
    calls = []
    app.exit_with_summary = lambda: calls.append(True)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert calls == [True]


@pytest.mark.asyncio
async def test_home_button_returns_and_stays_usable(tmp_path):
    plan = make_plan(tmp_path)
    result = JobResult(url=plan.urls[0], status="success", output_path=tmp_path / "f.mp4",
                       message="Saved f.mp4")
    runner = ScriptedRunner([], [result])
    app = make_app(tmp_path, runner)
    async with app.run_test() as pilot:
        app.push_screen(DownloadScreen(plan))
        await pilot.pause()
        runner.ready.wait(timeout=2)
        runner.proceed.set()
        await pilot.pause(0.2)
        await pilot.click("#home-button")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert len(app.state.results) == 1
        assert app.completed_count == 1
