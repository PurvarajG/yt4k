# Playlist Downloads Design

## Goal

Accept YouTube playlist URLs in both the Textual workbench and the one-shot
command while preserving every existing format, clipping, progress,
cancellation, retry, and per-video download behavior.

## Input policy

`list=` identifies a playlist-capable YouTube URL. A pure playlist URL expands
to the whole playlist. A URL containing both `v=` and `list=` is ambiguous:
the workbench presents a small choice screen before any metadata request;
one-shot requires either `--playlist` or `--video` to choose explicitly.
Supplying both flags is an argparse error.

## Expansion boundary

`JobRunner.playlist_info()` asks yt-dlp for flat playlist JSON only. A new
playlist-planning module turns that response into ordinary plan items in
playlist order. Each item retains its original 1-based playlist ordinal,
playlist title, and an optional preflight error. Downloads themselves still
call the existing one-video engine with `--no-playlist`; this keeps stream
selection, clipping, conversion, cancellation, and errors item-scoped.

## Plan and error model

`JobPlan` stays compatible with callers using `urls` and `metadata`, and gains
per-item output metadata plus optional playlist context. Missing flat entries,
private/deleted entries without a downloadable URL, and impossible clips
are represented as failed plan items. They render in review/download results
and never prevent later items from running. A fresh per-item metadata read is
used only when a relative-end clip needs a duration absent from flat playlist
JSON; only a failed refresh makes that item fail.

## Output layout

Playlist output goes below `<destination>/<safe playlist title> [list-id]/`. Folder
names remove path separators, control characters, leading/trailing dots and
platform-reserved punctuation; an empty title becomes `Playlist`. Each media
file begins with a zero-padded playlist ordinal (`001 - ...`) so concurrent
completion cannot change visible ordering and distinct playlist items do not
collide. Repeated playlist sources receive a deterministic ` (2)` folder
suffix. The runner keeps a separate temporary directory for every item.

## User experience

Review shows playlist title and the number of entries, with an unavailable
count when known. The download screen already allocates one row per plan item;
it will show the playlist number in its row title. Retry creates a filtered
plan from failed/cancelled jobs only, preserving their original ordinals and
playlist folder. Completion and CLI status remain nonzero when any item fails.

## Validation

Tests cover URL classification, flat playlist expansion/order/unavailable
entries, safe folders and numbered outputs, per-item clip failures, no-abort
execution, retry filtering, CLI selection flags/default/explain output, and
Textual choice/review wording. Existing single-video tests remain unchanged.
