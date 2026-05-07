#!/usr/bin/env bash
# ============================================================
# build/linux/build-linux.sh
# Builds the AIFactory Config Wizard for Linux (x86-64) using
# PyInstaller.
#
# Prerequisites (Ubuntu / Debian):
#   sudo apt-get install -y python3 python3-pip python3-tk
#   pip3 install pyyaml pyinstaller
#
# Usage (run from repo root):
#   bash build/linux/build-linux.sh           # build only
#   bash build/linux/build-linux.sh --tar     # build + .tar.gz
#   bash build/linux/build-linux.sh --run     # build + launch
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

SRC_VER="$REPO_ROOT/src/wizard_v034.py"
SRC="$REPO_ROOT/src/wizard.py"
DIST="$REPO_ROOT/build/linux"
NAME="aifactory-config"

echo "==> Repo root : $REPO_ROOT"
echo "==> Output dir: $DIST"

# ── Ensure python3-tk is present (Tkinter is NOT bundled by default) ─
echo "==> Ensuring python3-tk is available..."
if command -v apt-get &>/dev/null; then
  sudo apt-get install -y --no-install-recommends python3-tk 2>/dev/null || true
elif command -v dnf &>/dev/null; then
  sudo dnf install -y python3-tkinter 2>/dev/null || true
elif command -v zypper &>/dev/null; then
  sudo zypper install -y python3-tk 2>/dev/null || true
fi

# ── Promote versioned source ──────────────────────────────────────
echo "==> Copying wizard_v034.py -> src/wizard.py..."
cp -f "$SRC_VER" "$SRC"

# ── Dependencies ──────────────────────────────────────────────────
echo "==> Installing/upgrading dependencies..."
pip install --quiet --upgrade pyyaml pyinstaller

# ── Build ─────────────────────────────────────────────────────────
echo "==> Running PyInstaller (onefile, windowed)..."
cd "$REPO_ROOT"
pyinstaller \
  --onefile \
  --windowed \
  --name "$NAME" \
  --distpath "$DIST" \
  --add-data "template-files:template-files" \
  --add-data "images:images" \
  "$SRC"

echo ""
echo "Build complete!"
echo "Binary: $DIST/$NAME"

# ── Optional: archive ─────────────────────────────────────────────
if [[ "$1" == "--tar" ]] || [[ "$2" == "--tar" ]]; then
  ARCHIVE="$DIST/$NAME-linux.tar.gz"
  echo "==> Creating $ARCHIVE ..."
  tar -czf "$ARCHIVE" -C "$DIST" "$NAME"
  echo "Archive: $ARCHIVE"
fi

# ── Optional: launch ──────────────────────────────────────────────
if [[ "$1" == "--run" ]] || [[ "$2" == "--run" ]]; then
  echo "==> Launching $NAME ..."
  "$DIST/$NAME"
fi
