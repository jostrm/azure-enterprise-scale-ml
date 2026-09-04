#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="${AIFACTORY_REPO_ROOT:-$SCRIPT_DIR}"
readonly SUBMODULE_PATH="azure-enterprise-scale-ml"
readonly SUBMODULE_BRANCH="release/v1.24"
readonly BRANCH="${ADO_BRANCH:-main}"
readonly PIPELINE_NAME="${ADO_PIPELINE_NAME:-infra-project-genai}"
readonly PIPELINE_YAML_PATH="aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/infra-project-genai.yaml"
readonly VARIABLES_FILE="aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml"
readonly VARIABLES_TEMPLATE_FILE="aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables-template.yaml"
readonly CONFIG_FILE="aifactory/variables.json"
readonly CONFIG_TEMPLATE_FILE="aifactory/variables-template.json"
readonly RUNNER_SELECTION="${ADO_RUNNER_SELECTION:-self-hosted}"
readonly AZURE_DEVOPS_RESOURCE_URL="https://app.vssps.visualstudio.com/"
readonly ADO_SETTINGS_FILE="${ADO_SETTINGS_FILE:-$HOME/.aifactory-ado-settings.json}"
auth_method="${ADO_AUTH_METHOD:-aad}"

cd "$REPO_ROOT"

if [[ "${AIFACTORY_LAUNCHER_STABLE:-}" != "1" ]]; then
  state_dir="$HOME/.aifactory-update-state/ado-$$"
  stable_launcher="$state_dir/ADO-update-aifactory-and-run-project.sh"
  mkdir -p "$state_dir"
  cp "${BASH_SOURCE[0]}" "$stable_launcher"
  chmod +x "$stable_launcher"
  export AIFACTORY_LAUNCHER_STABLE=1
  export AIFACTORY_LAUNCHER_STATE_DIR="$state_dir"
  export AIFACTORY_REPO_ROOT="$REPO_ROOT"
  exec bash "$stable_launcher" "$@"
fi

state_dir="${AIFACTORY_LAUNCHER_STATE_DIR:?Stable launcher state directory is missing.}"
trap 'rm -rf -- "$state_dir"' EXIT

for command in git az; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "ERROR: Required command '$command' is not available." >&2
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
  echo "ERROR: A working Python 3 interpreter is required." >&2
  exit 1
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
    echo "ERROR: Azure DevOps organization and project are required in non-interactive mode." >&2
    echo "Set ADO_ORGANIZATION and ADO_PROJECT before starting this script." >&2
    exit 1
  fi
  echo "Azure DevOps settings are not configured. Enter them once; they will be saved locally for future runs."
fi
while [[ -z "$ado_organization" ]]; do
  read -r -p "Azure DevOps organization name or URL: " ado_organization
  devops_defaults_prompted=true
done
while [[ -z "$ado_project" ]]; do
  read -r -p "Azure DevOps project name: " ado_project
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
  echo "Saved Azure DevOps organization and project locally for future runs."
fi

configure_pat_auth() {
  if [[ -z "${AZURE_DEVOPS_EXT_PAT:-}" ]]; then
    if [[ ! -t 0 ]]; then
      echo "ERROR: AZURE_DEVOPS_EXT_PAT is required for PAT authentication." >&2
      return 1
    fi
    echo "Personal Microsoft accounts require an Azure DevOps PAT with Build Read & execute permission."
    echo "Create one at: $ado_organization/_usersSettings/tokens"
    read -r -s -p "Azure DevOps PAT (input is hidden): " AZURE_DEVOPS_EXT_PAT
    echo
  fi
  if [[ -z "$AZURE_DEVOPS_EXT_PAT" ]]; then
    echo "ERROR: An empty Azure DevOps PAT cannot be used." >&2
    return 1
  fi
  auth_method=pat
}

ado_tenant="${ADO_TENANT:-}"
case "${auth_method,,}" in
  aad|entra)
    unset AZURE_DEVOPS_EXT_PAT
    if ! az account show >/dev/null 2>&1; then
      if [[ ! -t 0 ]]; then
        echo "ERROR: An Azure CLI Microsoft Entra session is required in non-interactive mode." >&2
        echo "Run 'AZURE_CORE_LOGIN_EXPERIENCE_V2=off az login --allow-no-subscriptions' before starting this script." >&2
        exit 1
      fi
      echo "No active Azure CLI Microsoft Entra session was found. Opening browser sign-in..."
      echo "In the browser account picker, select 'Use another account' and enter the full email address."
      echo "No Azure subscription is required; this sign-in is only for Azure DevOps."
      if ! AZURE_CORE_LOGIN_EXPERIENCE_V2=off \
        az login --allow-no-subscriptions >/dev/null; then
        echo "Browser sign-in was blocked or canceled. Falling back to Azure DevOps PAT authentication."
        configure_pat_auth
      fi
    fi
    ;;
  pat|msa)
    configure_pat_auth
    ;;
  *)
    echo "ERROR: Unsupported ADO_AUTH_METHOD '$auth_method'. Use 'aad' (default) or 'pat'." >&2
    exit 1
    ;;
esac

backup_dir="$HOME/.aifactory-backups/$(basename "$REPO_ROOT")/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"

url_encode() {
  "${PYTHON[@]}" -c 'import sys; from urllib.parse import quote; print(quote(sys.argv[1], safe=""))' "$1"
}

get_ado_auth_header() {
  local token
  if [[ "${auth_method,,}" == "pat" ]]; then
    AZURE_DEVOPS_EXT_PAT="$AZURE_DEVOPS_EXT_PAT" "${PYTHON[@]}" -c '
import base64
import os

credential = base64.b64encode(
    (":" + os.environ["AZURE_DEVOPS_EXT_PAT"]).encode()
).decode()
print(f"Basic {credential}")
'
    return
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
  token=$(az "${token_args[@]}")
  printf 'Bearer %s\n' "$token"
}

ado_request() {
  local method="$1"
  local url="$2"
  local input_file="${3:-}"
  local auth_header
  auth_header=$(get_ado_auth_header)
  ADO_AUTH_HEADER="$auth_header" "${PYTHON[@]}" - "$method" "$url" "$input_file" <<'PY'
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
  if [[ ! -t 0 ]]; then
    echo "ERROR: The current Microsoft Entra tenant cannot access this Azure DevOps organization." >&2
    echo "Set ADO_TENANT to the Entra tenant ID/domain connected to the Azure DevOps organization." >&2
    echo "This can differ from the tenant associated with your Azure subscription." >&2
    echo "For a personal Microsoft account, set ADO_AUTH_METHOD=pat and AZURE_DEVOPS_EXT_PAT." >&2
    exit 1
  fi
  echo "The current Azure CLI tenant cannot access this Azure DevOps organization."
  echo "Enter the Entra tenant connected to the Azure DevOps organization, not necessarily your Azure subscription tenant."
  echo "To find it:"
  echo "  1. Open $ado_entra_settings_url (this link takes you there directly)."
  echo "  2. Or, open $ado_organization, click Organization settings in the lower-left corner,"
  echo "     then click Microsoft Entra in the left menu."
  echo "  3. Copy the Directory (tenant) ID."
  echo "  4. If only the directory name is shown, open that directory in the Microsoft Entra admin center,"
  echo "     then select Overview and copy Tenant ID."
  echo "If Microsoft Entra ID is unavailable, ask the Azure DevOps organization owner or enter 'pat'."
  echo "If the organization is not connected to Entra ID, use PAT authentication."
  auth_choice="$ado_tenant"
  while [[ -z "$auth_choice" ]]; do
    read -r -p "Azure DevOps-connected Entra tenant ID/domain, or 'pat': " auth_choice
  done
  case "${auth_choice,,}" in
    pat|msa|consumers)
      configure_pat_auth
      ;;
    *)
      ado_tenant="$auth_choice"
      echo "Opening browser sign-in for the specified Entra tenant..."
      echo "In the browser account picker, select 'Use another account' and enter the full email address."
      echo "No Azure subscription is required; this sign-in is only for Azure DevOps."
      if ! AZURE_CORE_LOGIN_EXPERIENCE_V2=off \
        az login \
        --tenant "$ado_tenant" \
        --allow-no-subscriptions \
        >/dev/null; then
        echo "Browser sign-in was blocked by Conditional Access or canceled."
        echo "Falling back to Azure DevOps PAT authentication."
        configure_pat_auth
      fi
      ;;
  esac
  if ! ado_request GET "$pipelines_url" > "$state_dir/pipelines.json"; then
    echo "ERROR: The signed-in identity still cannot access Azure DevOps organization '$ado_organization' project '$ado_project'." >&2
    exit 1
  fi
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
  echo "ERROR: Active Azure DevOps variables file is missing: $VARIABLES_FILE" >&2
  exit 1
fi
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: Active JSON configuration file is missing: $CONFIG_FILE" >&2
  exit 1
fi
cp "$VARIABLES_FILE" "$state_dir/variables.yaml"
cp "$CONFIG_FILE" "$state_dir/variables.json"
cp "$VARIABLES_FILE" "$backup_dir/variables.yaml"
cp "$CONFIG_FILE" "$backup_dir/variables.json"

resume_after_bootstrap=false
if [[ "${1:-}" == "--resume-after-bootstrap" ]]; then
  resume_after_bootstrap=true
fi
stash_created=false
submodule_stash_created=false
if [[ "$resume_after_bootstrap" == "false" ]]; then
  if [[ -d "$SUBMODULE_PATH/.git" || -f "$SUBMODULE_PATH/.git" ]] &&
     [[ -n "$(git -C "$SUBMODULE_PATH" status --porcelain)" ]]; then
    git -C "$SUBMODULE_PATH" stash push \
      --include-untracked \
      --message "Before AI Factory submodule update $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      >/dev/null
    submodule_stash_created=true
    echo "Existing submodule work was protected in: $(git -C "$SUBMODULE_PATH" stash list -1 --format='%gd %s')"
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    stash_message="Before AI Factory template update $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git stash push --include-untracked --message "$stash_message" >/dev/null
    stash_created=true
    echo "Existing work was protected in: $(git stash list -1 --format='%gd %s')"
  fi

  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
  git submodule update --init --recursive --remote
  git submodule foreach "git checkout '$SUBMODULE_BRANCH' && git pull --ff-only origin '$SUBMODULE_BRANCH'"

  printf 'a\n' | bash "$SUBMODULE_PATH/00-start.sh"
  bash "01-aif-copy-aifactory-templates.sh"
  bash "03-ADO-YAML-bootstrap-files-no-var-overwrite.sh"
fi

if [[ ! -f "$VARIABLES_TEMPLATE_FILE" ]]; then
  echo "ERROR: Azure DevOps variables template was not generated: $VARIABLES_TEMPLATE_FILE" >&2
  exit 1
fi
if [[ ! -f "$CONFIG_TEMPLATE_FILE" ]]; then
  echo "ERROR: JSON configuration template was not generated: $CONFIG_TEMPLATE_FILE" >&2
  exit 1
fi

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

legacy = [key for key in active if key not in used]
if legacy:
    result.extend(["", "  # Legacy values preserved from the previous variables.yaml"])
    result.extend(active_lines[key] for key in legacy)

output_path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY

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

def merge(template_value, active_value):
    if isinstance(template_value, dict) and isinstance(active_value, dict):
        merged = OrderedDict()
        for key, value in template_value.items():
            merged[key] = merge(value, active_value[key]) if key in active_value else value
        for key, value in active_value.items():
            if key not in merged:
                merged[key] = value
        return merged
    return active_value

output_path.write_text(json.dumps(merge(template, active), indent=2) + "\n", encoding="utf-8")
PY

rm -f "$VARIABLES_TEMPLATE_FILE" "$CONFIG_TEMPLATE_FILE"

"${PYTHON[@]}" - "$state_dir/preview-request.json" "$BRANCH" "$CONFIG_FILE" "$RUNNER_SELECTION" "$PIPELINE_YAML_PATH" <<'PY'
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
    },
    "stagesToSkip": [
        "Stage_GenAI_Project",
        "Prod_GenAI_Project",
    ],
    "yamlOverride": Path(sys.argv[5]).read_text(encoding="utf-8-sig"),
}
Path(sys.argv[1]).write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
PY

echo "Validating the Azure DevOps pipeline before commit and push..."
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
echo "Azure DevOps pipeline validation succeeded."

cp "$state_dir/ADO-update-aifactory-and-run-project.sh" "$REPO_ROOT/ADO-update-aifactory-and-run-project.sh"
chmod +x "$REPO_ROOT/ADO-update-aifactory-and-run-project.sh"

git add -A
if ! git diff --cached --quiet; then
  git commit \
    -m "Update AI Factory templates and Azure DevOps pipeline" \
    -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
  git push origin "$BRANCH"
else
  echo "No tracked template changes required a commit."
fi

"${PYTHON[@]}" - "$state_dir/run-request.json" "$BRANCH" "$CONFIG_FILE" "$RUNNER_SELECTION" <<'PY'
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
run_id="${run_details[0]}"
run_url="${run_details[1]:-}"

echo "Watching Azure DevOps run $run_id..."
if [[ -n "$run_url" ]]; then
  echo "$run_url"
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
  run_status="${run_state[0]}"
  run_result="${run_state[1]:-}"
  if [[ "$run_status" == "completed" ]]; then
    break
  fi
  sleep 15
done

if [[ "$run_result" != "succeeded" ]]; then
  echo "ERROR: Azure DevOps run $run_id completed with result: ${run_result:-unknown}" >&2
  exit 1
fi

if [[ "$stash_created" == "true" ]]; then
  echo "Pre-existing work remains protected in $(git stash list -1 --format='%gd')."
  echo "Review generated changes before restoring that stash to avoid overwriting the update."
fi
if [[ "$submodule_stash_created" == "true" ]]; then
  echo "Pre-existing submodule work remains protected in $(git -C "$SUBMODULE_PATH" stash list -1 --format='%gd')."
fi
echo "Azure DevOps run $run_id succeeded."
echo "Configuration backups are stored outside the repository at $backup_dir."
