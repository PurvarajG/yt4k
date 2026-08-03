from __future__ import annotations

from pathlib import Path

from textual.widgets.option_list import Option

from ...models import Settings

CUSTOM_OPTION_ID = "opt-custom"


def build_destination_rows(settings: Settings) -> list[tuple[str, Path | None]]:
    """(label-tag, path) rows: the saved default, deduplicated recents, then
    a trailing custom-path row (path is None)."""
    default = Path(settings.output_dir).expanduser()
    rows: list[tuple[str, Path | None]] = [("DEFAULT", default)]
    seen = {default}
    for raw in settings.recent_dirs:
        path = Path(raw).expanduser()
        if path in seen:
            continue
        seen.add(path)
        rows.append(("RECENT", path))
    rows.append(("", None))
    return rows


def build_destination_options(settings: Settings) -> list[Option]:
    rows = build_destination_rows(settings)
    options = []
    for index, (tag, path) in enumerate(rows):
        if path is None:
            options.append(Option("Enter another path…", id=CUSTOM_OPTION_ID))
        else:
            label = f"{path}   {tag}" if tag else str(path)
            options.append(Option(label, id=f"opt-{index}"))
    return options
