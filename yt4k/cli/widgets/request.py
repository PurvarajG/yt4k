from __future__ import annotations

from ...models import JobResult

STATUS_MARKS = {"success": "✓", "failed": "✗", "cancelled": "•"}


def format_result(result: JobResult) -> str:
    return f"{STATUS_MARKS[result.status]} {result.message}"


def format_results(results: list[JobResult], limit: int = 5) -> str:
    return "\n".join(format_result(r) for r in results[-limit:])


def context_line(destination, settings) -> str:
    mode = "audio only" if settings.mode == "audio" else f"video {settings.res or 'best'}"
    return f"{destination}   ·   {mode}"
