from __future__ import annotations

import pytest

from yt4k.cli.app import Yt4kApp
from yt4k.cli.screens.destination import DestinationScreen
from yt4k.cli.screens.home import HomeScreen
from yt4k.jobs import JobRunner
from yt4k.models import Settings, SessionState
from yt4k.settings import SettingsStore
from textual.widgets import Input, OptionList


def make_app(tmp_path, settings=None):
    store = SettingsStore(tmp_path / "config.json")
    state = SessionState(settings=settings or Settings())
    return Yt4kApp(state=state, store=store, runner=JobRunner())


@pytest.mark.asyncio
async def test_default_row_focused_first(tmp_path):
    settings = Settings(output_dir=str(tmp_path / "default-dir"))
    app = make_app(tmp_path, settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        option_list = app.screen.query_one("#destination-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.has_focus


@pytest.mark.asyncio
async def test_recent_rows_appear_deduplicated(tmp_path):
    default_dir = str(tmp_path / "default-dir")
    recent_dir = str(tmp_path / "recent-dir")
    settings = Settings(output_dir=default_dir, recent_dirs=(default_dir, recent_dir))
    app = make_app(tmp_path, settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        option_list = app.screen.query_one("#destination-list", OptionList)
        # default + one deduplicated recent + custom-path row
        assert option_list.option_count == 3


@pytest.mark.asyncio
async def test_enter_uses_folder_for_session_only(tmp_path):
    default_dir = tmp_path / "default-dir"
    settings = Settings(output_dir=str(default_dir))
    app = make_app(tmp_path, settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.state.destination == default_dir.expanduser().resolve() or \
            app.state.destination == default_dir.expanduser()
        assert app.state.settings.output_dir == str(default_dir)


@pytest.mark.asyncio
async def test_d_persists_new_default(tmp_path):
    default_dir = tmp_path / "default-dir"
    other_dir = tmp_path / "other-dir"
    settings = Settings(output_dir=str(default_dir), recent_dirs=(str(other_dir),))
    app = make_app(tmp_path, settings)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.state.settings.output_dir == str(other_dir)
        reloaded, _ = app.store.load()
        assert reloaded.output_dir == str(other_dir)


@pytest.mark.asyncio
async def test_custom_path_input_creates_missing_folder(tmp_path):
    settings = Settings(output_dir=str(tmp_path / "default-dir"))
    app = make_app(tmp_path, settings)
    custom = tmp_path / "brand-new"
    async with app.run_test() as pilot:
        await pilot.pause()
        option_list = app.screen.query_one("#destination-list", OptionList)
        option_list.highlighted = option_list.option_count - 1
        await pilot.press("enter")
        await pilot.pause()
        field = app.screen.query_one("#custom-path-input", Input)
        field.value = str(custom)
        await pilot.press("enter")
        await pilot.pause()
        assert custom.is_dir()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_invalid_path_shows_error_and_keeps_focus(tmp_path):
    settings = Settings(output_dir=str(tmp_path / "default-dir"))
    app = make_app(tmp_path, settings)
    not_a_dir = tmp_path / "some-file"
    not_a_dir.write_text("x")
    async with app.run_test() as pilot:
        await pilot.pause()
        option_list = app.screen.query_one("#destination-list", OptionList)
        option_list.highlighted = option_list.option_count - 1
        await pilot.press("enter")
        await pilot.pause()
        field = app.screen.query_one("#custom-path-input", Input)
        field.value = str(not_a_dir)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DestinationScreen)
        error = app.screen.query_one("#destination-error")
        text = str(error.content)
        assert "not a directory" in text or str(not_a_dir) in text


@pytest.mark.asyncio
async def test_escape_exits_without_destination(tmp_path):
    settings = Settings(output_dir=str(tmp_path / "default-dir"))
    app = make_app(tmp_path, settings)
    calls = []
    app.exit_with_summary = lambda: calls.append(True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.state.destination is None
        assert calls == [True]
