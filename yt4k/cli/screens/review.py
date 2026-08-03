from __future__ import annotations

from dataclasses import replace

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ...models import Settings
from ...planning import JobPlan
from ..fields import (
    AUDIO_BITRATES, CONTAINERS, MODES, RESOLUTIONS, VIDEO_CODECS,
    cycle_field, is_lossy, label_of,
)
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader

DOWNLOAD_OPTION_ID = "row-download"


class ReviewConfirmed(Message):
    def __init__(self, plan: JobPlan) -> None:
        super().__init__()
        self.plan = plan


class ReviewScreen(Screen):
    """Shown for every valid request before downloading."""

    BINDINGS = [
        ("left", "cycle_left", "Change"),
        ("right", "cycle_right", "Change"),
        ("escape", "cancel", "Back"),
    ]

    def __init__(self, plan: JobPlan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan
        self.draft_settings: Settings = plan.settings

    def _rows(self) -> list[tuple[str, str, str, bool]]:
        s = self.draft_settings
        video = s.mode == "video"
        rows = [("mode", "format", label_of(MODES, s.mode), True)]
        if video:
            rows += [
                ("res", "quality", label_of(RESOLUTIONS, s.res), True),
                ("codec", "encoding", label_of(VIDEO_CODECS, s.codec), True),
                ("container", "container", label_of(CONTAINERS, s.container), True),
            ]
        else:
            rows.append(("audio_format", "format",
                         label_of([("source", "keep source"), ("wav", "wav"),
                                   ("flac", "flac"), ("m4a", "m4a · aac"),
                                   ("mp3", "mp3"), ("opus", "opus")],
                                  s.audio_format), True))
            if is_lossy(s.audio_format):
                rows.append(("audio_bitrate", "bitrate", s.audio_bitrate, True))
        if self.plan.clip:
            rows.append(("_clip", "clip", self.plan.clip.label(), False))
        return rows

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="REVIEW", id="header")
        with Container(id="screen-body"):
            count = len(self.plan.urls)
            what = "1 link" if count == 1 else f"{count} links"
            title = self.plan.metadata[0].title if self.plan.metadata else ""
            yield Static(f"{what}   {title}", id="review-title")
            yield Static(str(self.plan.destination), id="review-destination")
            if self.plan.modifiers:
                yield Static(
                    "FROM YOUR REQUEST   " + "  ".join(self.plan.modifiers),
                    id="review-modifiers",
                )
            yield OptionList(*self._build_options(), id="review-rows")
        yield MinimumSizeGuard()
        yield ContextFooter(
            hints=(("↑↓", "move"), ("←→", "change"), ("enter", "download"),
                   ("esc", "back")),
            id="footer",
        )

    def _build_options(self) -> list[Option]:
        options = [Option(f"{label:<14} {value}", id=f"row-{key}")
                   for key, label, value, _editable in self._rows()]
        options.append(Option("Download", id=DOWNLOAD_OPTION_ID))
        return options

    def on_mount(self) -> None:
        option_list = self.query_one("#review-rows", OptionList)
        # Download is the last real option; Separator doesn't count toward index.
        option_list.highlighted = option_list.option_count - 1
        option_list.focus()

    def _refresh_rows(self) -> None:
        option_list = self.query_one("#review-rows", OptionList)
        highlighted = option_list.highlighted
        option_list.clear_options()
        for option in self._build_options():
            option_list.add_option(option)
        option_list.highlighted = highlighted

    def _highlighted_key(self) -> str | None:
        option_list = self.query_one("#review-rows", OptionList)
        index = option_list.highlighted
        if index is None:
            return None
        rows = self._rows()
        if index < len(rows):
            return rows[index][0]
        return None

    def _cycle(self, step: int) -> None:
        key = self._highlighted_key()
        if key is None or key == "_clip":
            return
        self.draft_settings = cycle_field(self.draft_settings, key, step)
        self._refresh_rows()

    def action_cycle_left(self) -> None:
        self._cycle(-1)

    def action_cycle_right(self) -> None:
        self._cycle(1)

    @on(OptionList.OptionSelected, "#review-rows")
    def _option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == DOWNLOAD_OPTION_ID:
            self._confirm()
            return
        self._cycle(1)

    def _confirm(self) -> None:
        plan = replace(self.plan, settings=self.draft_settings)
        self.post_message(ReviewConfirmed(plan))

    def action_cancel(self) -> None:
        self.app.pop_screen()
