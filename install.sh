#!/usr/bin/env bash
# Installs yt4k. The only thing this needs from your machine is Python 3.10+.
#
# Everything else - Textual, yt-dlp, and ffmpeg/ffprobe - is installed into a
# dedicated venv at ~/.local/share/yt4k/venv, so there's no Homebrew step, no
# apt step, and nothing to put on your PATH by hand. A `yt4k` launcher goes
# in ~/.local/bin and runs the script straight out of this folder, so keep
# the folder where it is; `git pull && ./install.sh` is the update.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
VENV_DIR="$HOME/.local/share/yt4k/venv"

echo "Installing yt4k..."
mkdir -p "$BIN_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH. Install Python 3.10+ and re-run this script." >&2
  exit 1
fi

py_ok=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
if [ "$py_ok" != "1" ]; then
  echo "yt4k needs Python 3.10+, found $(python3 --version)." >&2
  exit 1
fi

# yt4k's dependencies live in their own venv rather than in whatever python3
# happens to be first on PATH: many system/Homebrew/conda Pythons refuse
# "pip install" outright (PEP 668's externally-managed-environment guard),
# and installing into a moving target breaks silently when that target
# changes. The launcher below always uses this venv's python3.
if [ ! -x "$VENV_DIR/bin/python3" ]; then
  echo "Creating yt4k's Python environment at $VENV_DIR..."
  if ! python3 -m venv "$VENV_DIR"; then
    echo "Could not create a venv at $VENV_DIR. Check your python3 install and re-run." >&2
    exit 1
  fi
fi

echo "Installing yt4k's dependencies (Textual, yt-dlp, ffmpeg)..."
if ! "$VENV_DIR/bin/python3" -m pip install --quiet --upgrade pip ||
   ! "$VENV_DIR/bin/python3" -m pip install --quiet --upgrade -r "$REPO_DIR/requirements.txt"; then
  echo "Could not install yt4k's dependencies into $VENV_DIR." >&2
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

cat > "$BIN_DIR/yt4k" <<WRAP
#!/bin/sh
exec "$VENV_DIR/bin/python3" "$REPO_DIR/yt4k.py" "\$@"
WRAP
chmod +x "$BIN_DIR/yt4k"

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

if [ -f "$HOME/yt4k.py" ] && [ "$HOME/yt4k.py" != "$REPO_DIR/yt4k.py" ]; then
  if stray_is_a_copy; then
    rm -f "$HOME/yt4k.py"
    echo "Removed the old ~/yt4k.py copy — this folder is the only one now."
  else
    echo "Left ~/yt4k.py alone: it matches no committed version, so it may have"
    echo "edits worth keeping. Nothing runs it any more — delete it when ready."
  fi
fi

echo "Installed. Downloads land in ~/Downloads/YouTube 4K by default."
echo "yt4k runs $REPO_DIR/yt4k.py using the venv at $VENV_DIR — keep this folder where it is."

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo
    echo "$BIN_DIR isn't on your PATH yet. Add this to your shell rc file"
    echo "(~/.zshrc or ~/.bashrc) and open a new terminal:"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

echo
echo "Run 'yt4k' to start."
