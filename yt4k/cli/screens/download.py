from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen

from ...planning import JobPlan
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader


class DownloadScreen(Screen):
    """Fleshed out in the download progress/cancellation task."""

    def __init__(self, plan: JobPlan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="DOWNLOAD", id="header")
        with Container(id="screen-body"):
            yield from ()
        yield MinimumSizeGuard()
        yield ContextFooter(hints=(("ctrl+c", "cancel"),), id="footer")
