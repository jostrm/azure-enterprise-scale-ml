#!/usr/bin/env bash
set -euo pipefail

# Run only the operator-maintained checkout and Python; never fetch source or install the operator environment.
export AIF_CONSUMER_ROOT="${AIF_CONSUMER_ROOT:-/opt/esaf/consumer}"
export AIF_PYTHON="${AIF_PYTHON:-$AIF_CONSUMER_ROOT/.venv-agent-operator/bin/python}"
[[ "$AIF_CONSUMER_ROOT" == /* && -d "$AIF_CONSUMER_ROOT" ]] || {
  echo "Factory project folder on VM must be an existing absolute Linux directory: $AIF_CONSUMER_ROOT. Prepare the standard folder /opt/esaf/consumer or set another folder in advanced settings." >&2
  exit 2
}
[[ "$AIF_PYTHON" == /* && -f "$AIF_PYTHON" && -x "$AIF_PYTHON" ]] || {
  echo "Prepared Python on VM must be an existing absolute Python 3.12+ executable: $AIF_PYTHON. Prepare the standard executable $AIF_CONSUMER_ROOT/.venv-agent-operator/bin/python or set another executable in advanced settings; no system Python fallback or installation is performed." >&2
  exit 2
}
adapter="$AIF_CONSUMER_ROOT/azure-enterprise-scale-ml/bootstrap/lib/agent_chat_portal.py"
[[ -f "$adapter" ]] || {
  echo "Update the prepared accelerator submodule: bootstrap/lib/agent_chat_portal.py is missing." >&2
  exit 2
}
# The adapter validates configuration before its isolated managed-identity login, and owns cleanup and readiness.
exec "$AIF_PYTHON" -B "$adapter"
