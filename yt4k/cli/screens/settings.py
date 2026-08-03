from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen

from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader


class SettingsScreen(Screen):
    """Fleshed out in the review/settings/help task."""

    BINDINGS = [("escape", "dismiss_screen", "Cancel")]

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="SETTINGS", id="header")
        with Container(id="screen-body"):
            yield from ()
        yield MinimumSizeGuard()
        yield ContextFooter(hints=(("esc", "cancel"),), id="footer")

    def action_dismiss_screen(self) -> None:
        self.app.pop_screen()
