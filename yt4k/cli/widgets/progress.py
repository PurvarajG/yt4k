from __future__ import annotations

from ...models import JobStage, ProgressEvent

STAGE_LABELS = {
    JobStage.METADATA: "Fetching info",
    JobStage.DOWNLOADING: "Downloading",
    JobStage.CLIPPING: "Clipping",
    JobStage.REMUXING: "Remuxing",
    JobStage.ENCODING: "Encoding",
    JobStage.FINALIZING: "Finalizing",
}


def _human_bytes(n: float | None) -> str:
    if not n:
        return "--"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit in ("B", "KB") else f"{n:.1f}{unit}"
        n /= 1024
    return "--"


def _human_time(secs: float | None) -> str:
    if secs is None or secs < 0 or secs != secs or secs == float("inf"):
        return "--:--"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def stage_label(event: ProgressEvent) -> str:
    return STAGE_LABELS[event.stage]


def status_line(event: ProgressEvent) -> str:
    if event.stage == JobStage.METADATA:
        return f"Fetching info - {event.message}"
    bits = [stage_label(event)]
    if event.fraction is not None:
        bits.append(f"{event.fraction * 100:3.0f}%")
    if event.downloaded_bytes is not None:
        bits.append(f"{_human_bytes(event.downloaded_bytes)}/{_human_bytes(event.total_bytes)}")
        if event.speed:
            bits.append(f"{_human_bytes(event.speed)}/s")
    bits.append(f"eta {_human_time(event.eta)}")
    return "  ".join(bits)


def batch_line(event: ProgressEvent) -> str:
    return f"[{event.item_index + 1}/{event.item_count}]"
