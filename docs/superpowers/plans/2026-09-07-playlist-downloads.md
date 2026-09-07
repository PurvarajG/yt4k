# Playlist Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download YouTube playlists as independently processed, ordered jobs in the CLI and Textual workbench.

**Architecture:** Classify URLs before metadata fetches, expand playlists through yt-dlp flat JSON into normal job-plan items, and keep `JobRunner` single-video only. Plan item metadata provides safe, deterministic playlist output paths and preflight failures without changing the converter pipeline.

**Tech Stack:** Python 3.10+, yt-dlp JSON, Textual 8, pytest.

## Global Constraints

- Preserve existing single-video URLs and all conversion/download settings.
- A mixed `v=`/`list=` URL defaults to the video in one-shot mode; `--playlist` and `--video` are explicit overrides.
- Every playlist item is independently cancellable/failable and retains source order.
- Playlist names and generated paths must not permit traversal or platform-invalid path components.

---

### Task 1: Playlist classification and plan expansion

**Files:**
- Create: `yt4k/playlists.py`
- Modify: `yt4k/models.py`, `yt4k/planning.py`
- Test: `tests/test_playlists.py`, `tests/test_planning.py`

**Interfaces:**
- Produces `classify_url(url) -> URLKind`, `expand_playlist(url, raw) -> PlaylistExpansion` and `safe_playlist_name(title) -> str`.
- Produces `JobPlan.items: tuple[JobItem, ...]`, with compatibility `urls` and `metadata` properties.

- [ ] Write tests for classification, flat entry ordering, malformed entries, safe folders, and preflight-error plan items.
- [ ] Run `pytest tests/test_playlists.py tests/test_planning.py -v` and observe missing APIs fail.
- [ ] Implement immutable playlist expansion and item-centric planning.
- [ ] Re-run the targeted tests until they pass.

### Task 2: Engine output and item isolation

**Files:**
- Modify: `yt4k/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes `JobPlan.items` destination/prefix/error fields.
- Produces numbered output files below a safe playlist directory and a `JobResult` for every preflight failure.

- [ ] Write tests for numbered output paths, concurrent item directory separation, a preflight failure followed by success, and per-item unresolved tail clips.
- [ ] Run `pytest tests/test_jobs.py -v` and observe failures.
- [ ] Route each item's destination/naming through the existing audio/video functions; return failures before subprocess execution.
- [ ] Re-run engine tests until they pass.

### Task 3: CLI and Textual orchestration

**Files:**
- Modify: `yt4k.py`, `yt4k/cli/app.py`, `yt4k/cli/screens/review.py`, `yt4k/cli/screens/download.py`, `yt4k/cli/screens/home.py`
- Create: `yt4k/cli/screens/playlist_choice.py`
- Test: `tests/test_entrypoint.py`, `tests/test_cli_home_review.py`, `tests/test_cli_download.py`

**Interfaces:**
- CLI accepts `--playlist` / `--video` and sends expanded plans to `run_one_shot`.
- Workbench branches to `PlaylistChoiceScreen` only for ambiguous mixed links.
- Retry filters to failed/cancelled `JobItem` values and leaves successful files untouched.

- [ ] Write CLI and Textual tests for selection policy, review title/count, and retry filtering.
- [ ] Run the specified test modules and observe the required failures.
- [ ] Implement selection UI and filtered retry.
- [ ] Re-run targeted tests until they pass.

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`, `yt4k/cli/screens/help.py`
- Test: full suite

- [ ] Document playlist syntax, default and explicit mixed-link choices, output layout, partial-failure behavior, and clip limitation for unknown durations.
- [ ] Run `pytest -q`.
- [ ] Check `git diff --check` and review changed files against this plan.
