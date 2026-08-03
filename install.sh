#!/usr/bin/env bash
# Installs yt4k: puts a `yt4k` launcher on your PATH at ~/.local/bin/yt4k that
# runs the script straight out of this folder. Safe to re-run to update.
#
# Earlier versions copied the script to ~/yt4k.py and ran that instead, which
# left two copies to keep in step — and edits to the repo did nothing until
# you re-ran this. The launcher now points here, so this folder is the one
# and only copy: keep it where it is.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"

echo "Installing yt4k..."
mkdir -p "$BIN_DIR"

install_macos_deps() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew not found. Install it from https://brew.sh, then re-run this script." >&2
    exit 1
  fi
  for pkg in yt-dlp ffmpeg; do
    if ! command -v "$pkg" >/dev/null 2>&1; then
      echo "Installing $pkg via Homebrew..."
      brew install "$pkg"
    fi
  done
}

install_linux_deps() {
  if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "Installing yt-dlp via pip..."
    python3 -m pip install --user -U yt-dlp
  fi
  if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg not found. Install it with your distro's package manager, e.g.:"
    echo "  sudo apt install ffmpeg"
    exit 1
  fi
}

case "$(uname -s)" in
  Darwin) install_macos_deps ;;
  Linux)  install_linux_deps ;;
  *)
    echo "Unsupported OS: $(uname -s). yt4k needs a POSIX shell, yt-dlp, and ffmpeg." >&2
    exit 1
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found on PATH. Install Python 3.10+ and re-run this script." >&2
  exit 1
fi

py_ok=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
if [ "$py_ok" != "1" ]; then
  echo "yt4k needs Python 3.10+, found $(python3 --version)." >&2
  exit 1
fi

# yt4k's own Python deps (Textual) live in a dedicated venv rather than the
# system/Homebrew/conda python3 — many of those refuse "pip install" outright
# (PEP 668's externally-managed-environment guard), and even where they don't,
# installing into whatever python3 happens to be first on PATH is fragile:
# it's a different interpreter in every shell and breaks silently when that
# changes. The launcher below always runs yt4k.py with this venv's python3.
VENV_DIR="$HOME/.local/share/yt4k/venv"

if [ ! -x "$VENV_DIR/bin/python3" ]; then
  echo "Creating yt4k's Python environment at $VENV_DIR..."
  if ! python3 -m venv "$VENV_DIR"; then
    echo "Could not create a venv at $VENV_DIR. Check your python3 install and re-run." >&2
    exit 1
  fi
fi

if ! "$VENV_DIR/bin/python3" -c 'import textual' >/dev/null 2>&1; then
  echo "Installing Textual workbench dependency..."
  if ! "$VENV_DIR/bin/python3" -m pip install --quiet --upgrade pip ||
     ! "$VENV_DIR/bin/python3" -m pip install --quiet -r "$REPO_DIR/requirements.txt"; then
    echo "Could not install Textual into $VENV_DIR. Check pip/network access and re-run." >&2
    exit 1
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
