from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class WorkbenchHeader(Static):
    """One-line YT4K wordmark, screen label, and optional step/status."""

    DEFAULT_CSS = """
    WorkbenchHeader {
        height: 1;
        width: 100%;
        content-align: left middle;
        padding: 0 1;
    }
    """

    screen_label: reactive[str] = reactive("")
    status: reactive[str] = reactive("")

    def __init__(self, screen_label: str = "", status: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.screen_label = screen_label
        self.status = status

    def render(self) -> str:
        parts = ["YT4K"]
        if self.screen_label:
            parts.append(self.screen_label)
        if self.status:
            parts.append(self.status)
        return "  ".join(parts)

    def watch_screen_label(self, _value: str) -> None:
        self.refresh()

    def watch_status(self, _value: str) -> None:
        self.refresh()


class ContextFooter(Static):
    """Footer hints: ordered (key, action) pairs valid on the current screen."""

    DEFAULT_CSS = """
    ContextFooter {
        height: 1;
        width: 100%;
        dock: bottom;
        content-align: left middle;
        padding: 0 1;
    }
    """

    def __init__(self, hints: tuple[tuple[str, str], ...] = (), **kwargs) -> None:
        super().__init__(**kwargs)
        self._hints = hints
        self._apply()

    def set_hints(self, hints: tuple[tuple[str, str], ...]) -> None:
        self._hints = hints
        self._apply()

    def _apply(self) -> None:
        self.update("   ".join(f"[{key}] {action}" for key, action in self._hints))


class MinimumSizeGuard(Static):
    """Overlay shown below the minimum supported terminal size.

    Mounted alongside a screen's real content; CSS toggles which is visible so
    resizing never remounts state.
    """

    DEFAULT_CSS = """
    MinimumSizeGuard {
        display: none;
        width: 100%;
        height: 100%;
        content-align: center middle;
    }
    """

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("id", "resize-message")
        super().__init__(
            "Terminal too small - resize to at least 40x12 to continue.",
            **kwargs,
        )
