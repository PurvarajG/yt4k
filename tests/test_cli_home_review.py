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


async def _goto_review(pilot, app, request="https://youtu.be/example 1080p"):
    await _goto_home(pilot)
    field = app.screen.query_one("#request-input", Input)
    field.value = request
    await pilot.press("enter")
    for _ in range(20):
        await pilot.pause(0.05)
        if isinstance(app.screen, ReviewScreen):
            return


@pytest.mark.asyncio
async def test_review_shows_destination_metadata_and_modifiers(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_review(pilot, app)
        assert isinstance(app.screen, ReviewScreen)
        dest_text = str(app.screen.query_one("#review-destination").content)
        assert str(app.state.destination) in dest_text
        modifiers = str(app.screen.query_one("#review-modifiers").content)
        assert "1080p" in modifiers


@pytest.mark.asyncio
async def test_review_download_focused_by_default(tmp_path):
    from textual.widgets import OptionList

    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_review(pilot, app)
        rows = app.screen.query_one("#review-rows", OptionList)
        highlighted_option = rows.get_option_at_index(rows.highlighted)
        assert highlighted_option.id == "row-download"


@pytest.mark.asyncio
async def test_review_escape_preserves_request_and_returns_home(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_review(pilot, app)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert "example" in app.state.request_draft


@pytest.mark.asyncio
async def test_review_confirm_emits_one_immutable_plan(tmp_path):
    from yt4k.cli.screens.download import DownloadScreen

    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_review(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DownloadScreen)
        assert app.screen.plan.settings.res == 1080


@pytest.mark.asyncio
async def test_settings_screen_hides_irrelevant_fields(tmp_path):
    from textual.widgets import Select
    from yt4k.cli.screens.settings import SettingsScreen

    app = make_app(tmp_path, settings=Settings(mode="audio", audio_format="wav"))
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        app.push_screen(SettingsScreen())
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        assert not app.screen.query("#field-res")
        assert not app.screen.query("#field-audio-bitrate")  # wav isn't lossy


@pytest.mark.asyncio
async def test_settings_save_persists_once(tmp_path):
    from yt4k.cli.screens.settings import SettingsScreen
    from textual.widgets import Select, Button

    app = make_app(tmp_path, settings=Settings(mode="video", res=2160))
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        app.push_screen(SettingsScreen())
        await pilot.pause()
        select = app.screen.query_one("#field-res", Select)
        select.value = 1080
        await pilot.pause()
        await pilot.click("#save-button")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.state.settings.res == 1080
        reloaded, _ = app.store.load()
        assert reloaded.res == 1080


@pytest.mark.asyncio
async def test_settings_cancel_discards_draft(tmp_path):
    from yt4k.cli.screens.settings import SettingsScreen
    from textual.widgets import Select

    app = make_app(tmp_path, settings=Settings(mode="video", res=2160))
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        app.push_screen(SettingsScreen())
        await pilot.pause()
        select = app.screen.query_one("#field-res", Select)
        select.value = 480
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.state.settings.res == 2160


@pytest.mark.asyncio
async def test_help_screen_escape_returns_without_state_loss(tmp_path):
    from yt4k.cli.screens.help import HelpScreen

    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        app.state.request_draft = "kept-draft"
        app.push_screen(HelpScreen())
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.state.request_draft == "kept-draft"


@pytest.mark.asyncio
async def test_help_screen_search_filters_sections(tmp_path):
    from yt4k.cli.screens.help import HelpScreen
    from textual.widgets import Input as HelpInput, Static as HelpStatic

    app = make_app(tmp_path)
    async with app.run_test() as pilot:
        await _goto_home(pilot)
        app.push_screen(HelpScreen())
        await pilot.pause()
        search = app.screen.query_one("#help-search", HelpInput)
        search.focus()
        await pilot.pause()
        await pilot.press(*"clip")
        await pilot.pause()
        content = str(app.screen.query_one("#help-content", HelpStatic).content)
        assert "2:10" in content
        assert "ctrl+c" not in content.lower()
