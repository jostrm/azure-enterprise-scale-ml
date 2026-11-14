#!/usr/bin/env bash
# Optional provider dispatch/wait entry point; no local deployment or Factory API.
# --env-file PATH is parsed literally by Python in each phase, never sourced.
# Exported credentials win; the optional local file is never sent to the provider.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON:-python3}"
repo_root_args=()
repo_root_given=0
for argument in "$@"; do
  case "$argument" in
    --repo-root|--repo-root=*) repo_root_given=1 ;;
  esac
done
if (( ! repo_root_given )); then
  repo_root_args=(--repo-root "$(git rev-parse --show-toplevel)")
fi

# A bundle's committed request sidecar selects a read-only, pinned input artifact.
"$python_bin" "$script_dir/lib/pipeline_dispatch.py" \
  "${repo_root_args[@]}" --download-input "$@"
# Canonical validation is a separate, API-free phase before any dispatch.
"$python_bin" "$script_dir/lib/pipeline_dispatch.py" \
  "${repo_root_args[@]}" --validate-only "$@"
exec "$python_bin" "$script_dir/lib/pipeline_dispatch.py" \
  "${repo_root_args[@]}" "$@"
