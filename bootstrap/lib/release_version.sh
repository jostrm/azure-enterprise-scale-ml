#!/usr/bin/env bash
# AIFACTORY_VERSION_CONTRACT=1

aif_version_prepare() {
  local root="$1" project_only="${2:-false}" non_interactive="${3:-false}" default_version="${4:-}"
  local helper="${BASH_SOURCE[0]%/*}/release_version.py"
  local -a python_command version_arguments
  if command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    python_command=(python)
  elif command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    python_command=(python3)
  else
    python_command=(py -3)
  fi
  version_arguments=(--root "$root")
  [[ -z "${AIF_VERSION_ARGUMENT:-}" ]] || version_arguments+=(--aifactory-version "$AIF_VERSION_ARGUMENT")
  if [[ -z "${AIF_VERSION_ARGUMENT:-}" && -z "${AIFACTORY_VERSION:-}" &&
        -z "${AIF_SUBMODULE_BRANCH:-}" && -n "$default_version" ]]; then
    version_arguments+=(--aifactory-version "$default_version")
  fi
  [[ "$project_only" != "true" ]] || version_arguments+=(--project-only)
  [[ "$non_interactive" != "true" && "${AIFACTORY_VERSION_REVIEWED:-}" != "1" ]] || version_arguments+=(--non-interactive)
  local selection
  selection="$("${python_command[@]}" "$helper" "${version_arguments[@]}")" || return 1
  eval "$selection"
  readonly AIFACTORY_VERSION AIF_SUBMODULE_BRANCH AIF_SUBMODULE_REF
  AIF_VERSION_PYTHON=("${python_command[@]}")
  printf 'AI Factory version %s, branch %s, exact commit %s\n' "$AIFACTORY_VERSION" "$AIF_SUBMODULE_BRANCH" "$AIF_SUBMODULE_REF"
}

aif_version_save() {
  "${AIF_VERSION_PYTHON[@]}" "${BASH_SOURCE[0]%/*}/release_version.py" --root "$1" --save
}
