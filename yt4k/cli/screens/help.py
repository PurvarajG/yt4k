from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static

from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader

SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("KEYS", (
        "paste a link - opens review with your current settings",
        "several links - space-separated, queued as one batch",
        "f - change where this session saves",
        "s - settings: resolution, codec, audio format",
        "? - this screen",
        "esc - back, or quit from home",
        "ctrl+c - cancel an active download",
    )),
    ("CLIPS", (
        "2:10 to 4:05  ·  2:10-4:05 - from 2:10 until 4:05",
        "1h02m to 1h05m30s - hours / minutes / seconds spelled out",
        "2:10 to the end  ·  from 12:00 - that point through to the end",
        "start to 4:05  ·  until 0:45 - the beginning up to that point",
        "first 30s  ·  last 90s - relative to the start or the end",
    )),
    ("FORMAT WORDS", (
        "quality - 4k · 1440p · 1080p · 720p · 480p · best quality",
        "codec - av1 · vp9 · h264 · h265 / hevc · keep source",
        "re-encode - 'convert to h264' re-encodes; bare 'h264' prefers that stream",
        "file type - mp4 · mkv",
        "audio - just the audio · mp3 · wav · flac · m4a · opus · 320k",
        "shorthand - fast · smaller file · high quality",
    )),
)


class HelpScreen(Screen):
    """Searchable, scrollable keyboard and request-syntax reference."""

    BINDINGS = [("escape", "dismiss_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="HELP", id="header")
        with Container(id="screen-body"):
            yield Input(placeholder="search...", id="help-search")
            with VerticalScroll(id="help-body"):
                yield Static(self._render_help_text(""), id="help-content")
        yield MinimumSizeGuard()
        yield ContextFooter(hints=(("esc", "back"),), id="footer")

    def _render_help_text(self, query: str) -> str:
        query = query.strip().lower()
        blocks = []
        for title, lines in SECTIONS:
            title_matches = query in title.lower()
            matched = [line for line in lines
                      if not query or title_matches or query in line.lower()]
            if not matched:
                continue
            blocks.append(f"{title}\n" + "\n".join(f"  {line}" for line in matched))
        return "\n\n".join(blocks) if blocks else "No matches."

    @on(Input.Changed, "#help-search")
    def _search_changed(self, event: Input.Changed) -> None:
        self.query_one("#help-content", Static).update(self._render_help_text(event.value))

    def action_dismiss_screen(self) -> None:
        self.app.pop_screen()
