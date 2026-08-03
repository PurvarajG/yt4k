# Usable Textual CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace yt4k's fragile hand-rendered interactive UI with a mandatory-folder-first, keyboard-first Textual app while preserving the existing one-shot CLI and download behavior.

**Architecture:** Extract domain and subprocess logic from `yt4k.py` into a typed package, then place one Textual application above those stable interfaces. Interactive and one-shot modes share settings, parsing, planning, and job execution; only presentation differs.

**Tech Stack:** Python 3.10+, Textual, argparse, dataclasses, subprocess process groups, pytest, Textual Pilot, and pseudo-terminal integration tests.

## Global Constraints

- Treat current uncommitted changes in `README.md`, `install.sh`, and `yt4k.py` as user-owned. Never reset, restore, discard, or overwrite them wholesale.
- Approved specification: `docs/superpowers/specs/2026-08-03-usable-textual-cli-design.md` at commit `70179d2`.
- Bare `yt4k` always requires destination selection before accepting a request.
- Every interactive download passes through review.
- Interactive mode uses one Textual lifecycle. No manual screen clearing, cursor positioning, or raw/cbreak input.
- Preserve public flags, natural-language syntax, configuration path, output defaults, recent folders, and one-shot exit behavior.
- Core/job modules never import Textual or emit ANSI UI. Screens/widgets never invoke subprocesses or persist config directly.
- Minimum size is 40×12. Smaller terminals show one resize message without losing state.
- Support macOS and Linux on Python 3.10+. Windows is out of scope.
- Work test-first and make one focused commit per task.

## Target Structure

```text
yt4k.py
yt4k/{__init__,models,settings,parsing,planning,jobs}.py
yt4k/cli/{__init__,app}.py
yt4k/cli/theme.tcss
yt4k/cli/screens/{__init__,destination,home,review,download,settings,help}.py
yt4k/cli/widgets/{__init__,common,destination,request,progress}.py
tests/{conftest,test_settings,test_parsing,test_planning,test_jobs}.py
tests/{test_cli_destination,test_cli_home_review,test_cli_download}.py
tests/{test_cli_responsive,test_entrypoint,test_terminal_lifecycle}.py
requirements.txt
requirements-dev.txt
```

---

### Task 1: Freeze public behavior and establish tests

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `tests/conftest.py`, `tests/test_entrypoint.py`
- Modify: `install.sh` using hunk-level edits only

**Interfaces:**
- Produces: `python3 -m pytest -q` and an isolated `run_cli` fixture.
- Consumes: current `yt4k.py` CLI behavior.

- [ ] **Step 1: Inspect and protect user changes**

Run `git status --short` and `git diff -- README.md install.sh yt4k.py`. Keep these diffs visible. Do not use `git checkout`, `git restore`, or `git reset`.

- [ ] **Step 2: Add dependencies**

Create `requirements.txt` with `textual>=1.0,<2` and `requirements-dev.txt` with `-r requirements.txt` plus `pytest>=8,<9`. Verify Textual's currently supported stable major against official docs before installation; update the bound only if the APIs in this plan require the stable major, and record why.

- [ ] **Step 3: Add the isolated CLI fixture**

`run_cli(tmp_path, *args)` must invoke `[sys.executable, ROOT / "yt4k.py", *args]`, capture text output, and set `HOME`, `XDG_CONFIG_HOME`, and `NO_COLOR=1` so tests never touch real settings.

- [ ] **Step 4: Characterize one-shot behavior**

Add tests equivalent to:

```python
def test_explain_parses_clip_and_quality(run_cli):
    result = run_cli("https://youtu.be/example", "1:20-3:45", "1080p", "--explain")
    assert result.returncode == 0
    assert "1080p" in result.stdout

def test_output_override_is_session_only(run_cli, tmp_path):
    result = run_cli("https://youtu.be/example", "--explain", "-o", str(tmp_path / "clips"))
    assert result.returncode == 0
    assert "this run only" in result.stdout

def test_words_without_url_are_rejected(run_cli):
    result = run_cli("first", "30s")
    assert result.returncode == 2
    assert "no URL found" in result.stderr
```

Cover every README one-shot example with `--explain`; no test downloads media.

- [ ] **Step 5: Run the baseline**

Run `python3 -m pytest tests/test_entrypoint.py -q`. Expected: PASS against the current script.

- [ ] **Step 6: Extend, do not replace, `install.sh`**

Preserve its existing launcher and legacy-copy cleanup. Install `requirements.txt` with the validated interpreter only when `python3 -c 'import textual'` fails. Emit a specific error if pip fails.

- [ ] **Step 7: Verify and commit**

Run `python3 -m pytest tests/test_entrypoint.py -q` and `git diff --check`. Stage new files plus only the intended `install.sh` hunk via `git add -p install.sh`. Commit `test: freeze one-shot CLI behavior`.

---

### Task 2: Add typed settings and safe migration

**Files:**
- Create: `yt4k/__init__.py`, `yt4k/models.py`, `yt4k/settings.py`, `tests/test_settings.py`
- Modify: `yt4k.py`

**Interfaces:**
- Produces: `Settings`, `SessionState`, `ConfigNotice`, `SettingsStore`, `validate_destination`, `remember_destination`.

- [ ] **Step 1: Write failing settings tests**

Cover defaults, valid legacy JSON, unknown keys, invalid enum/range fallback, recent-folder dedupe/cap six, atomic save, invalid JSON backup, missing-directory creation, non-directory rejection, and unwritable-folder rejection.

- [ ] **Step 2: Implement exact models**

```python
@dataclass(frozen=True)
class Settings:
    mode: Literal["video", "audio"] = "video"
    res: int = 2160
    codec: str = "source"
    container: str = "auto"
    crf: int = 18
    preset: str = "slow"
    hardware: bool = False
    audio_format: str = "m4a"
    audio_bitrate: str = "192k"
    keep_source: bool = False
    clip_precise: bool = True
    output_dir: str = "~/Downloads/YouTube 4K"
    recent_dirs: tuple[str, ...] = ()

@dataclass
class SessionState:
    settings: Settings
    destination: Path | None = None
    request_draft: str = ""
    results: list["JobResult"] = field(default_factory=list)
```

Also define `ConfigNotice(message, backup_path)`, `Yt4kError`, and `ValidationError(field, message)`.

- [ ] **Step 3: Implement settings service**

`SettingsStore.load() -> tuple[Settings, ConfigNotice | None]` merges recognized keys, validates values, converts recents to a tuple, and renames invalid JSON to `config.json.invalid-YYYYMMDD-HHMMSS`. `save(settings)` writes a sibling temporary file then uses `os.replace`.

`validate_destination(raw, create=True) -> Path` expands `~`, rejects empty/existing-file paths, creates missing directories, and verifies writability with a temporary file inside the target. `remember_destination` deduplicates most-recent-first and caps at six.

- [ ] **Step 4: Adapt entrypoint state**

Replace mutable dict/global settings operations with `Settings`, explicit destination arguments, and `dataclasses.replace`. Preserve current output and flag precedence.

- [ ] **Step 5: Verify and commit**

Run `python3 -m pytest tests/test_settings.py tests/test_entrypoint.py -q`. Commit `refactor: add typed settings and safe config migration`.

---

### Task 3: Extract parsing and immutable planning

**Files:**
- Create: `yt4k/parsing.py`, `yt4k/planning.py`, `tests/test_parsing.py`, `tests/test_planning.py`
- Modify: `yt4k.py`

**Interfaces:**
- Produces: `Clip`, `ParsedRequest`, `MediaMetadata`, `JobPlan`, `parse_request`, `parse_clip`, `normalize_metadata`, `build_job_plan`.

- [ ] **Step 1: Characterize parsing**

Parametrize every documented time form and format word. Cover multiple URLs, audio overriding video fields, re-encode wording, reversed clips, start/end edges, and explicit CLI flags winning over words.

- [ ] **Step 2: Implement result contracts**

```python
@dataclass(frozen=True)
class ParsedRequest:
    raw: str
    urls: tuple[str, ...]
    settings: Settings
    clip: Clip | None
    modifiers: tuple[str, ...]

@dataclass(frozen=True)
class MediaMetadata:
    url: str
    title: str
    channel: str | None
    duration: float | None
    raw: Mapping[str, object] = field(repr=False)

@dataclass(frozen=True)
class JobPlan:
    urls: tuple[str, ...]
    destination: Path
    settings: Settings
    clip: Clip | None
    modifiers: tuple[str, ...]
    metadata: tuple[MediaMetadata, ...]
```

- [ ] **Step 3: Extract without redesigning behavior**

Move timestamp, clip, intent, URL, and metadata normalization logic from `yt4k.py`. Replace settings patch mutation with `dataclasses.replace`. Planning validates URL/metadata alignment and clip bounds but executes no process.

- [ ] **Step 4: Preserve one-shot semantics**

Switch `yt4k.py` to shared parsing. Keep `--explain` offline. Preserve argparse error text and explicit-flag precedence.

- [ ] **Step 5: Verify and commit**

Run `python3 -m pytest tests/test_parsing.py tests/test_planning.py tests/test_entrypoint.py -q`. Commit `refactor: extract request parsing and job planning`.

---

### Task 4: Emit structured job events and support cancellation

**Files:**
- Create: `yt4k/jobs.py`, `tests/test_jobs.py`
- Modify: `yt4k/models.py`, `yt4k.py`

**Interfaces:**
- Produces: `JobRunner.run(plan, emit, cancel)`, `CancellationToken.cancel()`, `ProgressEvent`, `JobResult`.

- [ ] **Step 1: Define exact event types**

```python
class JobStage(str, Enum):
    METADATA = "metadata"
    DOWNLOADING = "downloading"
    CLIPPING = "clipping"
    REMUXING = "remuxing"
    ENCODING = "encoding"
    FINALIZING = "finalizing"

@dataclass(frozen=True)
class ProgressEvent:
    item_index: int
    item_count: int
    stage: JobStage
    fraction: float | None
    downloaded_bytes: float | None = None
    total_bytes: float | None = None
    speed: float | None = None
    eta: float | None = None
    message: str = ""

@dataclass(frozen=True)
class JobResult:
    url: str
    status: Literal["success", "failed", "cancelled"]
    output_path: Path | None
    message: str
    technical_detail: str = ""
```

- [ ] **Step 2: Write fake-process tests**

Build an injected fake `Popen` factory. Test yt-dlp progress, ffmpeg `out_time`, stderr tails, success, failure, batch continuation, SIGTERM, grace-period SIGKILL, and cleanup limited to the current temp directory. No real tools run.

- [ ] **Step 3: Implement cancellation-safe processes**

Use `start_new_session=True`. `CancellationToken` wraps `threading.Event`. On cancellation, call `os.killpg(proc.pid, SIGTERM)`, wait a bounded grace period, then `SIGKILL`. Never signal a process or remove a path not created by this runner.

- [ ] **Step 4: Port engine logic**

Move metadata fetch, probing, format construction, yt-dlp fetch, clips, remux, transcode, audio conversion, uniqueness, and final probing. Replace `print`, `Bar`, `VERBOSE`, and `die` with events or typed exceptions. Preserve command arguments.

- [ ] **Step 5: Add a plain one-shot presenter**

Convert events to current CLI output in `yt4k.py`; honor `--verbose`. This is the only non-Textual progress printer.

- [ ] **Step 6: Verify and commit**

Run `python3 -m pytest tests/test_jobs.py tests/test_entrypoint.py -q`. Commit `refactor: emit structured download progress events`.

---

### Task 5: Build the Textual shell and theme

**Files:**
- Create: `yt4k/cli/app.py`, `yt4k/cli/theme.tcss`, common package `__init__.py` files, `yt4k/cli/widgets/common.py`, `tests/test_cli_responsive.py`

**Interfaces:**
- Produces: `Yt4kApp(state, store, runner)`, `WorkbenchHeader`, `ContextFooter`, `MinimumSizeGuard`.

- [ ] **Step 1: Write Pilot lifecycle tests**

Use `async with app.run_test(size=(80, 24)) as pilot`. Assert destination mounts first. At 39×11 only `#resize-message` is visible; resizing to 80×24 restores the unchanged active screen.

- [ ] **Step 2: Implement app ownership**

`Yt4kApp` owns `SessionState`, `SettingsStore`, injected `JobRunner`, screen routing, workers, and final summary. Set `CSS_PATH = "theme.tcss"`. Do not write escape sequences.

- [ ] **Step 3: Implement common widgets**

Header: one-line `YT4K`, screen label, optional step/status. Footer: ordered `(key, action)` pairs valid only on the current screen. Size guard: overlays a message below 40×12 without remounting state.

- [ ] **Step 4: Implement focused-workbench TCSS**

Use restrained red branding/errors, cyan focus/selection, neutral surfaces, strong contrast, one-cell borders, and no ASCII logo/cards. Add narrow/short classes managed by resize events. Apply a monochrome class under `NO_COLOR`.

- [ ] **Step 5: Verify and commit**

Run responsive tests at 40×12, 60×18, 80×24, and 120×36. Commit `feat: add Textual workbench application shell`.

---

### Task 6: Add mandatory destination and home screens

**Files:**
- Create: `yt4k/cli/screens/destination.py`, `home.py`; widgets `destination.py`, `request.py`; tests `test_cli_destination.py`, `test_cli_home_review.py`
- Modify: `yt4k/cli/app.py`

**Interfaces:**
- Produces: `DestinationChosen(path, make_default)`, `RequestSubmitted(raw)`, `DestinationScreen`, `HomeScreen`.

- [ ] **Step 1: Test destination behavior**

Cover default focus, recent ordering, arrows, Enter session-only, `D` persist-default, custom path editing/paste, create missing, invalid error/focus, Escape exit, and prohibition on home when destination is `None`.

- [ ] **Step 2: Implement destination selection**

Compose saved default, deduplicated recents, and custom path using native Textual focus/list/input controls. Show marker plus `DEFAULT`/`RECENT`. Validate before posting `DestinationChosen`.

- [ ] **Step 3: Test home behavior**

Assert request input focus, visible destination/settings, inline invalid-request error, `F` destination return with draft preserved, and bounded secondary results.

- [ ] **Step 4: Implement home**

Render compact header, destination/settings context, request input, bounded session results, contextual footer. Do not add an empty queue, tutorial, examples grid, dashboard cards, or command palette. Widgets emit intent only.

- [ ] **Step 5: Route state**

Destination choice updates session and persistence through the store. Request submission stores exact draft, parses, reports field errors, then retrieves metadata asynchronously before review.

- [ ] **Step 6: Verify and commit**

Run destination/home tests. Commit `feat: add mandatory destination and request screens`.

---

### Task 7: Add review, settings, and help

**Files:**
- Create: `yt4k/cli/screens/review.py`, `settings.py`, `help.py`
- Expand: `tests/test_cli_home_review.py`
- Modify: `yt4k/cli/app.py`

**Interfaces:**
- Produces: `ReviewConfirmed(plan)`, `SettingsSaved(settings)`, and three screens.

- [ ] **Step 1: Test review contract**

Every valid request routes to review. Assert metadata/destination/modifiers, mode-relevant fields, focused Download action, local draft edits, Escape preserving request, and one immutable plan emitted on confirmation.

- [ ] **Step 2: Implement review**

Use semantic rows plus one primary Download button. Video shows quality/codec/container; audio shows format and lossy bitrate. Clip appears only when present. Label parsed modifiers `FROM YOUR REQUEST`. State persistence consequences.

- [ ] **Step 3: Test and implement settings**

Use native `Select`, `Switch`, and `Input`. Irrelevant fields are absent. Edit a local immutable draft; save validates and persists once; Escape discards it.

- [ ] **Step 4: Implement help**

Move keys/syntax into structured, searchable, scrollable sections. Escape pops without state loss.

- [ ] **Step 5: Verify and commit**

Run `python3 -m pytest tests/test_cli_home_review.py -q`. Commit `feat: add download review settings and help`.

---

### Task 8: Integrate progress, cancellation, and recovery

**Files:**
- Create: `yt4k/cli/screens/download.py`, `yt4k/cli/widgets/progress.py`, `tests/test_cli_download.py`
- Modify: `yt4k/cli/app.py`

**Interfaces:**
- Consumes: `JobRunner`, `CancellationToken`, `ProgressEvent`, `JobResult`.
- Produces: `DownloadScreen`, `ProgressStatus`, result actions, worker integration.

- [ ] **Step 1: Write tests with an injected fake runner**

Cover stage/progress/speed/ETA, unknown total, batch position, bounded log, success, failure details/retry/edit, first Ctrl+C cancellation, second Ctrl+C forced exit, and usability after cancellation.

- [ ] **Step 2: Implement progress UI**

Keep title/URL, stage, progress, bytes, speed, ETA, and batch position in the primary visible region. Technical events go in a bounded scroll log. Pair colour with text/symbols.

- [ ] **Step 3: Integrate a worker safely**

Run `JobRunner.run` in `@work(thread=True, exclusive=True)`. Transfer immutable events with `call_from_thread` or posted messages. Never mutate widgets from the worker. Block duplicate confirmation.

- [ ] **Step 4: Implement recovery**

First Ctrl+C sets cancellation and status. Second triggers forced cleanup then app exit. Append immutable results; returning home keeps destination and clears only a completed draft.

- [ ] **Step 5: Verify and commit**

Run `python3 -m pytest tests/test_cli_download.py tests/test_jobs.py -q`. Commit `feat: add cancellable Textual download progress`.

---

### Task 9: Switch entrypoint, remove legacy TUI, verify terminal lifecycle

**Files:**
- Modify: `yt4k.py`, `README.md`; modify `install.sh` only for verified integration defects
- Create: `tests/test_terminal_lifecycle.py`
- Expand: `tests/test_entrypoint.py`

**Interfaces:**
- Produces: final interactive and one-shot commands.

- [ ] **Step 1: Write pseudo-terminal lifecycle test**

Use `pty.openpty()` with isolated config. Launch bare yt4k, select default, exit, and assert exit 0, restored termios/cursor, no echoed arrow sequence, no repeated frames, and no long newline-only gaps. Keep assertions semantic enough for Textual rendering.

- [ ] **Step 2: Replace interactive dispatch**

Lazy-import `Yt4kApp` only when no URL is supplied and stdin is a TTY. Construct store/state/runner, run once, and print one summary line. One-shot parsing and `--explain` must not import Textual.

- [ ] **Step 3: Delete obsolete code after tests pass**

Remove manual width/height/ANSI clipping, `Bar`, `KeyMode`, `read_key`, alternate-screen/clear helpers, ASCII logo, hand-built screens, pagination, and session loop. Retain only tested plain one-shot presentation.

- [ ] **Step 4: Reconcile README without losing user work**

Document mandatory folder, focused workbench, review, cancellation, Textual, installer, and one-shot compatibility. Remove the ASCII-logo screenshot and obsolete dashboard/palette copy. Preserve and reconcile the user's launcher/update/session-folder changes.

- [ ] **Step 5: Run complete verification**

Run:

```bash
python3 -m pytest -q
python3 yt4k.py --help
python3 yt4k.py "https://youtu.be/example" "first 30s in 1080p mp4" --explain
python3 -m compileall -q yt4k.py yt4k
git diff --check
```

Expected: all pass without network access.

- [ ] **Step 6: Manual terminal smoke**

Check default/recent/custom folders, 40×12 through 120×36 resize, request review, fake-runner progress/cancel, restored prompt/cursor/echo/scrollback. Use real download/network only with explicit authorization.

- [ ] **Step 7: Audit and commit**

Run `git diff -- README.md install.sh yt4k.py` and explicitly verify pre-existing user changes survived. Stage intended hunks only. Commit `feat: replace interactive CLI with Textual workbench`.

---

### Task 10: Final acceptance audit

**Files:** Modify only files needed for a failing acceptance criterion.

- [ ] **Step 1: Map all 11 spec acceptance criteria to evidence**

Every criterion needs an automated test and any necessary manual observation. Missing evidence means unfinished work.

- [ ] **Step 2: Search forbidden boundaries**

Run:

```bash
rg -n 'termios|tty\.setcbreak|\\033\[2J|\\033\[\?1049|def clear|class KeyMode|def read_key|LOGO = ' yt4k.py yt4k
rg -n 'subprocess\.' yt4k/cli
rg -n 'from textual|import textual' yt4k/models.py yt4k/settings.py yt4k/parsing.py yt4k/planning.py yt4k/jobs.py
```

Expected: no manual TUI code, no subprocess use in CLI, no Textual imports in core/jobs.

- [ ] **Step 3: Prove isolation**

Run `python3 -m pytest -q && python3 -m pytest -q`. Both runs must pass.

- [ ] **Step 4: Commit only acceptance fixes**

If needed, commit `fix: satisfy Textual CLI acceptance audit`; do not create an empty commit.

- [ ] **Step 5: Report evidence**

Report test count, commands, terminal sizes, one-shot compatibility, lifecycle result, limitations, and commit SHAs. Do not claim completion while any criterion lacks evidence.
