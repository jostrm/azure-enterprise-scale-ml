#!/usr/bin/env bash
# ============================================================
# build/macos/build-macos.sh
# Builds the AIFactory Config Wizard for macOS (Apple Silicon
# and Intel) using PyInstaller.
#
# Prerequisites (macOS):
#   brew install python@3.11        # or use system Python 3.11+
#   pip install pyyaml pyinstaller
#
# Usage (run from repo root):
#   bash build/macos/build-macos.sh           # build only
#   bash build/macos/build-macos.sh --tar     # build + .tar.gz
#   bash build/macos/build-macos.sh --run     # build + launch
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

SRC_VER="$REPO_ROOT/src/wizard_v034.py"
SRC="$REPO_ROOT/src/wizard.py"
DIST="$REPO_ROOT/build/macos"
NAME="aifactory-config"

echo "==> Repo root : $REPO_ROOT"
echo "==> Output dir: $DIST"

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
  ARCHIVE="$DIST/$NAME-macos.tar.gz"
  echo "==> Creating $ARCHIVE ..."
  tar -czf "$ARCHIVE" -C "$DIST" "$NAME"
  echo "Archive: $ARCHIVE"
fi

# ── Optional: launch ──────────────────────────────────────────────
if [[ "$1" == "--run" ]] || [[ "$2" == "--run" ]]; then
  echo "==> Launching $NAME ..."
  open "$DIST/$NAME" 2>/dev/null || "$DIST/$NAME"
fi
