#!/usr/bin/env bash
# Check is read-only. Installation never upgrades an existing tool.
set -euo pipefail

aif_runner_version() {
  local command_name="$1" text
  if [[ "$command_name" == az ]]; then
    text="$(az version --query '"azure-cli"' --output tsv 2>/dev/null)" || return 1
  else
    text="$("$command_name" --version 2>/dev/null)" || return 1
  fi
  [[ "$text" =~ ([0-9]+\.[0-9]+(\.[0-9]+)?) ]] || return 1
  printf '%s\n' "${BASH_REMATCH[1]}"
}

aif_runner_version_at_least() {
  local actual="$1" minimum="$2"
  [[ "$(printf '%s\n%s\n' "$actual" "$minimum" | sort -V | head -n 1)" == "$minimum" ]]
}

aif_runner_python_alias() {
  local destination="${1:-/usr/local/bin/python}" python3_path actual
  if command -v python >/dev/null 2>&1; then
    actual="$(aif_runner_version python)" && aif_runner_version_at_least "$actual" 3.10 ||
      { printf '%s\n' 'Existing python requires explicit repair/upgrade; no alias was created.' >&2; return 1; }
    return 0
  fi
  [[ ! -e "$destination" && ! -L "$destination" ]] ||
    { printf 'Refusing to overwrite Python alias destination: %s\n' "$destination" >&2; return 1; }
  python3_path="$(type -P python3)" && python3_path="$(readlink -f -- "$python3_path")" ||
    { printf '%s\n' 'An installed python3 executable is required for the python alias.' >&2; return 1; }
  actual="$(aif_runner_version "$python3_path")" && aif_runner_version_at_least "$actual" 3.10 ||
    { printf '%s\n' 'python3 requires explicit repair/upgrade before creating the python alias.' >&2; return 1; }
  # -T and no -f make creation fail rather than replace any concurrent file or symlink.
  ln -s -T -- "$python3_path" "$destination" || return
  actual="$(aif_runner_version "$destination")" && aif_runner_version_at_least "$actual" 3.10 ||
    { printf '%s\n' 'Python alias failed post-install verification.' >&2; return 1; }
  printf 'created: python -> %s (%s)\n' "$python3_path" "$destination"
}

aif_runner_official_asset() {
  python3 - "$@" <<'PY'
import hashlib
import json
import pathlib
import sys
import urllib.request

repo, pattern, destination = sys.argv[1:]
import fnmatch
request = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/releases/latest",
    headers={"Accept": "application/vnd.github+json", "User-Agent": "AI-Factory-bootstrap"},
)
with urllib.request.urlopen(request, timeout=60) as response:
    release = json.load(response)
if release.get("draft") or release.get("prerelease"):
    raise SystemExit("Refusing non-stable release")
assets = [item for item in release["assets"] if fnmatch.fnmatchcase(item["name"], pattern)]
if len(assets) != 1:
    raise SystemExit(f"Expected one official release asset for {repo}: {pattern}")
asset = assets[0]
url, digest = asset["browser_download_url"], asset.get("digest") or ""
if not url.startswith(f"https://github.com/{repo}/releases/download/"):
    raise SystemExit("Unexpected release URL")
if not digest.startswith("sha256:") or len(digest) != 71:
    raise SystemExit("Official SHA256 metadata is unavailable; refusing unverified binary")
path = pathlib.Path(destination)
with urllib.request.urlopen(url, timeout=180) as response, path.open("xb") as output:
    while chunk := response.read(1024 * 1024):
        output.write(chunk)
if hashlib.sha256(path.read_bytes()).hexdigest() != digest[7:].lower():
    raise SystemExit("Official release SHA256 verification failed")
PY
}

aif_runner_microsoft_repository() {
  local kind="$1" codename="$2" version="$3" work="$4"
  local key=/etc/apt/keyrings/aifactory-microsoft.gpg
  local source="/etc/apt/sources.list.d/aifactory-${kind}.list"
  # Signed apt metadata supplies the package version and integrity, not a curl-to-shell installer.
  if [[ ! -f "$key" ]]; then
    curl --fail --silent --show-error --location 'https://packages.microsoft.com/keys/microsoft.asc' \
      --output "$work/microsoft.asc" || return
    local fingerprint
    fingerprint="$(gpg --batch --show-keys --with-colons "$work/microsoft.asc" | awk -F: '$1=="fpr" {print $10; exit}')" || return
    [[ "$fingerprint" == BC528686B50D79E339D3721CEB3E94ADBE1229CF ]] ||
      { printf '%s\n' 'Microsoft apt signing-key fingerprint mismatch.' >&2; return 1; }
    gpg --batch --yes --dearmor --output "$work/microsoft.gpg" "$work/microsoft.asc" || return
    install -d -m 755 /etc/apt/keyrings || return
    install -m 644 "$work/microsoft.gpg" "$key" || return
  fi
  local line
  if [[ "$kind" == azure-cli ]]; then
    line="deb [arch=amd64 signed-by=$key] https://packages.microsoft.com/repos/azure-cli/ $codename main"
  else
    line="deb [arch=amd64 signed-by=$key] https://packages.microsoft.com/ubuntu/$version/prod $codename main"
  fi
  if [[ -e "$source" ]]; then
    [[ "$(cat "$source")" == "$line" ]] || { printf 'Refusing to replace %s\n' "$source" >&2; return 1; }
  else
    printf '%s\n' "$line" > "$source"
    chmod 644 "$source"
  fi
}

aif_runner_mark_prerequisites_changed() {
  install -d -m 755 /var/lib/aifactory-runner
  date -u +%s > /var/lib/aifactory-runner/prerequisites-changed
  chmod 644 /var/lib/aifactory-runner/prerequisites-changed
}

aif_runner_require_root() {
  (( EUID == 0 )) || { printf '%s\n' 'Installation requires sudo/root.' >&2; return 1; }
}

aif_runner_repair_partial_az_module_permissions() {
  python3 - "$1" <<'PY'
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
if root.name != "Modules" or root.parent.name != "powershell":
    raise SystemExit("Unexpected AllUsers module root")
if not root.exists():
    raise SystemExit(0)
names = {"Az.Accounts", "Az.Network"}
if any(path.name not in names or not path.is_dir() for path in root.iterdir()):
    raise SystemExit("Unrelated modules prevent partial-install permission repair")
paths = [root.parent, root, *root.rglob("*")]
for path in paths:
    info = path.lstat()
    if (info.st_uid != 0 or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)):
        raise SystemExit("Partial module permissions require root-owned, nonlinked, nonwritable package files")
changed = False
for path in paths:
    mode = stat.S_IMODE(path.stat().st_mode)
    readable = mode | (0o055 if path.is_dir() or mode & stat.S_IXUSR else 0o044)
    if readable != mode:
        os.chmod(path, readable)
        changed = True
print("Repaired reviewed AllUsers module visibility." if changed else "AllUsers module visibility already correct.")
PY
}

aif_runner_az_modules() (
  umask 022
  local install_missing="$1" script
  script="$(cat <<'PS'
$ErrorActionPreference = 'Stop'
foreach ($spec in @(@{Name='Az.Accounts'; Minimum=[version]'2.12'}, @{Name='Az.Network'; Minimum=[version]'5.0'})) {
    $module = Get-Module -ListAvailable -Name $spec.Name | Sort-Object Version -Descending | Select-Object -First 1
    if ($module -and $module.Version -lt $spec.Minimum) {
        throw "Existing $($spec.Name) is too old; upgrade explicitly."
    }
    if (-not $module) {
        if ($env:AIF_INSTALL_MODULES -ne 'true') { throw "Missing PowerShell module $($spec.Name) (check mode)." }
        [IO.Directory]::CreateDirectory('/var/lib/aifactory-runner') | Out-Null
        [IO.File]::WriteAllText('/var/lib/aifactory-runner/prerequisites-changed', [DateTimeOffset]::UtcNow.ToUnixTimeSeconds().ToString())
        $version = (Find-Module -Name $spec.Name -Repository PSGallery).Version
        Install-Module -Name $spec.Name -RequiredVersion $version -Repository PSGallery -Scope AllUsers -Force -AcceptLicense
        if (-not (Get-Module -ListAvailable -Name $spec.Name | Where-Object Version -GE $spec.Minimum)) {
            throw "Module $($spec.Name) failed post-install verification."
        }
    }
}
PS
)"
  AIF_INSTALL_MODULES="$install_missing" pwsh -NoProfile -NonInteractive -Command "$script"
)

aif_runner_prerequisites_main() (
  local install_missing=false require_runtime=false require_modules=false
  while (( $# )); do
    case "$1" in
      --check|--plan) ;;
      --install-missing) install_missing=true ;;
      --require-runner-runtime) require_runtime=true ;;
      --require-az-modules) require_modules=true ;;
      --help)
        printf '%s\n' 'runner-prerequisites.sh [--check|--plan|--install-missing] [--require-runner-runtime] [--require-az-modules] (Ubuntu 22.04/24.04 x64)'
        return 0 ;;
      *) printf 'Unknown prerequisite option: %s\n' "$1" >&2; return 1 ;;
    esac
    shift
  done
  [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] ||
    { printf '%s\n' 'Ubuntu x64 required. On Windows use runner-prerequisites.ps1.' >&2; return 1; }
  local ID="" VERSION_ID="" VERSION_CODENAME=""
  source /etc/os-release
  [[ "$ID" == ubuntu && ( "$VERSION_ID" == 22.04 || "$VERSION_ID" == 24.04 ) ]] ||
    { printf '%s\n' 'Supported runner distributions: Ubuntu 22.04 and 24.04.' >&2; return 1; }
  local -a names=(git bash python3 python az pwsh gh bicep jq) missing=()
  # 0.31 supports the source's imported functions. Keep the separate, reviewed CI install pin below.
  local -A minimum=([git]=2.30 [bash]=4.0 [python3]=3.10 [python]=3.10 [az]=2.50 [pwsh]=7.0 [gh]=2.0 [bicep]=0.31.92 [jq]=1.6)
  local name actual invalid=false
  for name in "${names[@]}"; do
    if ! command -v "$name" >/dev/null 2>&1; then
      printf 'missing: %s >= %s\n' "$name" "${minimum[$name]}"
      missing+=("$name")
    elif ! actual="$(aif_runner_version "$name")" || ! aif_runner_version_at_least "$actual" "${minimum[$name]}"; then
      printf 'invalid: %s (%s); requires >= %s. Repair/upgrade explicitly.\n' "$name" "$(command -v "$name")" "${minimum[$name]}" >&2
      invalid=true
    else
      printf 'ready: %s %s (%s)\n' "$name" "$actual" "$(command -v "$name")"
    fi
  done
  [[ "$invalid" == false ]] || return 2
  local -a runtime_missing=() runtime_packages=(libkrb5-3 zlib1g)
  if [[ "$VERSION_ID" == 22.04 ]]; then
    runtime_packages+=(liblttng-ust1 libicu70 libssl3 libcurl4)
  else
    runtime_packages+=(liblttng-ust1t64 libicu74 libssl3t64 libcurl4t64)
  fi
  if [[ "$require_runtime" == true ]]; then
    for name in "${runtime_packages[@]}"; do
      dpkg-query -W -f='${Status}' "$name" 2>/dev/null | grep -qx 'install ok installed' || runtime_missing+=("$name")
    done
  fi
  if (( ${#missing[@]} == 0 && ${#runtime_missing[@]} == 0 )); then
    if [[ "$require_modules" == true ]]; then
      if [[ "$install_missing" == true ]]; then
        aif_runner_require_root || return
      fi
      aif_runner_az_modules "$install_missing" || return
    fi
    return 0
  fi
  if [[ "$install_missing" != true ]]; then
    (( ${#runtime_missing[@]} == 0 )) || printf 'Missing runtime packages: %s\n' "${runtime_missing[*]}" >&2
    printf '%s\n' 'Check made no changes. Review and rerun with --install-missing.' >&2
    return 2
  fi
  aif_runner_require_root || return
  local work="$PWD/.aifactory-runner-downloads" package
  [[ ! -e "$work" ]] || { printf 'Inspect existing staging directory before retrying: %s\n' "$work" >&2; return 1; }
  (umask 077; mkdir "$work")
  # Clean up only files created in our new staging directory, never any runner directory.
  trap 'rm -f -- "$work"/microsoft.asc "$work"/microsoft.gpg "$work"/gh.deb "$work"/bicep; rmdir -- "$work"' EXIT
  aif_runner_mark_prerequisites_changed || return
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || return
  local -a base_missing=()
  for name in python3 git jq curl gpg ca-certificates; do
    if [[ "$name" == ca-certificates ]]; then
      dpkg-query -W -f='${Status}' ca-certificates 2>/dev/null | grep -q 'install ok installed' || base_missing+=("$name")
    elif ! command -v "$name" >/dev/null 2>&1; then
      base_missing+=("$name")
    fi
  done
  if (( ${#base_missing[@]} )); then apt-get install -y --no-upgrade "${base_missing[@]}" || return; fi
  if (( ${#runtime_missing[@]} )); then apt-get install -y --no-upgrade "${runtime_missing[@]}" || return; fi
  for name in "${missing[@]}"; do
    case "$name" in
      git|jq|python3) ;;
      python) aif_runner_python_alias || return ;;
      bash) printf '%s\n' 'Repair the system Bash installation explicitly.' >&2; return 1 ;;
      az|pwsh)
        package=azure-cli
        [[ "$name" != pwsh ]] || package=powershell
        aif_runner_microsoft_repository "$package" "$VERSION_CODENAME" "$VERSION_ID" "$work" || return
        apt-get update -qq || return
        apt-get install -y --no-upgrade "$package" || return
        ;;
      gh)
        aif_runner_official_asset cli/cli 'gh_*_linux_amd64.deb' "$work/gh.deb" || return
        apt-get install -y --no-upgrade "$work/gh.deb" || return
        ;;
      bicep)
        [[ ! -e /usr/local/bin/bicep ]] || { printf '%s\n' 'Refusing to overwrite /usr/local/bin/bicep.' >&2; return 1; }
        curl --fail --silent --show-error --location --retry 3 --max-time 180 \
          'https://github.com/Azure/bicep/releases/download/v0.44.1/bicep-linux-x64' --output "$work/bicep" || return
        printf '%s  %s\n' 'e17dc9a9888184886bb0c0051a3230b83b19f342749999f707bc571c3dfd2f45' "$work/bicep" |
          sha256sum --check --status || return
        install -m 755 "$work/bicep" /usr/local/bin/bicep || return
        ;;
    esac
  done
  hash -r
  for name in "${names[@]}"; do
    actual="$(aif_runner_version "$name")" && aif_runner_version_at_least "$actual" "${minimum[$name]}" ||
      { printf 'Post-install verification failed: %s\n' "$name" >&2; return 1; }
  done
  for name in "${runtime_missing[@]}"; do
    dpkg-query -W -f='${Status}' "$name" 2>/dev/null | grep -qx 'install ok installed' ||
      { printf 'Runner runtime package failed post-install verification: %s\n' "$name" >&2; return 1; }
  done
  if [[ "$require_modules" == true ]]; then aif_runner_az_modules true || return; fi
  printf '%s\n' 'Prerequisites verified. Runner registration and scoped Linux identity/lease checks are separate.'
  rm -f -- "$work"/microsoft.asc "$work"/microsoft.gpg "$work"/gh.deb "$work"/bicep
  rmdir -- "$work"
  trap - EXIT
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  aif_runner_prerequisites_main "$@"
fi
