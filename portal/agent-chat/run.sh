#!/usr/bin/env bash
set -euo pipefail

# Run only the operator-maintained checkout and Python; never fetch source or install the operator environment.
: "${AIF_CONSUMER_ROOT:?An absolute durable consumer checkout is required}"
: "${AIF_PYTHON:?An absolute prepared Python 3.12+ executable is required}"
[[ "$AIF_CONSUMER_ROOT" == /* && -d "$AIF_CONSUMER_ROOT" ]] || {
  echo "AIF_CONSUMER_ROOT must be an existing absolute Linux directory." >&2
  exit 2
}
[[ "$AIF_PYTHON" == /* && -x "$AIF_PYTHON" ]] || {
  echo "AIF_PYTHON must be an existing absolute executable." >&2
  exit 2
}
adapter="$AIF_CONSUMER_ROOT/azure-enterprise-scale-ml/bootstrap/lib/agent_chat_portal.py"
[[ -f "$adapter" ]] || {
  echo "Update the prepared accelerator submodule: bootstrap/lib/agent_chat_portal.py is missing." >&2
  exit 2
}
# The adapter validates configuration before its isolated managed-identity login, and owns cleanup and readiness.
exec "$AIF_PYTHON" -B "$adapter"
