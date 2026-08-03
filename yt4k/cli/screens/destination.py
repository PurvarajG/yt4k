from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen

from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader


class DestinationScreen(Screen):
    """Always the first screen of an interactive session."""

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="DESTINATION", id="header")
        with Container(id="screen-body"):
            yield Container(id="destination-body")
        yield MinimumSizeGuard()
        yield ContextFooter(
            hints=(("enter", "use folder"), ("d", "make default"), ("esc", "quit")),
            id="footer",
        )
