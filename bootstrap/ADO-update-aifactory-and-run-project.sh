#!/usr/bin/env bash
# AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIF_UI_DIR="$SCRIPT_DIR"
for AIF_UI_LIBRARY in "$AIF_UI_DIR/ui/terminal.sh" "$AIF_UI_DIR/azure-enterprise-scale-ml/bootstrap/ui/terminal.sh"; do
  [[ ! -f "$AIF_UI_LIBRARY" ]] || break
done
if [[ ! -f "$AIF_UI_LIBRARY" ]]; then
  printf 'ERROR: AI Factory terminal library is missing. Copy bootstrap/ui alongside this script.\n' >&2
  exit 1
fi
source "$AIF_UI_LIBRARY"
readonly REPO_ROOT="${AIFACTORY_REPO_ROOT:-$SCRIPT_DIR}"
readonly SUBMODULE_PATH="azure-enterprise-scale-ml"
readonly SUBMODULE_BRANCH="main"
readonly BRANCH="${ADO_BRANCH:-main}"
readonly PIPELINE_NAME="${ADO_PIPELINE_NAME:-infra-project-genai}"
readonly PIPELINE_YAML_PATH="aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/infra-project-genai.yaml"
readonly VARIABLES_FILE="aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
readonly VARIABLES_TEMPLATE_FILE="aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables-template.yaml"
readonly CONFIG_FILE="aifactory/variables.json"
readonly CONFIG_TEMPLATE_FILE="aifactory/variables-template.json"
readonly RUNNER_SELECTION="${ADO_RUNNER_SELECTION:-from-config}"
readonly AZURE_DEVOPS_RESOURCE_URL="https://app.vssps.visualstudio.com/"
readonly ADO_SETTINGS_FILE="${ADO_SETTINGS_FILE:-$HOME/.aifactory-ado-settings.json}"
auth_method="${ADO_AUTH_METHOD:-aad}"

cd "$REPO_ROOT"

reviewed_project=false
if [[ -n "${AIFACTORY_TARGET_ENVIRONMENT:-}${AIFACTORY_PROJECT_NUMBER:-}${AIFACTORY_PROJECT_CONFIG:-}" ]]; then
  reviewed_project=true
  export AIFACTORY_USE_JSON_OVERRIDE=yes
  export AIFACTORY_REPO_ROOT="$REPO_ROOT"
  umask 077
fi

if [[ "${AIFACTORY_LAUNCHER_STABLE:-}" != "1" ]]; then
  state_dir="$HOME/.aifactory-update-state/ado-$$"
  stable_launcher="$state_dir/ADO-update-aifactory-and-run-project.sh"
  mkdir -p "$state_dir"
  mkdir -p "$state_dir/ui"
  cp "$AIF_UI_LIBRARY" "$state_dir/ui/terminal.sh"
  cp "${BASH_SOURCE[0]}" "$stable_launcher"
  if [[ "$reviewed_project" == "true" ]]; then
    deployment_helper="$SCRIPT_DIR/lib/project_deployment.py"
    if [[ ! -f "$deployment_helper" ]]; then
      deployment_helper="$REPO_ROOT/azure-enterprise-scale-ml/bootstrap/lib/project_deployment.py"
    fi
    [[ -f "$deployment_helper" ]] || { aif_error "Install lib/project_deployment.py for reviewed project deployment."; exit 1; }
    mkdir -p "$state_dir/lib"
    cp "$deployment_helper" "$state_dir/lib/project_deployment.py"
  fi
  chmod +x "$stable_launcher"
  export AIFACTORY_LAUNCHER_STABLE=1
  export AIFACTORY_LAUNCHER_STATE_DIR="$state_dir"
  export AIFACTORY_REPO_ROOT="$REPO_ROOT"
  exec bash "$stable_launcher" "$@"
fi

state_dir="${AIFACTORY_LAUNCHER_STATE_DIR:?Stable launcher state directory is missing.}"
trap 'rm -rf -- "$state_dir"' EXIT
project_only=false
resume_after_bootstrap=false
for argument in "$@"; do
  case "$argument" in
    --project-only)
      project_only=true
      ;;
    --resume-after-bootstrap)
      resume_after_bootstrap=true
      ;;
    --help|-h)
      printf 'Usage: %s [--project-only]\n' "$(basename "$0")"
      printf '  --project-only  Skip all AI Factory and template updates; trigger the project pipeline only.\n'
      exit 0
      ;;
    *)
      aif_error "Unsupported argument: $argument. Use --project-only or --help." >&2
      exit 1
      ;;
  esac
done
case "${AIFACTORY_PROJECT_ONLY:-false}" in
  true|TRUE|1|yes|YES)
    project_only=true
    ;;
  false|FALSE|0|no|NO|"")
    ;;
  *)
    aif_error "AIFACTORY_PROJECT_ONLY must be true or false." >&2
    exit 1
    ;;
esac

if [[ "$project_only" == "true" ]]; then
  aif_banner "AZURE DEVOPS / PROJECT ONLY" "Skip AI Factory updates. Trigger the existing project pipeline."
else
  aif_banner "AZURE DEVOPS / UPDATE + RUN" "Preserve configuration. Refresh templates. Deploy with intent."
fi
aif_value "Repository" "$REPO_ROOT"
aif_value "Branch" "$BRANCH"
aif_section "01 / Configuration"

confirm_commit_and_continue() {
  local choice="${AIFACTORY_COMMIT_CHANGES:-}"
  while true; do
    if [[ -z "$choice" && -t 0 ]]; then
      read -r -p "$(aif_prompt "Commit and continue? [y/N]: ")" choice
    fi
    case "${choice,,}" in
      y|yes)
        return 0
        ;;
      ""|n|no)
        return 1
        ;;
      *)
        aif_warn "Please enter 'y' for Yes or 'n' for No. Press Enter for No." >&2
        if [[ ! -t 0 ]]; then
          return 1
        fi
        choice=""
        ;;
    esac
  done
}

json_override_choice="${AIFACTORY_USE_JSON_OVERRIDE:-}"
while true; do
  if [[ -z "$json_override_choice" && -t 0 ]]; then
    read -r -p "$(aif_prompt "Do you want to override with variables.json? [y/N]: ")" json_override_choice
  fi
  case "${json_override_choice,,}" in
    y|yes)
      use_json_override=true
      config_override_file="$CONFIG_FILE"
      aif_info "JSON override enabled: $CONFIG_FILE"
      break
      ;;
    ""|n|no)
      use_json_override=false
      config_override_file=""
      aif_info "JSON override disabled; the pipeline will use variables.yaml."
      break
      ;;
    *)
      aif_warn "Please enter 'y' for Yes or 'n' for No. Press Enter for No." >&2
      json_override_choice=""
      ;;
  esac
done

for command in git az; do
  if ! command -v "$command" >/dev/null 2>&1; then
    aif_error "Required command '$command' is not available." >&2
    exit 1
  fi
done
if command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
  PYTHON=(python)
elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
  PYTHON=(py -3)
elif command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
  PYTHON=(python3)
else
  aif_error "A working Python 3 interpreter is required." >&2
  exit 1
fi

if [[ "$reviewed_project" == "true" ]]; then
  export AIFACTORY_PROJECT_ONLY="$project_only"
  helper_path="$SCRIPT_DIR/lib/project_deployment.py"
  helper_state_dir="$state_dir"
  if command -v cygpath >/dev/null 2>&1; then
    helper_path="$(cygpath -m "$helper_path")"
    helper_state_dir="$(cygpath -m "$helper_state_dir")"
    export AIFACTORY_REPO_ROOT="$(cygpath -m "$REPO_ROOT")"
    if [[ -n "${AIFACTORY_PROJECT_CONFIG:-}" ]]; then
      export AIFACTORY_PROJECT_CONFIG="$(cygpath -m "$AIFACTORY_PROJECT_CONFIG")"
    fi
  fi
  "${PYTHON[@]}" "$helper_path" --route ado --state-dir "$helper_state_dir"
  exit "$?"
fi

ado_repository_name="${ADO_REPOSITORY_NAME:-}"
if [[ -z "$ado_repository_name" ]]; then
  origin_url=$(git remote get-url origin)
  ado_repository_name=$("${PYTHON[@]}" -c '
import sys
from urllib.parse import unquote, urlparse

url = sys.argv[1].rstrip("/")
parsed = urlparse(url)
path = unquote(parsed.path).rstrip("/")
if "/_git/" in path:
    name = path.rsplit("/_git/", 1)[1]
elif parsed.scheme:
    name = path.rsplit("/", 1)[-1]
else:
    name = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
print(name.removesuffix(".git"))
' "$origin_url")
fi

read_saved_setting() {
  local name="$1"
  if [[ ! -f "$ADO_SETTINGS_FILE" ]]; then
    return
  fi
  "${PYTHON[@]}" -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as settings_file:
    value = json.load(settings_file).get(sys.argv[2], "")
if isinstance(value, str):
    print(value)
' "$ADO_SETTINGS_FILE" "$name"
}

aif_section "02 / Azure DevOps connection"
devops_defaults=""
if az extension show --name azure-devops >/dev/null 2>&1; then
  devops_defaults=$(az devops configure --list 2>/dev/null || true)
fi
read_devops_default() {
  local name="$1"
  printf '%s\n' "$devops_defaults" | "${PYTHON[@]}" -c '
import sys

target = sys.argv[1]
for line in sys.stdin:
    key, separator, value = line.partition("=")
    if separator and key.strip() == target:
        print(value.strip())
        break
' "$name"
}

ado_organization="${ADO_ORGANIZATION:-}"
ado_project="${ADO_PROJECT:-}"
if [[ -z "$ado_organization" ]]; then
  ado_organization="$(read_saved_setting organization)"
fi
if [[ -z "$ado_project" ]]; then
  ado_project="$(read_saved_setting project)"
fi
if [[ -z "$ado_organization" ]]; then
  ado_organization="$(read_devops_default organization)"
fi
if [[ -z "$ado_project" ]]; then
  ado_project="$(read_devops_default project)"
fi
devops_defaults_prompted=false
if [[ -z "$ado_organization" || -z "$ado_project" ]]; then
  if [[ ! -t 0 ]]; then
    aif_error "Azure DevOps organization and project are required in non-interactive mode." >&2
    aif_info "Set ADO_ORGANIZATION and ADO_PROJECT before starting this script." >&2
    exit 1
  fi
  aif_warn "Azure DevOps settings are not configured. Enter them once; they will be saved locally for future runs."
fi
while [[ -z "$ado_organization" ]]; do
  read -r -p "$(aif_prompt "Azure DevOps organization name or URL: ")" ado_organization
  devops_defaults_prompted=true
done
while [[ -z "$ado_project" ]]; do
  read -r -p "$(aif_prompt "Azure DevOps project name: ")" ado_project
  devops_defaults_prompted=true
done
case "$ado_organization" in
  http://*|https://*) ;;
  *) ado_organization="https://dev.azure.com/$ado_organization" ;;
esac
ado_organization="${ado_organization%/}"
if [[ "$devops_defaults_prompted" == "true" ]]; then
  "${PYTHON[@]}" - "$ADO_SETTINGS_FILE" "$ado_organization" "$ado_project" <<'PY'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(
    json.dumps({"organization": sys.argv[2], "project": sys.argv[3]}, indent=2) + "\n",
    encoding="utf-8",
)
PY
  aif_success "Saved Azure DevOps organization and project locally for future runs."
fi

configure_pat_auth() {
  if [[ -z "${AZURE_DEVOPS_EXT_PAT:-}" ]]; then
    if [[ ! -t 0 ]]; then
      aif_error "AZURE_DEVOPS_EXT_PAT is required for PAT authentication." >&2
      return 1
    fi
    aif_info "Personal Microsoft accounts require an Azure DevOps PAT with Build Read & execute permission."
    aif_info "Create one at: $ado_organization/_usersSettings/tokens"
    read -r -s -p "$(aif_prompt "Azure DevOps PAT (input is hidden): ")" AZURE_DEVOPS_EXT_PAT
    echo
  fi
  if [[ -z "$AZURE_DEVOPS_EXT_PAT" ]]; then
    aif_error "An empty Azure DevOps PAT cannot be used." >&2
    return 1
  fi
  auth_method=pat
}

login_with_entra() {
  local -a login_args
  login_args=(login --allow-no-subscriptions)
  if [[ -n "$ado_tenant" ]]; then
    login_args+=(--tenant "$ado_tenant")
  fi

  aif_info "Opening browser sign-in for Microsoft Entra authentication..." >&2
  aif_info "In the browser account picker, select 'Use another account' and enter the full email address." >&2
  aif_info "No Azure subscription is required; this sign-in is only for Azure DevOps." >&2
  AZURE_CORE_LOGIN_EXPERIENCE_V2=off az "${login_args[@]}" >/dev/null
}

ado_tenant="${ADO_TENANT:-}"
tenant_config_prompted=false
if [[ -z "$ado_tenant" ]]; then
  if [[ "$use_json_override" == "true" ]]; then
    tenant_config_source="$CONFIG_FILE"
    if [[ ! -f "$CONFIG_FILE" ]]; then
      aif_error "JSON override is enabled, but configuration file is missing: $CONFIG_FILE" >&2
      exit 1
    fi
    ado_tenant=$("${PYTHON[@]}" - "$CONFIG_FILE" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
dev = config.get("dev", {})
if isinstance(dev, dict):
    print(str(dev.get("azureDevOpsTenantId", "")).strip())
PY
)
  else
    tenant_config_source="$VARIABLES_FILE"
    if [[ ! -f "$VARIABLES_FILE" ]]; then
      aif_error "Azure DevOps variables file is missing: $VARIABLES_FILE" >&2
      exit 1
    fi
    ado_tenant=$("${PYTHON[@]}" - "$VARIABLES_FILE" <<'PY'
import re
import sys
from pathlib import Path

assignment = re.compile(r"^\s*azureDevOpsTenantId:\s*(.*?)\s*(?:#.*)?$")
for line in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines():
    match = assignment.match(line)
    if match:
        print(match.group(1).strip().strip("'\""))
        break
PY
)
  fi
else
  tenant_config_source="ADO_TENANT"
fi

if [[ -z "$ado_tenant" || "$ado_tenant" == *"<todo>"* || "$ado_tenant" == '$('* ||
      "$ado_tenant" =~ [[:space:]/] ]]; then
  if [[ ! -t 0 ]]; then
    aif_error "azureDevOpsTenantId is missing or unresolved in $tenant_config_source." >&2
    aif_info "Set it to the Microsoft Entra tenant connected to the Azure DevOps organization." >&2
    exit 1
  fi
  aif_warn "azureDevOpsTenantId is missing or unresolved in $tenant_config_source."
  aif_info "Use the Microsoft Entra tenant connected to the Azure DevOps organization, not tenantId used for Azure deployments."
  while true; do
    read -r -p "$(aif_prompt "Azure DevOps-connected Entra tenant ID/domain: ")" ado_tenant
    if [[ -n "$ado_tenant" && "$ado_tenant" != *"<todo>"* &&
          "$ado_tenant" != '$('* && ! "$ado_tenant" =~ [[:space:]/] ]]; then
      break
    fi
    aif_info "Enter a tenant GUID or verified tenant domain without spaces." >&2
  done
  tenant_config_prompted=true
fi

if [[ "$tenant_config_prompted" == "true" ]]; then
  if [[ "$use_json_override" == "true" ]]; then
    "${PYTHON[@]}" - "$CONFIG_FILE" "$ado_tenant" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
config = json.loads(path.read_text(encoding="utf-8-sig"))
for section in ("dev", "stage_prod"):
    values = config.get(section)
    if isinstance(values, dict):
        values["azureDevOpsTenantId"] = sys.argv[2]
path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
PY
  else
    "${PYTHON[@]}" - "$VARIABLES_FILE" "$ado_tenant" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
tenant = sys.argv[2]
lines = path.read_text(encoding="utf-8-sig").splitlines()
assignment = re.compile(r"^(\s*)azureDevOpsTenantId:\s*.*$")
for index, line in enumerate(lines):
    match = assignment.match(line)
    if match:
        lines[index] = f'{match.group(1)}azureDevOpsTenantId: "{tenant}"'
        break
else:
    tenant_line = next(
        (index for index, line in enumerate(lines) if re.match(r"^\s*tenantId:", line)),
        None,
    )
    insert_at = tenant_line + 1 if tenant_line is not None else 1
    lines.insert(insert_at, f'  azureDevOpsTenantId: "{tenant}"')
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  fi
  aif_success "Saved azureDevOpsTenantId to $tenant_config_source."
fi
aif_info "Using Azure DevOps-connected Entra tenant from $tenant_config_source."

case "${auth_method,,}" in
  aad|entra)
    unset AZURE_DEVOPS_EXT_PAT
    if ! az account show >/dev/null 2>&1; then
      if [[ ! -t 0 ]]; then
        aif_error "An Azure CLI Microsoft Entra session is required in non-interactive mode." >&2
        aif_info "Run 'AZURE_CORE_LOGIN_EXPERIENCE_V2=off az login --tenant \"$ado_tenant\" --allow-no-subscriptions' before starting this script." >&2
        exit 1
      fi
      aif_info "No active Azure CLI Microsoft Entra session was found."
      if ! login_with_entra; then
        aif_warn "Browser sign-in was blocked or canceled. Falling back to Azure DevOps PAT authentication."
        configure_pat_auth
      fi
    fi
    ;;
  pat|msa)
    configure_pat_auth
    ;;
  *)
    aif_error "Unsupported ADO_AUTH_METHOD '$auth_method'. Use 'aad' (default) or 'pat'." >&2
    exit 1
    ;;
esac

backup_dir="$HOME/.aifactory-backups/$(basename "$REPO_ROOT")/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"

url_encode() {
  "${PYTHON[@]}" -c 'import sys; from urllib.parse import quote; print(quote(sys.argv[1], safe=""))' "$1"
}

refresh_ado_auth_header() {
  local token token_error
  if [[ "${auth_method,,}" == "pat" ]]; then
    ado_auth_header=$(AZURE_DEVOPS_EXT_PAT="$AZURE_DEVOPS_EXT_PAT" "${PYTHON[@]}" -c '
import base64
import os

credential = base64.b64encode(
    (":" + os.environ["AZURE_DEVOPS_EXT_PAT"]).encode()
).decode()
print(f"Basic {credential}")
')
    if [[ -z "$ado_auth_header" ]]; then
      aif_error "Failed to construct the Azure DevOps PAT authorization header." >&2
      return 1
    fi
    return 0
  fi

  local -a token_args
  token_args=(
    account get-access-token
    --resource "$AZURE_DEVOPS_RESOURCE_URL"
    --query accessToken
    --output tsv
  )
  if [[ -n "$ado_tenant" ]]; then
    token_args+=(--tenant "$ado_tenant")
  fi

  if ! token=$(az "${token_args[@]}" 2>&1); then
    token_error="$token"
    aif_info "Azure CLI authentication expired or became unavailable during the update." >&2
    if [[ -n "$token_error" ]]; then
      aif_info "$token_error" >&2
    fi
    if [[ ! -t 0 ]]; then
      aif_error "Interactive Microsoft Entra sign-in is required to continue." >&2
      return 1
    fi
    if ! login_with_entra; then
      aif_error "Microsoft Entra sign-in failed or was canceled." >&2
      return 1
    fi
    if ! token=$(az "${token_args[@]}" 2>&1); then
      token_error="$token"
      aif_error "Could not acquire an Azure DevOps access token after signing in." >&2
      if [[ -n "$token_error" ]]; then
        aif_info "$token_error" >&2
      fi
      return 1
    fi
  fi

  token="${token//$'\r'/}"
  token="${token//$'\n'/}"
  if [[ -z "$token" ]]; then
    aif_error "Azure CLI returned an empty Azure DevOps access token." >&2
    return 1
  fi
  ado_auth_header="Bearer $token"
}

ado_request() {
  local method="$1"
  local url="$2"
  local input_file="${3:-}"
  if ! refresh_ado_auth_header; then
    return 1
  fi
  ADO_AUTH_HEADER="$ado_auth_header" "${PYTHON[@]}" - "$method" "$url" "$input_file" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

method, url, input_file = sys.argv[1:4]
data = None
if input_file:
    with open(input_file, "rb") as request_file:
        data = request_file.read()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

request = urllib.request.Request(
    url,
    data=data,
    method=method,
    headers={
        "Accept": "application/json",
        "Authorization": os.environ["ADO_AUTH_HEADER"],
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.build_opener(NoRedirect).open(request) as response:
        sys.stdout.buffer.write(response.read())
except urllib.error.HTTPError as error:
    body = error.read().decode("utf-8", errors="replace")
    if error.code in {301, 302, 303, 307, 308}:
        print("ERROR: Azure DevOps redirected this identity to sign-in.", file=sys.stderr)
        raise SystemExit(42)
    message = body
    try:
        payload = json.loads(body)
        message = payload.get("message") or payload.get("error", {}).get("message") or body
    except json.JSONDecodeError:
        pass
    print(f"ERROR: Azure DevOps API returned HTTP {error.code}: {message}", file=sys.stderr)
    raise SystemExit(1)
except urllib.error.URLError as error:
    print(f"ERROR: Azure DevOps API request failed: {error.reason}", file=sys.stderr)
    raise SystemExit(1)
PY
}

ado_project_encoded="$(url_encode "$ado_project")"
ado_api_base="$ado_organization/$ado_project_encoded/_apis"
pipelines_url="$ado_api_base/build/definitions?includeAllProperties=true&api-version=7.1&%24top=1000"
ado_entra_settings_url="$ado_organization/_settings/organizationAad"

if ado_request GET "$pipelines_url" > "$state_dir/pipelines.json"; then
  :
else
  request_status=$?
  if [[ "$request_status" -ne 42 || "${auth_method,,}" == "pat" ]]; then
    exit "$request_status"
  fi
  aif_error "azureDevOpsTenantId from $tenant_config_source cannot access Azure DevOps organization '$ado_organization' project '$ado_project'." >&2
  aif_info "Verify the connected directory at: $ado_entra_settings_url" >&2
  aif_info "Update azureDevOpsTenantId in $tenant_config_source, or set ADO_TENANT explicitly, then retry." >&2
  exit 1
fi

pipeline_id=$("${PYTHON[@]}" - "$state_dir/pipelines.json" "$PIPELINE_YAML_PATH" "$PIPELINE_NAME" "$ado_repository_name" <<'PY'
import json
import sys
from pathlib import PurePosixPath

payload = json.loads(open(sys.argv[1], encoding="utf-8-sig").read())
pipelines = payload.get("value", []) if isinstance(payload, dict) else payload
target_path = str(PurePosixPath(sys.argv[2].replace("\\", "/"))).lstrip("/").lower()
target_name = sys.argv[3].lower()
target_repository = sys.argv[4].lower()

path_matches = []
name_matches = []
for pipeline in pipelines:
    if str(pipeline.get("queueStatus") or "enabled").lower() != "enabled":
        continue
    process = pipeline.get("process") or pipeline.get("configuration") or {}
    repository = pipeline.get("repository") or {}
    repository_name = str(repository.get("name") or repository.get("id") or "").lower()
    if repository_name and repository_name != target_repository:
        continue
    yaml_path = str(
        process.get("yamlFilename") or process.get("path") or ""
    ).replace("\\", "/").lstrip("/").lower()
    if yaml_path == target_path:
        path_matches.append(pipeline)
    if str(pipeline.get("name") or "").lower() == target_name:
        name_matches.append(pipeline)

matches = path_matches or name_matches
if len(matches) != 1:
    reason = "not found" if not matches else "ambiguous"
    raise SystemExit(
        f"Enabled Azure DevOps pipeline is {reason}; expected YAML path {sys.argv[2]!r} "
        f"or pipeline name {sys.argv[3]!r} in repository {sys.argv[4]!r}."
    )
print(
    f"Using Azure DevOps pipeline {matches[0]['name']!r} "
    f"(ID {matches[0]['id']}) from repository {sys.argv[4]!r}.",
    file=sys.stderr,
)
print(matches[0]["id"])
PY
)

if [[ ! -f "$VARIABLES_FILE" ]]; then
  aif_error "Active Azure DevOps variables file is missing: $VARIABLES_FILE" >&2
  exit 1
fi
if [[ "$use_json_override" == "true" && ! -f "$CONFIG_FILE" ]]; then
  aif_error "Active JSON configuration file is missing: $CONFIG_FILE" >&2
  exit 1
fi
stash_created=false
submodule_stash_created=false
if [[ "$project_only" == "true" ]]; then
  aif_section "03 / Project-only mode"
  aif_info "Skipping submodule pull, template refresh, configuration merge, pipeline preview, and Git commit/push."
else
  cp "$VARIABLES_FILE" "$state_dir/variables.yaml"
  cp "$VARIABLES_FILE" "$backup_dir/variables.yaml"
  if [[ "$use_json_override" == "true" ]]; then
    cp "$CONFIG_FILE" "$state_dir/variables.json"
    cp "$CONFIG_FILE" "$backup_dir/variables.json"
  fi

  aif_section "03 / Protect local work and refresh templates"
  if [[ "$resume_after_bootstrap" == "false" ]]; then
  if [[ -d "$SUBMODULE_PATH/.git" || -f "$SUBMODULE_PATH/.git" ]] &&
     [[ -n "$(git -C "$SUBMODULE_PATH" status --porcelain)" ]]; then
    git -C "$SUBMODULE_PATH" stash push \
      --include-untracked \
      --message "Before AI Factory submodule update $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      >/dev/null
    submodule_stash_created=true
    aif_success "Existing submodule work was protected in: $(git -C "$SUBMODULE_PATH" stash list -1 --format='%gd %s')"
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    stash_message="Before AI Factory template update $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git stash push --include-untracked --message "$stash_message" >/dev/null
    stash_created=true
    aif_success "Existing work was protected in: $(git stash list -1 --format='%gd %s')"
  fi

  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
  git submodule update --init --recursive --remote
  git submodule foreach "git checkout '$SUBMODULE_BRANCH' && git pull --ff-only origin '$SUBMODULE_BRANCH'"

  printf 'a\n' | bash "$SUBMODULE_PATH/00-start.sh"
  bash "01-aif-copy-aifactory-templates.sh"
    bash "03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"
  fi
fi

if [[ "$project_only" == "false" && ! -f "$VARIABLES_TEMPLATE_FILE" ]]; then
  aif_error "Azure DevOps variables template was not generated: $VARIABLES_TEMPLATE_FILE" >&2
  exit 1
fi
if [[ "$project_only" == "false" && "$use_json_override" == "true" && ! -f "$CONFIG_TEMPLATE_FILE" ]]; then
  aif_error "JSON configuration template was not generated: $CONFIG_TEMPLATE_FILE" >&2
  exit 1
fi

if [[ "$project_only" == "false" ]]; then
  aif_section "04 / Configuration changes"
"${PYTHON[@]}" - \
  "$state_dir/variables.yaml" \
  "$VARIABLES_TEMPLATE_FILE" \
  "$state_dir/variables.json" \
  "$CONFIG_TEMPLATE_FILE" \
  "$use_json_override" <<'PY' | aif_stream
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

active_yaml_path = Path(sys.argv[1])
template_yaml_path = Path(sys.argv[2])
active_json_path = Path(sys.argv[3])
template_json_path = Path(sys.argv[4])
use_json = sys.argv[5] == "true"
removed_keys = {"useAdminVMBuildAgent"}
assignment = re.compile(r"^\s{2}([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")


def split_comment(text):
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "#" and (index == 0 or text[index - 1].isspace()):
            return text[:index].rstrip()
    return text.rstrip()


def yaml_values(path):
    values = OrderedDict()
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = assignment.match(line)
        if match:
            values[match.group(1)] = split_comment(match.group(2))
    return values


def flatten_new(template, active, prefix=""):
    changes = []
    for key, value in template.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in active:
            if isinstance(value, dict) and value:
                changes.extend(flatten_new(value, {}, path))
            else:
                changes.append((path, value))
        elif isinstance(value, dict) and isinstance(active[key], dict):
            changes.extend(flatten_new(value, active[key], path))
    return changes


def find_removed(value, prefix=""):
    removed = []
    if not isinstance(value, dict):
        return removed
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if key in removed_keys:
            removed.append(path)
        elif isinstance(child, dict):
            removed.extend(find_removed(child, path))
    return removed


def print_section(label, new_values, removed):
    if not new_values and not removed:
        return False
    print(f"\n{label}")
    if new_values:
        print("  New variables and template defaults:")
        for name, value in new_values:
            default = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            print(f"    {name} = {default}")
    if removed:
        print("  Removed variables:")
        for name in removed:
            print(f"    {name}")
    return True


active_yaml = yaml_values(active_yaml_path)
template_yaml = yaml_values(template_yaml_path)
found = print_section(
    "variables.yaml",
    [(key, value) for key, value in template_yaml.items() if key not in active_yaml],
    [key for key in active_yaml if key in removed_keys],
)

if use_json:
    active_json = json.loads(
        active_json_path.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict
    )
    template_json = json.loads(
        template_json_path.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict
    )
    found = print_section(
        "variables.json",
        flatten_new(template_json, active_json),
        find_removed(active_json),
    ) or found

if not found:
    print("\nVariable template changes: no new or removed variables.")
PY

"${PYTHON[@]}" - "$VARIABLES_TEMPLATE_FILE" "$state_dir/variables.yaml" "$VARIABLES_FILE" <<'PY'
import re
import sys
from collections import OrderedDict
from pathlib import Path

template_path = Path(sys.argv[1])
active_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
assignment = re.compile(r"^(\s{2})([A-Za-z_][A-Za-z0-9_-]*):(\s*)(.*)$")

def split_value_comment(text):
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "#" and (index == 0 or text[index - 1].isspace()):
            return text[:index].rstrip(), text[index:]
    return text.rstrip(), ""

def read_assignments(path):
    values = OrderedDict()
    lines = OrderedDict()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = assignment.match(line)
        if not match:
            continue
        key = match.group(2)
        if key in values:
            raise SystemExit(f"Duplicate variable {key!r} in {path}")
        values[key] = split_value_comment(match.group(4))[0]
        lines[key] = line
    return values, lines

active, active_lines = read_assignments(active_path)
template, _ = read_assignments(template_path)
if not active:
    raise SystemExit(f"No variables found in active file: {active_path}")
if not template:
    raise SystemExit(f"No variables found in template file: {template_path}")

used = set()
result = []
for line in template_path.read_text(encoding="utf-8-sig").splitlines():
    match = assignment.match(line)
    if not match:
        result.append(line)
        continue
    indent, key, spacing, remainder = match.groups()
    if key not in active:
        result.append(line)
        continue
    _, comment = split_value_comment(remainder)
    comment_suffix = f" {comment}" if comment else ""
    result.append(f"{indent}{key}:{spacing}{active[key]}{comment_suffix}")
    used.add(key)

removed_keys = {"useAdminVMBuildAgent"}
legacy = [key for key in active if key not in used and key not in removed_keys]
if legacy:
    result.extend(["", "  # Legacy values preserved from the previous variables.yaml"])
    result.extend(active_lines[key] for key in legacy)

output_path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY

if [[ "$use_json_override" == "true" ]]; then
  "${PYTHON[@]}" - "$CONFIG_TEMPLATE_FILE" "$state_dir/variables.json" "$CONFIG_FILE" <<'PY'
import json
import sys
from collections import OrderedDict
from pathlib import Path

template_path = Path(sys.argv[1])
active_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
template = json.loads(template_path.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict)
active = json.loads(active_path.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict)
removed_keys = {"useAdminVMBuildAgent"}

def merge(template_value, active_value):
    if isinstance(template_value, dict) and isinstance(active_value, dict):
        merged = OrderedDict()
        for key, value in template_value.items():
            merged[key] = merge(value, active_value[key]) if key in active_value else value
        for key, value in active_value.items():
            if key not in merged and key not in removed_keys:
                merged[key] = value
        return merged
    return active_value

output_path.write_text(json.dumps(merge(template, active), indent=2) + "\n", encoding="utf-8")
PY
fi

rm -f "$VARIABLES_TEMPLATE_FILE" "$CONFIG_TEMPLATE_FILE"
fi

if [[ "$project_only" == "false" ]]; then
"${PYTHON[@]}" - "$state_dir/preview-request.json" "$BRANCH" "$CONFIG_FILE" "$RUNNER_SELECTION" "$use_json_override" "$PIPELINE_YAML_PATH" <<'PY'
import json
import sys
from pathlib import Path

request = {
    "previewRun": True,
    "resources": {
        "repositories": {
            "self": {
                "refName": f"refs/heads/{sys.argv[2]}",
            }
        }
    },
    "templateParameters": {
        "configFile": sys.argv[3],
        "runnerSelection": sys.argv[4],
        "useJsonConfigOverride": sys.argv[5] == "true",
    },
    "stagesToSkip": [
        "Stage_GenAI_Project",
        "Prod_GenAI_Project",
    ],
    "yamlOverride": Path(sys.argv[6]).read_text(encoding="utf-8-sig"),
}
Path(sys.argv[1]).write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
PY

aif_section "05 / Validate pipeline"
aif_info "Compiling the pipeline before commit and push..."
ado_request \
  POST \
  "$ado_api_base/pipelines/$pipeline_id/runs?api-version=7.1" \
  "$state_dir/preview-request.json" \
  > "$state_dir/preview-response.json"
"${PYTHON[@]}" - "$state_dir/preview-response.json" <<'PY'
import json
import sys

response = json.loads(open(sys.argv[1], encoding="utf-8-sig").read())
if not response.get("finalYaml"):
    raise SystemExit("Azure DevOps preview did not return compiled YAML.")
PY
aif_success "Azure DevOps pipeline validation succeeded."

cp "$state_dir/ADO-update-aifactory-and-run-project.sh" "$REPO_ROOT/ADO-update-aifactory-and-run-project.sh"
chmod +x "$REPO_ROOT/ADO-update-aifactory-and-run-project.sh"

aif_section "06 / Review and publish"
git add -A
if ! git diff --cached --quiet; then
  if ! confirm_commit_and_continue; then
    git restore --staged -- .
    aif_warn "Commit declined. Changes remain in the working tree; no push or pipeline run was started."
    exit 0
  fi
  git commit \
    -m "Update AI Factory templates and Azure DevOps pipeline" \
    -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
  git push origin "$BRANCH"
else
  aif_info "No tracked template changes required a commit."
fi
fi

"${PYTHON[@]}" - "$state_dir/run-request.json" "$BRANCH" "$CONFIG_FILE" "$RUNNER_SELECTION" "$use_json_override" <<'PY'
import json
import sys
from pathlib import Path

request = {
    "resources": {
        "repositories": {
            "self": {
                "refName": f"refs/heads/{sys.argv[2]}",
            }
        }
    },
    "templateParameters": {
        "configFile": sys.argv[3],
        "runnerSelection": sys.argv[4],
        "useJsonConfigOverride": sys.argv[5] == "true",
    },
    "stagesToSkip": [
        "Stage_GenAI_Project",
        "Prod_GenAI_Project",
    ],
}
Path(sys.argv[1]).write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
PY

ado_request \
  POST \
  "$ado_api_base/pipelines/$pipeline_id/runs?api-version=7.1" \
  "$state_dir/run-request.json" \
  > "$state_dir/run.json"

mapfile -t run_details < <("${PYTHON[@]}" - "$state_dir/run.json" <<'PY'
import json
import sys

run = json.loads(open(sys.argv[1], encoding="utf-8-sig").read())
print(run["id"])
print(((run.get("_links") or {}).get("web") or {}).get("href") or "")
PY
)
run_id="${run_details[0]%$'\r'}"
run_url="${run_details[1]:-}"
run_url="${run_url%$'\r'}"
if [[ ! "$run_id" =~ ^[0-9]+$ ]]; then
  aif_error "Azure DevOps returned an invalid run ID: $(printf '%q' "$run_id")" >&2
  exit 1
fi

aif_section "07 / Deployment"
aif_value "Run" "$run_id"
if [[ -n "$run_url" ]]; then
  aif_value "Open in browser" "$run_url"
fi

while true; do
  ado_request \
    GET \
    "$ado_api_base/pipelines/$pipeline_id/runs/$run_id?api-version=7.1" \
    > "$state_dir/run-status.json"
  mapfile -t run_state < <("${PYTHON[@]}" - "$state_dir/run-status.json" <<'PY'
import json
import sys

run = json.loads(open(sys.argv[1], encoding="utf-8-sig").read())
print(run.get("state") or run.get("status") or "")
print(run.get("result") or "")
PY
)
  run_status="${run_state[0]%$'\r'}"
  run_result="${run_state[1]:-}"
  run_result="${run_result%$'\r'}"
  if [[ "$run_status" == "completed" ]]; then
    break
  fi
  sleep 15
done

if [[ "$run_result" != "succeeded" ]]; then
  aif_error "Azure DevOps run $run_id completed with result: ${run_result:-unknown}" >&2
  exit 1
fi

if [[ "$stash_created" == "true" ]]; then
  aif_info "Pre-existing work remains protected in $(git stash list -1 --format='%gd')."
  aif_warn "Review generated changes before restoring that stash to avoid overwriting the update."
fi
if [[ "$submodule_stash_created" == "true" ]]; then
  aif_info "Pre-existing submodule work remains protected in $(git -C "$SUBMODULE_PATH" stash list -1 --format='%gd')."
fi
aif_value "Backups" "$backup_dir"
aif_complete "Azure DevOps run $run_id succeeded."
