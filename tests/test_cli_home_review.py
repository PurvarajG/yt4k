from __future__ import annotations

import pytest
from textual.widgets import Input

from yt4k.cli.app import Yt4kApp
from yt4k.cli.screens.destination import DestinationScreen
from yt4k.cli.screens.home import HomeScreen
from yt4k.cli.screens.review import ReviewScreen
from yt4k.jobs import JobRunner
from yt4k.models import JobResult, Settings, SessionState
from yt4k.settings import SettingsStore


class FakeRunner(JobRunner):
    """Never touches the network: returns fixed metadata for any URL."""

    def __init__(self, duration=100.0, title="A great video"):
        super().__init__()
        self._duration = duration
        self._title = title

    def video_info(self, url):
        return {"title": self._title, "duration": self._duration, "channel": "Ch"}


def make_app(tmp_path, settings=None, destination=None, runner=None):
    store = SettingsStore(tmp_path / "config.json")
    state = SessionState(settings=settings or Settings(),
                         destination=destination or (tmp_path / "downloads"))
    app = Yt4kApp(state=state, store=store, runner=runner or FakeRunner())
    return app


async def _goto_home(pilot):
    """Bare app starts on destination; accept the default to reach home."""
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.asyncio
async def test_request_input_focused_on_home_entry(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        assert isinstance(app.screen, HomeScreen)
        field = app.screen.query_one("#request-input", Input)
        assert field.has_focus


@pytest.mark.asyncio
async def test_home_shows_destination_and_settings(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        context = app.screen.query_one("#context-line")
        text = str(context.content)
        assert str(app.state.destination) in text


@pytest.mark.asyncio
async def test_invalid_request_shows_inline_error(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        field = app.screen.query_one("#request-input", Input)
        field.value = "not a link at all"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        error = app.screen.query_one("#request-error")
        assert "link" in str(error.content)


@pytest.mark.asyncio
async def test_f_returns_to_destination_with_draft_preserved(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        field = app.screen.query_one("#request-input", Input)
        draft = "https://youtu.be/unfinished draft text"
        field.value = draft
        app.state.request_draft = draft
        field.value = "f"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DestinationScreen)
        assert app.state.request_draft == draft


@pytest.mark.asyncio
async def test_valid_request_opens_review_screen(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        field = app.screen.query_one("#request-input", Input)
        field.value = "https://youtu.be/example 1080p"
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if isinstance(app.screen, ReviewScreen):
                break
        assert isinstance(app.screen, ReviewScreen)
        assert app.screen.plan.settings.res == 1080
        assert app.screen.plan.metadata[0].title == "A great video"


@pytest.mark.asyncio
async def test_session_results_are_bounded(tmp_path):
    app = make_app(tmp_path)
    results = [JobResult(url=f"u{i}", status="success", output_path=None,
                         message=f"file{i}") for i in range(10)]
    app.state.results = results
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        text = str(app.screen.query_one("#session-results").content)
        assert text.count("file") <= 5
