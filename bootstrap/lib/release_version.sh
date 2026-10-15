#!/usr/bin/env bash
# AIFACTORY_VERSION_CONTRACT=1

aif_version_prepare() {
  local root="$1" project_only="${2:-false}" non_interactive="${3:-false}" default_version="${4:-}"
  local helper="${BASH_SOURCE[0]%/*}/release_version.py"
  local -a python_command version_arguments
  # Remember caller pins before resolution exports its selected commit.
  AIF_VERSION_KEEP_DETACHED=false
  if [[ -n "${AIF_SUBMODULE_REF:-}" || "${AIFACTORY_VERSION_REVIEWED:-}" == "1" || "$project_only" == "true" ]]; then
    AIF_VERSION_KEEP_DETACHED=true
  fi
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
  readonly AIFACTORY_VERSION AIF_SUBMODULE_BRANCH AIF_SUBMODULE_REF AIF_VERSION_KEEP_DETACHED
  AIF_VERSION_PYTHON=("${python_command[@]}")
  printf 'AI Factory version %s, branch %s, exact commit %s\n' "$AIFACTORY_VERSION" "$AIF_SUBMODULE_BRANCH" "$AIF_SUBMODULE_REF"
}

aif_version_checkout() {
  local source="$1/azure-enterprise-scale-ml" branch="$AIF_SUBMODULE_BRANCH" ref="$AIF_SUBMODULE_REF"
  local dirty remote_ref local_ref actual_ref
  if [[ ! "$ref" =~ ^[0-9a-f]{40}$ || ( "$branch" != "main" && ! "$branch" =~ ^release/v[0-9]+\.[0-9]+$ ) ]]; then
    printf 'ERROR: A resolved AI Factory branch and exact commit are required.\n' >&2
    return 1
  fi
  dirty="$(git -C "$source" status --porcelain)" || return 1
  if [[ -n "$dirty" ]]; then
    printf 'ERROR: Preserve local submodule changes before updating the selected branch.\n' >&2
    return 1
  fi
  if [[ "${AIF_VERSION_KEEP_DETACHED:-true}" == "true" ]]; then
    git -C "$source" fetch --no-tags origin "$ref" || return 1
    git -C "$source" checkout --detach "$ref" || return 1
  elif [[ "$AIF_VERSION_KEEP_DETACHED" == "false" ]]; then
    git -C "$source" fetch --no-tags origin "refs/heads/$branch:refs/remotes/origin/$branch" || return 1
    remote_ref="$(git -C "$source" rev-parse --verify "refs/remotes/origin/$branch^{commit}")" || return 1
    if [[ "$remote_ref" != "$ref" ]]; then
      printf 'ERROR: The published branch changed after version selection; rerun the update to select its latest commit.\n' >&2
      return 1
    fi
    local_ref="$(git -C "$source" for-each-ref --format='%(objectname)' "refs/heads/$branch")" || return 1
    if [[ -n "$local_ref" ]]; then
      if ! git -C "$source" merge-base --is-ancestor "$local_ref" "$ref"; then
        printf 'ERROR: Local branch %s is ahead or diverged; preserve and reconcile its commits manually.\n' "$branch" >&2
        return 1
      fi
      git -C "$source" checkout "$branch" || return 1
      git -C "$source" merge --ff-only "$ref" || return 1
    else
      git -C "$source" checkout -b "$branch" "$ref" || return 1
    fi
    git -C "$source" branch --set-upstream-to="origin/$branch" "$branch" || return 1
  else
    printf 'ERROR: Invalid AI Factory checkout mode.\n' >&2
    return 1
  fi
  actual_ref="$(git -C "$source" rev-parse HEAD)" || return 1
  if [[ "$actual_ref" != "$ref" ]]; then
    printf 'ERROR: Submodule checkout does not match the selected exact commit.\n' >&2
    return 1
  fi
}

aif_version_save() {
  "${AIF_VERSION_PYTHON[@]}" "${BASH_SOURCE[0]%/*}/release_version.py" --root "$1" --save
}
