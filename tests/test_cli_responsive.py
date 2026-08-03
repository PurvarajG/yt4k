from __future__ import annotations

import pytest

from yt4k.cli.app import Yt4kApp
from yt4k.models import Settings, SessionState


def make_app(tmp_path):
    store_path = tmp_path / "config.json"
    from yt4k.settings import SettingsStore

    store = SettingsStore(store_path)
    state = SessionState(settings=Settings())
    return Yt4kApp(state=state, store=store)


@pytest.mark.asyncio
async def test_destination_screen_mounts_first(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from yt4k.cli.screens.destination import DestinationScreen

        assert isinstance(app.screen, DestinationScreen)


@pytest.mark.asyncio
async def test_below_minimum_size_shows_only_resize_message(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.resize_terminal(39, 11)
        await pilot.pause()
        message = app.screen.query_one("#resize-message")
        body = app.screen.query_one("#screen-body")
        assert "size-blocked" in app.screen.classes
        assert message.styles.display != "none"
        assert body.styles.display == "none"


@pytest.mark.asyncio
async def test_resize_back_up_restores_active_screen(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        from yt4k.cli.screens.destination import DestinationScreen

        original_screen = app.screen
        await pilot.resize_terminal(39, 11)
        await pilot.pause()
        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert app.screen is original_screen
        assert isinstance(app.screen, DestinationScreen)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (60, 18), (80, 24), (120, 36)])
async def test_supported_sizes_render_without_resize_message(tmp_path, size):
    app = make_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert "size-blocked" not in app.screen.classes
