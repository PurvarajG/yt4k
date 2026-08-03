#!/usr/bin/env bash
# Installs yt4k: copies the script to ~/yt4k.py and puts a `yt4k` launcher
# on your PATH at ~/.local/bin/yt4k. Safe to re-run to update.
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

if ! python3 -c 'import textual' >/dev/null 2>&1; then
  echo "Installing Textual workbench dependency..."
  if ! python3 -m pip install -r "$REPO_DIR/requirements.txt"; then
    echo "Could not install Textual from $REPO_DIR/requirements.txt. Check pip/network access and re-run." >&2
    exit 1
  fi
fi

cp "$REPO_DIR/yt4k.py" "$HOME/yt4k.py"

cat > "$BIN_DIR/yt4k" <<'WRAP'
#!/bin/sh
exec python3 "$HOME/yt4k.py" "$@"
WRAP
chmod +x "$BIN_DIR/yt4k"

echo "Installed. Downloads land in ~/Downloads/YouTube 4K by default."

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
