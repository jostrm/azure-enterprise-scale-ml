#!/usr/bin/env bash
# Managed Run Command named (including protected) Linux parameters are environment variables:
# https://learn.microsoft.com/azure/virtual-machines/linux/run-command-managed
# RegistrationToken is passed in memory, never as a command-line argument or stored credential.
set +x
set -euo pipefail

aif_linux_runner_scope() {
  python3 - "$@" <<'PY'
import json
import pathlib
import re
import sys
from urllib.parse import urlsplit

provider, root, url, pool, name = sys.argv[1:6]
remote_id = sys.argv[6] if len(sys.argv) > 6 else ""
def normalize(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port:
        raise SystemExit("Runner scope must be HTTPS without credentials, port, query, or fragment")
    result = value.rstrip("/").lower()
    legacy = re.fullmatch(r"https://([a-z0-9-]+)\.visualstudio\.com", result)
    if provider == "ado" and legacy:
        result = f"https://dev.azure.com/{legacy[1]}"
    pattern = r"https://dev\.azure\.com/[a-z0-9_.-]+" if provider == "ado" else r"https://github\.com/[a-z0-9_.-]+/[a-z0-9_.-]+"
    if not re.fullmatch(pattern, result):
        raise SystemExit("Unsupported organization/repository scope")
    return result

expected = normalize(url)
path = pathlib.Path(root) / (".agent" if provider == "ado" else ".runner")
if path.is_symlink():
    raise SystemExit("Refusing symlinked runner configuration")
if not path.exists():
    print("false")
else:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    actual = config.get("serverUrl" if provider == "ado" else "gitHubUrl", "")
    if (normalize(actual) != expected or config.get("agentName") != name
            or (provider == "ado" and config.get("poolName") != pool)):
        raise SystemExit("Existing runner belongs to a different scope, pool, or name; refusing reconfiguration")
    if remote_id and str(config.get("agentId", "")) != remote_id:
        raise SystemExit("Existing provider agent ID differs; refusing stale registration/takeover")
    print("true")
PY
}

aif_linux_runner_worker() {
  local worker="$1" home="$2" create="$3" entry uid gid actual_home shell groups
  if ! entry="$(getent passwd "$worker")"; then
    [[ "$create" == true ]] || { printf 'Missing dedicated worker %s.\n' "$worker" >&2; return 1; }
    [[ ! -e "$home" ]] || { printf 'Refusing to adopt existing worker home %s.\n' "$home" >&2; return 1; }
    useradd --system --user-group --create-home --home-dir "$home" --shell /usr/sbin/nologin "$worker" || return
    entry="$(getent passwd "$worker")" || return
  fi
  IFS=: read -r _ _ uid gid _ actual_home shell <<< "$entry"
  [[ "$uid" =~ ^[0-9]+$ && "$uid" != 0 && "$actual_home" == "$home" && "$shell" == /usr/sbin/nologin ]] ||
    { printf 'Worker %s is not a dedicated unprivileged service identity; inspect explicitly.\n' "$worker" >&2; return 1; }
  groups="$(id -G "$worker")" || return
  [[ "$groups" == "$gid" ]] ||
    { printf 'Worker %s has extra groups; refusing privileged/shared worker identity.\n' "$worker" >&2; return 1; }
}

aif_linux_runner_service() {
  local provider="$1" root="$2" worker="$3" name key value
  [[ -f "$root/.service" && ! -L "$root/.service" ]] ||
    { printf '%s\n' 'Registered runner has no regular .service ownership file.' >&2; return 1; }
  name="$(cat "$root/.service")"
  local prefix=vsts.agent.
  [[ "$provider" != gha ]] || prefix=actions.runner.
  [[ "$name" == "$prefix"* && "$name" =~ ^[a-zA-Z0-9_.@-]+\.service$ ]] ||
    { printf '%s\n' 'Invalid provider service ownership name.' >&2; return 1; }
  local -A info=()
  local details
  details="$(systemctl show "$name" --no-pager \
    --property=Id,LoadState,User,WorkingDirectory,ExecStart,FragmentPath,ActiveState,SubState,UnitFileState,MainPID)" || return
  while IFS='=' read -r key value; do info["$key"]="$value"; done <<< "$details"
  [[ "${info[Id]:-}" == "$name" && "${info[LoadState]:-}" == loaded &&
     "${info[User]:-}" == "$worker" && "${info[WorkingDirectory]:-}" == "$root" &&
     "${info[FragmentPath]:-}" == "/etc/systemd/system/$name" &&
     "${info[ExecStart]:-}" == "{ path=$root/runsvc.sh ; argv[]=$root/runsvc.sh ;"* &&
     "${info[ExecStart]:-}" != *"} {"* &&
     "${info[UnitFileState]:-}" == enabled ]] ||
    { printf 'Service %s does not match the exact runner folder, worker, executable, or enabled state.\n' "$name" >&2; return 1; }
  [[ "${info[ActiveState]:-}" == inactive ||
     ( "${info[ActiveState]:-}" == active && "${info[SubState]:-}" == running && "${info[MainPID]:-0}" != 0 ) ]] ||
    { printf 'Owned service %s is not healthy/stopped; resolve explicitly.\n' "$name" >&2; return 1; }
  AIF_OWNED_SERVICE="$name"
  AIF_OWNED_STATE="${info[ActiveState]}"
  AIF_OWNED_PID="${info[MainPID]:-0}"
}

aif_linux_runner_fresh_process() {
  python3 - "$1" <<'PY'
import os
import pathlib
import sys
marker = pathlib.Path("/var/lib/aifactory-runner/prerequisites-changed")
if marker.exists():
    # Linux process start time is field 22 in /proc/PID/stat, after the parenthesized comm.
    stat = pathlib.Path(f"/proc/{int(sys.argv[1])}/stat").read_text().rsplit(")", 1)[1].split()
    boot = next(int(line.split()[1]) for line in pathlib.Path("/proc/stat").read_text().splitlines() if line.startswith("btime "))
    started = boot + int(stat[19]) / os.sysconf("SC_CLK_TCK")
    if started <= marker.stat().st_mtime:
        raise SystemExit("Prerequisites changed; running/busy service left untouched. Explicitly restart it when idle, refresh its captured PATH if necessary, then rerun verification.")
PY
}

aif_linux_runner_worker_check() {
  local worker="$1" home="$2" root="$3" script="$4" path="$5"
  [[ ! -f "$root/.path" ]] || path="$(cat "$root/.path")"
  [[ "$path" == /* && "$path" != *$'\n'* && "$path" != *$'\r'* ]] ||
    { printf '%s\n' 'Invalid captured runner PATH; inspect .path explicitly.' >&2; return 1; }
  printf '%s\n%s\n' "$script" 'aif_runner_prerequisites_main --check --require-runner-runtime --require-az-modules' |
    (cd "$home" && runuser -u "$worker" -- env -i HOME="$home" USER="$worker" LOGNAME="$worker" PATH="$path" \
      AZURE_BICEP_USE_BINARY_FROM_PATH=true /bin/bash -c 'source <(cat)')
}

aif_linux_runner_verify_package() {
  python3 - "$@" <<'PY'
import hashlib
import os
import pathlib
import posixpath
import re
import stat
import sys
import tarfile

root, package = map(pathlib.Path, sys.argv[1:3])
checksum, uid = sys.argv[3], int(sys.argv[4])
def require(value, message):
    if not value:
        raise SystemExit(message)
def digest(stream):
    result = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        result.update(chunk)
    return result.hexdigest()
require(re.fullmatch(r"[a-f0-9]{64}", checksum), "Explicit reviewed package SHA256 is required")
require(root.is_dir() and not root.is_symlink() and root.stat().st_uid == uid,
        "Resume requires the exact dedicated-worker package directory")
require(package.is_file() and not package.is_symlink(), "Verified package must be a regular file")
with package.open("rb") as stream:
    require(digest(stream) == checksum, "Resume package SHA256 mismatch")
for name in (".agent", ".runner", ".service", ".credentials", ".credentials_rsaparams"):
    require(not os.path.lexists(root / name), "Existing registration prevents package-only resume")
with tarfile.open(package) as archive:
    expected = {}
    for entry in archive:
        path = pathlib.PurePosixPath(entry.name)
        require(not path.is_absolute() and ".." not in path.parts, "Unsafe resume archive path")
        if str(path) == ".":
            continue
        name = str(path)
        require(name not in expected, "Duplicate resume archive entry")
        require(entry.isdir() or entry.isfile() or entry.issym() or entry.islnk(), "Unsafe resume archive type")
        if entry.issym() or entry.islnk():
            target = pathlib.PurePosixPath(entry.linkname)
            resolved = posixpath.normpath(posixpath.join(str(path.parent), str(target)) if entry.issym() else str(target))
            require(not target.is_absolute() and resolved != ".." and not resolved.startswith("../"),
                    "Unsafe resume archive link")
        expected[name] = entry
    directories = {str(parent) for name in expected for parent in pathlib.PurePosixPath(name).parents
                   if str(parent) != "."}
    actual = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = pathlib.Path(directory) / name
            actual[path.relative_to(root).as_posix()] = path
    require(set(actual) == set(expected) | directories, "Unregistered directory differs from verified package inventory")
    # Follow archive order so gzip never repeatedly decompresses earlier package contents.
    for name in (*expected, *sorted(directories - set(expected))):
        path = actual[name]
        info = path.lstat()
        require(info.st_uid == uid and not info.st_mode & (stat.S_ISUID | stat.S_ISGID),
                "Resume package ownership or permissions differ")
        entry = expected.get(name)
        if entry is None or entry.isdir():
            require(stat.S_ISDIR(info.st_mode), "Resume package directory differs")
        elif entry.issym():
            require(stat.S_ISLNK(info.st_mode) and os.readlink(path) == entry.linkname, "Resume package symlink differs")
        else:
            require(stat.S_ISREG(info.st_mode), "Resume package file type differs")
            require(path.resolve().is_relative_to(root.resolve()), "Resume package file escapes directory")
            with path.open("rb") as local, archive.extractfile(entry) as official:
                require(digest(local) == digest(official), "Resume package file content differs")
print("Verified exact unregistered official package; no existing registration was adopted.")
PY
}

aif_linux_runner_download() {
  python3 - "$@" <<'PY'
import hashlib
import pathlib
import posixpath
import re
import sys
import tarfile
import urllib.request
from urllib.parse import urlsplit
provider, url, checksum, destination = sys.argv[1:]
if not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
    raise SystemExit("Official runner SHA256 metadata is required")
parsed = urlsplit(url)
if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port:
    raise SystemExit("Invalid official package URL")
if provider == "ado":
    valid = parsed.hostname in ("download.agent.dev.azure.com", "vstsagentpackage.azureedge.net", "vstsagentpackage.blob.core.windows.net")
    valid = valid and re.fullmatch(r"/agent/([0-9]+\.[0-9]+\.[0-9]+)/vsts-agent-linux-x64-\1\.tar\.gz", parsed.path)
else:
    valid = re.fullmatch(r"https://github\.com/actions/runner/releases/download/v([0-9]+\.[0-9]+\.[0-9]+)/actions-runner-linux-x64-\1\.tar\.gz", url)
if not valid:
    raise SystemExit("Package must be a pinned official Linux x64 provider release")
path = pathlib.Path(destination)
digest = hashlib.sha256()
with urllib.request.urlopen(url, timeout=180) as response, path.open("xb") as output:
    while chunk := response.read(1024 * 1024):
        digest.update(chunk)
        output.write(chunk)
if digest.hexdigest() != checksum.lower():
    raise SystemExit("Runner SHA256 verification failed")
with tarfile.open(path) as archive:
    for item in archive:
        name = pathlib.PurePosixPath(item.name)
        target = pathlib.PurePosixPath(item.linkname)
        if name.is_absolute() or ".." in name.parts or item.isdev():
            raise SystemExit("Unsafe runner archive entry")
        if item.issym() or item.islnk():
            relative = posixpath.join(str(name.parent), str(target)) if item.issym() else str(target)
            resolved = posixpath.normpath(relative)
            if target.is_absolute() or resolved == ".." or resolved.startswith("../"):
                raise SystemExit("Unsafe runner archive link")
PY
}

aif_linux_runner_configure() {
  local worker="$1" home="$2" root="$3" provider="$4" url="$5" pool="$6" name="$7" label="$8" path="$9"
  # The protected token arrives on stdin, not env(1)'s argv. Provider consumes/masks its INPUT_TOKEN.
  runuser -u "$worker" -- env -i HOME="$home" USER="$worker" LOGNAME="$worker" PATH="$path" \
    AZURE_BICEP_USE_BINARY_FROM_PATH=true /bin/bash -c '
      set +x; set -euo pipefail; umask 077
      root="$1"; provider="$2"; url="$3"; pool="$4"; name="$5"; label="$6"
      IFS= read -r token
      if [[ "$provider" == ado ]]; then export VSTS_AGENT_INPUT_TOKEN="$token"
      else export ACTIONS_RUNNER_INPUT_TOKEN="$token"; fi
      unset token
      cd "$root"
      args=(--unattended --url "$url" --work _work)
      if [[ "$provider" == ado ]]; then args+=(--auth pat --pool "$pool" --agent "$name")
      else args+=(--name "$name" --labels "$label"); fi
      exec ./config.sh "${args[@]}"
    ' -- "$root" "$provider" "$url" "$pool" "$name" "$label" >/dev/null 2>&1
}

aif_linux_runner_install_service() {
  local provider="$1" root="$2" worker="$3" path="$4" name=vsts.agent.aifactory.service
  [[ "$provider" != gha ]] || name=actions.runner.aifactory.service
  [[ ! -e "/etc/systemd/system/$name" && ! -L "/etc/systemd/system/$name" && ! -e "$root/.service" ]] ||
    { printf '%s\n' 'Owned service already exists; refusing replacement.' >&2; return 1; }
  install -m 755 -o "$worker" -g "$worker" "$root/bin/runsvc.sh" "$root/runsvc.sh" || return
  (umask 022; set -o noclobber; cat > "/etc/systemd/system/$name" <<UNIT
[Unit]
Description=AI Factory $provider worker
After=network-online.target
[Service]
User=$worker
WorkingDirectory=$root
ExecStart=$root/runsvc.sh
Environment="PATH=$path" "AZURE_BICEP_USE_BINARY_FROM_PATH=true"
NoNewPrivileges=true
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=5min
[Install]
WantedBy=multi-user.target
UNIT
  ) || return
  (umask 027; set -o noclobber; printf '%s\n' "$name" > "$root/.service") || return
  chown "$worker:$worker" "$root/.service" || return
  systemctl daemon-reload || return
  systemctl enable "$name" || return
}

aif_linux_runner_main() (
  set +x
  umask 077
  local token="${RegistrationToken:-}"
  unset RegistrationToken
  local provider="${Provider:-}" url="${RegistrationUrl:-}" pool="${AgentPool:-}" name="${AgentName:-}"
  local install_missing="${InstallMissing:-false}" remote_exists="${RemoteExists:-false}" label="${RunnerLabel:-}"
  [[ "$provider" == ado || "$provider" == gha ]] || { printf '%s\n' 'Provider must be ado or gha.' >&2; exit 1; }
  [[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$ && ( "$provider" != ado || -n "$pool" ) ]] ||
    { printf '%s\n' 'Safe runner name and ADO pool are required.' >&2; exit 1; }
  [[ "$provider" != gha || "$label" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$ ]] ||
    { printf '%s\n' 'A safe unique GitHub label is required.' >&2; exit 1; }
  [[ "$install_missing" == true || "$install_missing" == false ]] || exit 1
  [[ "$remote_exists" == true || "$remote_exists" == false ]] || exit 1
  [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] ||
    { printf '%s\n' 'Ubuntu 22.04/24.04 x64 required; this helper never labels Windows as Linux.' >&2; exit 1; }
  local ID="" VERSION_ID=""
  source /etc/os-release
  [[ "$ID" == ubuntu && ( "$VERSION_ID" == 22.04 || "$VERSION_ID" == 24.04 ) ]] || exit 1
  local root=/opt/aifactory-agent worker=aifactory-ado home=/var/lib/aifactory-ado
  if [[ "$provider" == gha ]]; then root=/opt/aifactory-gha-runner; worker=aifactory-gha; home=/var/lib/aifactory-gha; fi
  local path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin configured resume_verified=false
  [[ ! -L "$root" && ! -L /opt && ! -L "$home" ]] || { printf '%s\n' 'Refusing symlinked runner roots.' >&2; exit 1; }
  [[ ! -e "$root" || -d "$root" ]] || { printf '%s\n' 'Runner root is not a directory; inspect explicitly.' >&2; exit 1; }
  # Ubuntu supplies Python; fail safely instead of installing before local ownership checks.
  configured="$(aif_linux_runner_scope "$provider" "$root" "$url" "$pool" "$name" "${RemoteAgentId:-}")" || exit
  if [[ "$configured" == true ]]; then
    aif_linux_runner_worker "$worker" "$home" false || exit
    aif_linux_runner_service "$provider" "$root" "$worker" || exit
  elif [[ "$remote_exists" == true ]]; then
    printf '%s\n' 'Provider already has this name but local registration is absent; refusing takeover.' >&2; exit 1
  elif [[ -d "$root" && -n "$(find "$root" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    # Only an explicitly reviewed package-only failure may resume; default takeover rejection remains.
    if [[ "$provider" != ado || "$install_missing" != true ||
          ! "${ResumePackageSha256:-}" =~ ^[a-f0-9]{64}$ ||
          "${ResumePackageSha256:-}" != "${PackageSha256:-}" ]]; then
      printf '%s\n' 'Unregistered nonempty runner directory; inspect explicitly. Nothing was deleted.' >&2; exit 1
    fi
    aif_linux_runner_worker "$worker" "$home" false || exit
    [[ ! -e /etc/systemd/system/vsts.agent.aifactory.service &&
       ! -L /etc/systemd/system/vsts.agent.aifactory.service ]] ||
      { printf '%s\n' 'Existing service prevents package-only resume.' >&2; exit 1; }
    local resume_archive="$PWD/.aifactory-runner-resume-${ResumePackageSha256}.tar.gz"
    if [[ ! -e "$resume_archive" && ! -L "$resume_archive" ]]; then
      aif_linux_runner_download "$provider" "${PackageUrl:-}" "$ResumePackageSha256" "$resume_archive" || exit
    fi
    aif_linux_runner_verify_package "$root" "$resume_archive" "$ResumePackageSha256" "$(id -u "$worker")" || exit
    resume_verified=true
  fi
  local script="${PrerequisitesScript:-}"
  [[ -n "$script" ]] || script="$(cat "$(dirname "${BASH_SOURCE[0]}")/runner-prerequisites.sh")"
  local -a options=(--check --require-runner-runtime --require-az-modules)
  if [[ "$install_missing" == true ]]; then
    (( EUID == 0 )) || { printf '%s\n' 'Installation requires sudo/root.' >&2; exit 1; }
    options=(--install-missing --require-runner-runtime --require-az-modules)
  fi
  source /dev/stdin <<< "$script"
  if [[ "$resume_verified" == true ]]; then
    aif_runner_repair_partial_az_module_permissions /usr/local/share/powershell/Modules || exit
  fi
  aif_runner_prerequisites_main "${options[@]}" || exit
  if [[ "$configured" == true ]]; then
    aif_linux_runner_worker_check "$worker" "$home" "$root" "$script" "$path" || exit
    if [[ "$AIF_OWNED_STATE" == active ]]; then
      aif_linux_runner_fresh_process "$AIF_OWNED_PID" || exit
      printf 'Reused healthy %s runner; running/busy service was not interrupted.\n' "$provider"
    elif [[ "$install_missing" == true ]]; then
      systemctl start "$AIF_OWNED_SERVICE" || exit
      aif_linux_runner_service "$provider" "$root" "$worker" || exit
      [[ "$AIF_OWNED_STATE" == active ]] || exit 1
    else
      printf '%s\n' 'Check only: registered service is stopped. No service was started.'
    fi
    exit 0
  fi
  [[ "$install_missing" == true ]] || { printf '%s\n' 'Check only: prerequisites ready, runner not registered.'; exit 0; }
  [[ -n "$token" && "$token" != *$'\n'* && "$token" != *$'\r'* ]] ||
    { printf '%s\n' 'A protected registration token is required for first registration.' >&2; exit 1; }
  aif_linux_runner_worker "$worker" "$home" true || exit
  install -d -m 750 -o "$worker" -g "$worker" "$root" || exit
  if [[ "$resume_verified" != true ]]; then
    local archive="$root/runner-package.tar.gz"
    [[ ! -e "$archive" && ! -L "$archive" ]] || exit 1
    trap 'rm -f -- "$archive"' EXIT
    aif_linux_runner_download "$provider" "${PackageUrl:-}" "${PackageSha256:-}" "$archive" || exit
    chown "root:$worker" "$archive" && chmod 640 "$archive" || exit
    runuser -u "$worker" -- tar --extract --gzip --no-same-owner --file "$archive" --directory "$root" || exit
  fi
  aif_linux_runner_worker_check "$worker" "$home" "$root" "$script" "$path" || exit
  if ! printf '%s\n' "$token" | aif_linux_runner_configure "$worker" "$home" "$root" "$provider" "$url" "$pool" "$name" "$label" "$path"; then
    printf '%s\n' 'Runner configuration failed. Inspect the protected runner diagnostics; no registration was replaced.' >&2; exit 1
  fi
  token=''
  [[ "$(aif_linux_runner_scope "$provider" "$root" "$url" "$pool" "$name")" == true ]] || exit 1
  aif_linux_runner_install_service "$provider" "$root" "$worker" "$path" || exit
  aif_linux_runner_service "$provider" "$root" "$worker" || exit
  systemctl start "$AIF_OWNED_SERVICE" || exit
  aif_linux_runner_service "$provider" "$root" "$worker" || exit
  [[ "$AIF_OWNED_STATE" == active ]] || exit 1
  printf 'Registered %s Linux runner with a dedicated unprivileged worker.\n' "$provider"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  aif_linux_runner_main
fi
