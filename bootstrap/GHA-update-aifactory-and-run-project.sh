#!/usr/bin/env bash
# AIFACTORY_PROJECT_DEPLOYMENT_ALIAS=GH-update-aifactory-and-run-project.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/GH-update-aifactory-and-run-project.sh" "$@"
