#!/usr/bin/env bash
# AIFACTORY_PROJECT_DEPLOYMENT_ALIAS=GH-update-aifactory-and-run-project.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AIF_UPDATE_DEFAULT_VERSION="${AIF_UPDATE_DEFAULT_VERSION:-main}"
exec bash "$SCRIPT_DIR/GH-update-aifactory-and-run-project.sh" "$@"
