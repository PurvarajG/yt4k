# Usable Textual CLI Design

## Purpose

Rebuild yt4k's interactive mode as a reliable, keyboard-first full-screen application. The common workflow must be obvious, fast, and safe: choose a destination, paste a request, review what yt4k understood, download, and repeat. Visual character supports that workflow but never competes with it.

The existing one-shot command-line interface, natural-language request syntax, download behavior, and saved settings remain compatible.

## Product Principles

1. Usability is the acceptance gate. A visually polished screen that obscures the next action fails.
2. Folder selection is mandatory at the beginning of every interactive session.
3. The interactive application owns the terminal for its entire lifetime and restores it exactly once on exit.
4. Each screen has one obvious focus and one primary action.
5. Every download is reviewed before work begins.
6. The interface is keyboard-first. Mouse support is optional convenience.
7. Errors explain what happened and offer a direct recovery action.
8. The UI renders structured application state; it never parses subprocess output or writes ANSI sequences itself.

## Supported Modes

### Interactive mode

Running `yt4k` without a URL starts a Textual application on the terminal's alternate screen. Textual exclusively owns rendering, keyboard input, cursor state, focus, resizing, and screen transitions.

### One-shot mode

Running `yt4k URL ...` remains a conventional `argparse` command. It does not start Textual and preserves current flags, natural-language modifiers, standard output behavior, and exit codes.

### Non-interactive input

When standard input is not a terminal and no URL is supplied, yt4k returns the existing argument error. It does not attempt to start Textual.

## Primary User Flow

1. Bare `yt4k` enters one Textual application.
2. The destination screen requires the user to choose the saved default, a recent folder, or a custom path.
3. The home screen focuses the request input and keeps the chosen destination and saved format defaults visible.
4. The user pastes one or more URLs, optionally followed by natural-language settings or a clip range.
5. yt4k parses the request and retrieves enough metadata to produce a trustworthy review.
6. The review screen shows title/channel when available, destination, media type, quality, codec, container or audio format, clip range, and parsed modifiers.
7. `Enter` confirms and starts the job. Arrow-key editing changes a review field. `Esc` returns without downloading.
8. The download screen shows the active item, batch position, stage, progress, speed, ETA, and cancellation status.
9. Completion returns to the home screen and adds one concise success, failure, or cancellation result to session history.
10. Quitting restores the original terminal and prints one summary line containing the number of completed files and destination.

## Screen Designs

### Destination screen

This is always the first screen in an interactive session.

- Heading: `Where should this session save?`
- Supporting copy: one short sentence explaining that the saved default is ready and recent folders are available.
- Rows: saved default, up to the configured recent-folder limit, and `Enter another path`.
- Labels: `DEFAULT` and `RECENT` are mutually exclusive metadata. `CURRENT SESSION` is used only after a session destination exists.
- Selection: one cyan focus/selection treatment spanning the active row.
- `Enter`: validate, create if necessary, and use the highlighted folder for this session.
- `D`: validate, create if necessary, use the folder for this session, and persist it as the new default.
- `Esc`: exit yt4k because no session destination has been chosen.
- A custom path opens a Textual input supporting normal editing, paste, selection, Home/End, and submission.
- Empty, inaccessible, or unwritable paths stay on this screen with a specific inline error and focused input.

### Home screen

- The request input is focused on entry.
- The chosen destination and current download defaults remain visible near the input.
- Session history shows only completed attempts from the current run and is secondary to the input.
- The screen does not contain an empty queue, tutorial paragraphs, example grids, decorative cards, or a large ASCII logo.
- `F` reopens destination selection without ending the session.
- `S` opens settings, `?` opens help, and `Esc` requests exit.
- The footer exposes only shortcuts valid on this screen.

### Review screen

- Opens for every valid request before downloading.
- Shows the URL count and metadata for the current item or batch.
- Shows destination, video/audio mode, resolution, codec, container or audio format, bitrate where applicable, clip range, and encoding behavior.
- Parsed natural-language modifiers are explicitly identified so incorrect interpretation is visible.
- The primary action is `Download`; it is focused by default.
- Arrow keys navigate editable rows. `Enter` on a row edits that value; `Enter` on `Download` confirms.
- `Esc` returns to the home screen with the request preserved.
- Settings changed during review apply to this job and become saved defaults only where current behavior already does so. The UI states when a change will persist.

### Download screen

- Shows title or URL, channel when known, batch position, stage, progress, downloaded size, total size when known, speed, and ETA.
- Progress updates are driven by typed events from the job engine.
- Completed log lines are bounded and scrollable; they cannot push the primary status off-screen.
- `Ctrl+C` initiates cancellation and changes the primary status to `Cancelling…`.
- A second `Ctrl+C` during forced cleanup exits after restoring the terminal.
- Success, failure, and cancellation each offer an obvious return-home action. Failure also offers retry and edit-settings actions.

### Settings screen

- Uses Textual select, switch, and input controls rather than hand-built arrow cycling.
- Fields irrelevant to the selected media mode are removed from layout instead of shown as disabled rows.
- Field descriptions explain consequences such as re-encoding, quality, speed, and file size.
- Saving validates all values atomically and persists once.
- Cancelling discards the draft completely.

### Help screen

- Provides searchable, scrollable keyboard and request-syntax reference.
- It is one Textual screen, not manually paginated output.
- `Esc` returns to the previous screen and preserves its state.

## Visual Direction: Focused Workbench

The selected direction is a compact workbench, not a dashboard and not a retro terminal performance.

- Branding is a one-line `YT4K` wordmark. Red is reserved for brand and destructive/error states where semantics remain clear.
- Cyan marks focus and selection.
- Neutral surfaces and high-contrast text carry the interface.
- Uppercase labels are limited to compact metadata such as `DEFAULT`, `RECENT`, and step/status labels.
- Borders organize interactive regions; cards are not used as decoration.
- Footer hints pair a key with a short action and change by screen.
- Animation is limited to useful progress and loading feedback.
- Copy is direct utility language. No slogans, faux-industrial terminology, or repeated instructions.

## Responsive Behavior

The application must work at a minimum supported terminal size of 40 columns by 12 rows. Below that size it renders a single clear resize message and preserves state until sufficient space returns.

- At 80×24 and larger, screens use the full focused-workbench composition.
- At narrow widths, metadata moves beneath its associated value, paths use middle truncation where the leaf and root both matter, and footer hints wrap or reduce to primary actions.
- At short heights, supporting copy and the wordmark subtitle disappear before any interactive control.
- The destination list and session history become scrollable when needed.
- The request input, selected destination, primary action, and active progress status never leave the visible viewport.
- Resizing never resets navigation, typed input, draft settings, or job state.

## Architecture

### Entry point

`yt4k.py` becomes a thin compatibility entry point. It parses arguments, applies explicit flag precedence, and dispatches to one-shot execution or the Textual app.

### Core package

`yt4k/core.py` owns domain behavior: settings models and migration, request parsing, clip parsing, destination history, path validation, metadata normalization, job planning, filename decisions, and domain exceptions. It contains no Textual imports and emits no ANSI codes.

### Job engine

`yt4k/jobs.py` owns yt-dlp and ffmpeg subprocess construction, execution, progress parsing, cancellation, cleanup, and final result creation. It exposes structured events and accepts a cancellation signal. It does not print UI output.

### Interactive package

`yt4k/cli/app.py` owns application state, screen routing, global actions, worker lifecycle, and terminal restoration through Textual.

`yt4k/cli/screens/` contains destination, home, review, download, settings, and help screens. Each screen consumes explicit state and emits typed user intents.

`yt4k/cli/widgets/` contains reusable destination rows, request input, settings rows, progress status, result rows, and contextual footer hints.

`yt4k/cli/theme.tcss` defines the focused-workbench visual system and responsive breakpoints.

### Boundary rules

- Core and job modules never import Textual.
- Screens never invoke `subprocess` directly.
- Widgets do not write configuration files or mutate global session variables.
- Subprocess output is parsed once by the job engine into typed events.
- Configuration persistence occurs through one core settings service.
- One-shot mode and interactive mode use the same request parser, job planner, and job engine.

## State and Data Flow

The application owns a session state containing saved settings, selected session destination, recent destinations, current request draft, current review plan, active job state, and session results.

Destination selection emits a validated path intent. The app updates session state and routes to home. Request submission calls the shared parser and planner, then routes a valid plan to review or returns a field-level error to home. Confirmation starts a Textual worker that consumes job events and updates download state. Completion appends an immutable result and routes home. Settings edits operate on a draft and replace saved settings only after validation and persistence succeed.

## Error Handling and Recovery

- Path errors name the path and whether creation, access, or writing failed.
- Request errors distinguish missing URL, unsupported syntax, invalid clip range, and conflicting settings.
- Metadata errors distinguish invalid/unavailable URLs, private content, network failure, and likely outdated yt-dlp where evidence allows.
- Job errors preserve a short user-facing message and expandable technical details.
- Configuration parse failure moves the invalid file to a timestamped backup, loads defaults, and informs the user without blocking startup.
- An unexpected exception exits Textual before printing its traceback.
- All subprocesses run in their own process group. Cancellation terminates the group, waits for a bounded grace period, escalates if necessary, and removes only verified temporary artifacts created by the current job.

## Accessibility and Terminal Compatibility

- All actions are reachable by keyboard with visible focus.
- Selected state uses shape and placement as well as colour.
- `NO_COLOR` and low-colour terminals receive a readable monochrome hierarchy.
- Text never relies on red/green alone for success and failure.
- Status updates use Textual's accessibility facilities where supported.
- The application does not assume a mouse, Unicode width beyond Textual's renderer, or a specific terminal font.
- macOS Terminal, iTerm2, and common Linux terminals are first-class targets.

## Compatibility and Migration

- Preserve Python 3.10+.
- Add Textual as the interactive runtime dependency and install it through the existing installer.
- Preserve existing public flags, natural-language forms, configuration location, output defaults, recent-folder behavior, and one-shot invocation.
- Move global settings/session state behind explicit models without silently changing saved values.
- Remove custom alternate-screen, cursor, clearing, raw-key, clipping, banner-budgeting, and manual pagination code after equivalent Textual behavior is verified.

## Testing Strategy

### Core tests

Unit tests cover request parsing, clip parsing, explicit flag precedence, settings validation and migration, recent-folder ordering, path validation, metadata normalization, and job planning.

### Job tests

Fake-process tests cover yt-dlp and ffmpeg command construction, progress-event parsing, success, expected failure, cancellation, escalation, temporary-file cleanup, and batch continuation. Tests do not download real media.

### Textual tests

Textual Pilot tests cover startup destination enforcement, default/recent/custom destination selection, path errors, request submission, review editing and confirmation, progress-event rendering, cancellation, retry, settings draft cancellation, help return, and exit.

Tests run at 40×12, 60×18, 80×24, and 120×36. Assertions verify that focus, primary actions, request input, selected destination, and active progress remain reachable and visible.

### Terminal lifecycle test

A pseudo-terminal integration test launches interactive mode, selects a destination, exits, and asserts that the process restores cursor visibility, terminal mode, and the original screen without leaked escape input or appended blank-screen redraws.

### CLI regression tests

Current README one-shot examples become subprocess-level regression tests for argument parsing, `--explain`, output override behavior, and error exit codes.

## Acceptance Criteria

1. Bare `yt4k` always asks for a destination before accepting a request.
2. The complete interactive session uses one Textual application and leaves no stacked frames or blank scrollback gaps.
3. A first-time user can choose a default folder, paste a URL, understand the review, start a download, and find the result without opening help.
4. Every download has a review step and an obvious cancel path.
5. All advertised keyboard actions work immediately and never leak escape sequences into an input.
6. Resizing across supported dimensions preserves state and keeps the primary action accessible.
7. Cancellation terminates child processes and leaves the application usable.
8. Unexpected failures restore the terminal before displaying diagnostics.
9. Existing one-shot commands and natural-language requests remain compatible.
10. The focused-workbench visual direction is consistent across every screen without large logos, decorative dashboards, or instruction walls.
11. Automated core, job, Textual, pseudo-terminal, and CLI regression tests pass.

## Out of Scope

- A download queue that persists across application restarts.
- Remote download management, browser integration, or a web interface.
- Mouse-only interactions.
- Replacing yt-dlp or ffmpeg.
- Redesigning natural-language syntax beyond compatibility fixes required by tests.
- Supporting Windows in this iteration; current termios-era behavior and installer targets are macOS/Linux.
