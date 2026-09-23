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
    CONTAINERS, MODES, codec_choices, cycle_choice, cycle_field,
    effective_choice, is_lossy, label_of, resolution_choices, source_codecs,
    source_heights,
)
from ... import pinterest
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
        # Only offer what these sources can actually deliver: no 4K row for a
        # 1080p clip, no AV1 row for a site that only serves H.264.
        self.resolutions = resolution_choices(source_heights(plan.metadata))
        self.codecs = codec_choices(source_codecs(plan.metadata))
        self.images_only = bool(plan.items) and all(
            (item.metadata.raw or {}).get(pinterest.IMAGES_KEY)
            for item in plan.items)

    def _choices(self, key: str) -> list | None:
        table = {"res": self.resolutions, "codec": self.codecs}.get(key)
        return [value for value, _label in table] if table else None

    def _effective(self, key: str):
        values = self._choices(key)
        fallback = {"res": 0, "codec": "source"}[key]
        return effective_choice(getattr(self.draft_settings, key), values, fallback)

    def _rows(self) -> list[tuple[str, str, str, bool]]:
        s = self.draft_settings
        if self.images_only:
            # Images are saved byte-for-byte; there is nothing to choose.
            return [("_image", "format", "image · original file", False)]
        video = s.mode == "video"
        rows = [("mode", "format", label_of(MODES, s.mode), True)]
        if video:
            rows += [
                ("res", "quality",
                 label_of(self.resolutions, self._effective("res")), True),
                ("codec", "encoding",
                 label_of(self.codecs, self._effective("codec")), True),
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
            count = len(self.plan.items)
            if self.plan.playlist_count:
                names = " · ".join(self.plan.playlist_titles)
                unavailable = (f" · {self.plan.unavailable_count} unavailable"
                               if self.plan.unavailable_count else "")
                title = f"Playlist · {names} · {count} items{unavailable}"
            else:
                what = "1 link" if count == 1 else f"{count} links"
                title = self.plan.items[0].metadata.title if self.plan.items else ""
                title = f"{what}   {title}"
            yield Static(title, id="review-title")
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
        if key is None or key.startswith("_"):
            return
        values = self._choices(key)
        if values:
            current = replace(self.draft_settings, **{key: self._effective(key)})
            self.draft_settings = cycle_choice(current, key, values, step)
        else:
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
