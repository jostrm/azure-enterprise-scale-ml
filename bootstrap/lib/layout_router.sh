#!/usr/bin/env bash
# AIFACTORY_LAYOUT_ROUTER_CONTRACT=1

AIF_DUAL_LAYOUT_LAUNCHERS=(
  ADO-azurefactory.sh
  ADO-create-new-aifactory-scaleset.sh
  ADO-update-aifactory-and-run-project.sh
  AIFactory-lifecycle.sh
  ALL-create-new-aifactory-scaleset.sh
  GH-update-aifactory-and-run-project.sh
  GHA-azurefactory.sh
  GHA-create-new-aifactory-scaleset.sh
  GHA-update-aifactory-and-run-project.sh
)
AIF_DUAL_LAYOUT_LIBRARIES=(
  aifactory_private_dns.py
  aifactory_scaleset_config.py
  aifactory_vpn_profile.py
  create-new-aifactory-scaleset.sh
  factory_lifecycle.py
  layout_router.sh
  project_deployment.py
  project_environment.py
  release_version.py
  release_version.sh
)

aif_registered_layout_root() {
  local cursor="$1"
  cursor="$(realpath -m "$cursor")"
  while [[ "$cursor" != "/" && "$cursor" != "." ]]; do
    if [[ -L "$cursor/register.json" || -L "$cursor/azurefactory/register.json" ]]; then
      printf 'ERROR: azurefactory/register.json cannot be a symbolic link.\n' >&2
      return 2
    fi
    if [[ "${cursor##*/}" == "azurefactory" && -f "$cursor/register.json" ]]; then
      printf '%s\n' "$cursor"
      return 0
    fi
    if [[ -f "$cursor/azurefactory/register.json" ]]; then
      printf '%s\n' "$cursor/azurefactory"
      return 0
    fi
    local parent="${cursor%/*}"
    [[ -n "$parent" && "$parent" != "$cursor" ]] || break
    cursor="$parent"
  done
  return 1
}

aif_layout_provider_launcher() {
  local route="$1" script_dir="$2" name
  name="GHA-azurefactory.sh"
  [[ "$route" != "ado" ]] || name="ADO-azurefactory.sh"
  local candidate
  for candidate in \
    "$script_dir/$name" \
    "$script_dir/azure-enterprise-scale-ml/bootstrap/$name"; do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf 'ERROR: Registered-layout launcher %s is not installed.\n' "$name" >&2
  return 2
}

aif_route_registered_layout() {
  local route="$1" repo_root="$2" script_dir="$3"
  shift 3
  local -a original=("$@")
  local index
  for (( index=0; index<${#original[@]}; index++ )); do
    case "${original[$index]}" in
      --repo-root)
        (( index + 1 < ${#original[@]} )) || {
          printf 'ERROR: --repo-root requires a value.\n' >&2
          exit 2
        }
        repo_root="${original[$((index + 1))]}"
        index=$((index + 1))
        ;;
      --repo-root=*)
        repo_root="${original[$index]#*=}"
        ;;
    esac
  done
  local register_root detected
  if register_root="$(aif_registered_layout_root "$repo_root")"; then
    detected=0
  else
    detected=$?
  fi
  [[ "$detected" -ne 2 ]] || exit 2
  [[ "$detected" -eq 0 ]] || return 0

  local -a forwarded=()
  while (( $# )); do
    case "$1" in
      --repo-root)
        [[ $# -ge 2 ]] || { printf 'ERROR: --repo-root requires a value.\n' >&2; exit 2; }
        shift 2
        ;;
      --repo-root=*)
        shift
        ;;
      --aifactory-version|--aifactory-version=*)
        printf 'ERROR: Registered azurefactory operations freeze the version in the reviewed manifest; --aifactory-version is not accepted.\n' >&2
        exit 2
        ;;
      *)
        forwarded+=("$1")
        shift
        ;;
    esac
  done
  if (( ${#forwarded[@]} == 0 )); then
    printf 'ERROR: Registered azurefactory/register.json root %s requires AIFactory-lifecycle.sh inspect|execute with a reviewed protected manifest.\n' "$register_root" >&2
    exit 2
  fi
  case "${forwarded[0]:---help}" in
    inspect|execute|capabilities|--help|-h)
      ;;
    *)
      printf 'ERROR: Registered azurefactory/register.json root %s requires AIFactory-lifecycle.sh inspect|execute with a reviewed protected manifest. Legacy create/update options cannot be applied directly.\n' "$register_root" >&2
      exit 2
      ;;
  esac
  local launcher
  launcher="$(aif_layout_provider_launcher "$route" "$script_dir")" || exit $?
  exec bash "$launcher" "${forwarded[@]}"
}

aif_launcher_bundle_source() {
  local preferred="$1" candidate
  for candidate in "$preferred" "$preferred/azure-enterprise-scale-ml/bootstrap"; do
    local complete=true name
    for name in "${AIF_DUAL_LAYOUT_LAUNCHERS[@]}"; do
      [[ -f "$candidate/$name" ]] || complete=false
    done
    for name in "${AIF_DUAL_LAYOUT_LIBRARIES[@]}"; do
      [[ -f "$candidate/lib/$name" ]] || complete=false
    done
    [[ -f "$candidate/ui/terminal.sh" ]] || complete=false
    if [[ "$complete" == "true" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf 'ERROR: Complete dual-layout launcher bundle is not installed.\n' >&2
  return 2
}

aif_snapshot_launcher_bundle() {
  local preferred="$1" destination="$2" source
  source="$(aif_launcher_bundle_source "$preferred")" || return $?
  mkdir -p "$destination/lib" "$destination/ui" || return 2
  local name
  for name in "${AIF_DUAL_LAYOUT_LAUNCHERS[@]}"; do
    [[ -f "$source/$name" ]] || {
      printf 'ERROR: Dual-layout launcher bundle is missing %s.\n' "$name" >&2
      return 2
    }
    cp "$source/$name" "$destination/$name" || return 2
  done
  for name in "${AIF_DUAL_LAYOUT_LIBRARIES[@]}"; do
    cp "$source/lib/$name" "$destination/lib/$name" || return 2
  done
  cp "$source/ui/terminal.sh" "$destination/ui/terminal.sh" || return 2
}

aif_ensure_control_bundle_gitignore() {
  local destination="$1" ignore="$1/.gitignore"
  local rules=(
    "# AI Factory dual-layout control bundle"
  )
  local name
  for name in "${AIF_DUAL_LAYOUT_LAUNCHERS[@]}"; do
    rules+=("!/$name")
  done
  rules+=(
    "!/lib/"
    "/lib/*"
    "!/lib/aifactory_private_dns.py"
    "!/lib/aifactory_scaleset_config.py"
    "!/lib/aifactory_vpn_profile.py"
    "!/lib/create-new-aifactory-scaleset.sh"
    "!/lib/factory_lifecycle.py"
    "!/lib/layout_router.sh"
    "!/lib/project_deployment.py"
    "!/lib/project_environment.py"
    "!/lib/release_version.py"
    "!/lib/release_version.sh"
    "!/ui/"
    "/ui/*"
    "!/ui/terminal.sh"
  )
  touch "$ignore" || return 2
  if [[ -s "$ignore" && "$(tail -c 1 "$ignore" | wc -l)" -eq 0 ]]; then
    printf '\n' >> "$ignore" || return 2
  fi
  local rule
  for rule in "${rules[@]}"; do
    grep -qxF "$rule" "$ignore" 2>/dev/null || printf '%s\n' "$rule" >> "$ignore" || return 2
  done
}

aif_restore_launcher_bundle() {
  local snapshot="$1" destination="$2"
  mkdir -p "$destination/lib" "$destination/ui" || return 2
  local name
  for name in "${AIF_DUAL_LAYOUT_LAUNCHERS[@]}"; do
    [[ -f "$snapshot/$name" ]] || {
      printf 'ERROR: Preserved launcher bundle is incomplete: %s.\n' "$name" >&2
      return 2
    }
    cp "$snapshot/$name" "$destination/$name" || return 2
    chmod +x "$destination/$name" || return 2
  done
  for name in "${AIF_DUAL_LAYOUT_LIBRARIES[@]}"; do
    [[ -f "$snapshot/lib/$name" ]] || {
      printf 'ERROR: Preserved launcher library bundle is incomplete: %s.\n' "$name" >&2
      return 2
    }
    cp "$snapshot/lib/$name" "$destination/lib/$name" || return 2
  done
  [[ -f "$snapshot/ui/terminal.sh" ]] || {
    printf 'ERROR: Preserved launcher UI bundle is incomplete: terminal.sh.\n' >&2
    return 2
  }
  cp "$snapshot/ui/terminal.sh" "$destination/ui/terminal.sh" || return 2
  aif_ensure_control_bundle_gitignore "$destination" || return 2
}
