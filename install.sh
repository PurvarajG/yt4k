#!/usr/bin/env bash
# Installs fetch4k on a fresh macOS or Linux machine. Needs nothing preinstalled:
# if there's no Python 3.10+, it fetches one with uv (no sudo, no Homebrew).
#
# Everything else - Textual, yt-dlp, ffmpeg/ffprobe, and the Deno JS runtime -
# is installed into a dedicated venv at ~/.local/share/fetch4k/venv, so there's
# no Homebrew step, no apt step, and ~/.local/bin is added to your PATH for
# you. A `fetch4k` launcher goes
# in ~/.local/bin and runs the script straight out of this folder, so keep
# the folder where it is; `git pull && ./install.sh` is the update.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
VENV_DIR="$HOME/.local/share/fetch4k/venv"

echo "Installing fetch4k..."
mkdir -p "$BIN_DIR"

# Pick a Python 3.10+ to build the venv from. Use the system one when it's
# new enough; otherwise have uv download a private CPython. uv's installer
# drops a single binary in ~/.local/bin and needs no admin rights.
py_is_ok() {
  "$1" -c 'import sys, venv; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

PYTHON=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1 && py_is_ok "$candidate"; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "No Python 3.10+ found - fetching one with uv (nothing system-wide changes)..."
  UV="$(command -v uv || true)"
  [ -z "$UV" ] && [ -x "$BIN_DIR/uv" ] && UV="$BIN_DIR/uv"
  if [ -z "$UV" ]; then
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BIN_DIR" UV_NO_MODIFY_PATH=1 sh
    else
      wget -qO- https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BIN_DIR" UV_NO_MODIFY_PATH=1 sh
    fi
    UV="$BIN_DIR/uv"
  fi
  "$UV" python install 3.12
  PYTHON="$("$UV" python find 3.12)"
  if ! py_is_ok "$PYTHON"; then
    echo "Could not set up Python automatically. Install Python 3.10+ and re-run." >&2
    exit 1
  fi
fi
echo "Using $("$PYTHON" --version) at $PYTHON"

# fetch4k's dependencies live in their own venv rather than in whatever python3
# happens to be first on PATH: many system/Homebrew/conda Pythons refuse
# "pip install" outright (PEP 668's externally-managed-environment guard),
# and installing into a moving target breaks silently when that target
# changes. The launcher below always uses this venv's python3.
if [ ! -x "$VENV_DIR/bin/python3" ]; then
  rm -rf "$VENV_DIR"
  echo "Creating fetch4k's Python environment at $VENV_DIR..."
  if ! "$PYTHON" -m venv "$VENV_DIR"; then
    echo "Could not create a venv at $VENV_DIR. Check your python3 install and re-run." >&2
    exit 1
  fi
fi

echo "Installing fetch4k's dependencies (Textual, yt-dlp, ffmpeg, Deno)..."
if ! "$VENV_DIR/bin/python3" -m pip install --quiet --upgrade pip ||
   ! "$VENV_DIR/bin/python3" -m pip install --quiet --upgrade -r "$REPO_DIR/requirements.txt"; then
  echo "Could not install fetch4k's dependencies into $VENV_DIR." >&2
  echo "Check pip and network access, then re-run this script." >&2
  exit 1
fi

# static-ffmpeg fetches its binaries on first use. Do that here, where a slow
# download is expected, rather than in the middle of someone's first clip.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "Fetching ffmpeg..."
  if ! "$VENV_DIR/bin/python3" -c 'import static_ffmpeg; static_ffmpeg.add_paths()' >/dev/null 2>&1; then
    echo "Warning: could not download the bundled ffmpeg. Clipping and format" >&2
    echo "conversion will fail until this succeeds - re-run install.sh when" >&2
    echo "you have network access, or install ffmpeg yourself." >&2
  fi
fi

# YouTube signs its media URLs behind a JavaScript challenge that yt-dlp solves
# with an external JS runtime; without one, downloads fail with a 403. Deno is
# pip-installed into the venv (requirements.txt) and the launcher puts the
# venv's bin first on PATH, so yt-dlp always finds it.
if [ ! -x "$VENV_DIR/bin/deno" ]; then
  echo "Warning: Deno didn't install into the venv. YouTube downloads may fail" >&2
  echo "with a 403 unless deno or node is on your PATH." >&2
fi

cat > "$BIN_DIR/fetch4k" <<WRAP
#!/bin/sh
PATH="$VENV_DIR/bin:\$PATH" exec "$VENV_DIR/bin/python3" "$REPO_DIR/fetch4k.py" "\$@"
WRAP
chmod +x "$BIN_DIR/fetch4k"

# fetch4k used to be called yt4k. Carry the settings over and clear out the
# old launcher and venv, so there's only one command left.
OLD_CONFIG="$HOME/.config/yt4k"
NEW_CONFIG="$HOME/.config/fetch4k"
if [ -d "$OLD_CONFIG" ] && [ ! -e "$NEW_CONFIG" ]; then
  mv "$OLD_CONFIG" "$NEW_CONFIG"
  echo "Moved your yt4k settings to $NEW_CONFIG."
fi
if [ -f "$BIN_DIR/yt4k" ] && grep -qs 'yt4k.py' "$BIN_DIR/yt4k"; then
  rm -f "$BIN_DIR/yt4k"
  echo "Removed the old 'yt4k' command — it's 'fetch4k' now."
fi
rm -rf "$HOME/.local/share/yt4k"

# True when ~/yt4k.py is byte-identical to some committed version, i.e. an old
# install's copy rather than a file someone edited in place.
stray_is_a_copy() {
  local sha
  git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1 || return 1
  for sha in $(git -C "$REPO_DIR" log --all --format=%H -- yt4k.py); do
    if git -C "$REPO_DIR" show "$sha:yt4k.py" 2>/dev/null |
       cmp -s - "$HOME/yt4k.py"; then
      return 0
    fi
  done
  return 1
}

if [ -f "$HOME/yt4k.py" ] && [ "$HOME/yt4k.py" != "$REPO_DIR/fetch4k.py" ]; then
  if stray_is_a_copy; then
    rm -f "$HOME/yt4k.py"
    echo "Removed the old ~/yt4k.py copy — this folder is the only one now."
  else
    echo "Left ~/yt4k.py alone: it matches no committed version, so it may have"
    echo "edits worth keeping. Nothing runs it any more — delete it when ready."
  fi
fi

echo "Installed. Downloads land in ~/Downloads/fetch4k by default."
echo "fetch4k runs $REPO_DIR/fetch4k.py using the venv at $VENV_DIR — keep this folder where it is."

# Put ~/.local/bin on PATH in the user's shell rc, once, so `fetch4k` just works
# in new terminals.
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    case "$(basename "${SHELL:-}")" in
      zsh) RC="$HOME/.zshrc" ;;
      bash) if [ "$(uname)" = Darwin ]; then RC="$HOME/.bash_profile"; else RC="$HOME/.bashrc"; fi ;;
      *) RC="$HOME/.profile" ;;
    esac
    if ! grep -qsE '# added by (fetch4k|yt4k)' "$RC"; then
      printf '\nexport PATH="$HOME/.local/bin:$PATH"  # added by fetch4k\n' >> "$RC"
      echo "Added ~/.local/bin to your PATH in $RC."
    fi
    echo "Open a new terminal (or run: source $RC) before using fetch4k."
    ;;
esac

echo
echo "Run 'fetch4k' to start."
