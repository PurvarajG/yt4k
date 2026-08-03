from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen

from ...planning import JobPlan
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader


class ReviewScreen(Screen):
    """Shown for every valid request before downloading. Fleshed out in the
    review/settings/help task; this is the routing target for Task 6."""

    def __init__(self, plan: JobPlan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="REVIEW", id="header")
        with Container(id="screen-body"):
            yield from ()
        yield MinimumSizeGuard()
        yield ContextFooter(
            hints=(("enter", "download"), ("esc", "back")), id="footer",
        )
