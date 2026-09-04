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

cd "$REPO_ROOT"

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
if ! az extension show --name azure-devops >/dev/null 2>&1; then
  echo "ERROR: The Azure CLI azure-devops extension is required." >&2
  echo "Install it with: az extension add --name azure-devops" >&2
  exit 1
fi

devops_defaults=$(az devops configure --list 2>/dev/null || true)
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

ado_organization="${ADO_ORGANIZATION:-$(read_devops_default organization)}"
ado_project="${ADO_PROJECT:-$(read_devops_default project)}"
devops_defaults_prompted=false
if [[ -z "$ado_organization" || -z "$ado_project" ]]; then
  if [[ ! -t 0 ]]; then
    echo "ERROR: Azure DevOps organization and project are required in non-interactive mode." >&2
    echo "Set ADO_ORGANIZATION and ADO_PROJECT, or configure Azure CLI defaults:" >&2
    echo "  az devops configure --defaults organization=https://dev.azure.com/<org> project=<project>" >&2
    exit 1
  fi
  echo "Azure DevOps settings are not configured. Enter them once; they will be saved as Azure CLI defaults."
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
  az devops configure \
    --defaults organization="$ado_organization" project="$ado_project" \
    >/dev/null
  echo "Saved Azure DevOps organization and project for future runs."
fi

state_dir="$HOME/.aifactory-update-state/ado-$$"
mkdir -p "$state_dir"
trap 'rm -rf -- "$state_dir"' EXIT
cp "$0" "$state_dir/ADO-update-aifactory-and-run-project.sh"
backup_dir="$HOME/.aifactory-backups/$(basename "$REPO_ROOT")/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"

az pipelines list \
  --organization "$ado_organization" \
  --project "$ado_project" \
  --output json > "$state_dir/pipelines.json"

pipeline_id=$("${PYTHON[@]}" - "$state_dir/pipelines.json" "$PIPELINE_YAML_PATH" "$PIPELINE_NAME" <<'PY'
import json
import sys
from pathlib import PurePosixPath

pipelines = json.loads(open(sys.argv[1], encoding="utf-8-sig").read())
target_path = str(PurePosixPath(sys.argv[2].replace("\\", "/"))).lstrip("/").lower()
target_name = sys.argv[3].lower()

path_matches = []
name_matches = []
for pipeline in pipelines:
    process = pipeline.get("process") or {}
    yaml_path = str(process.get("yamlFilename") or "").replace("\\", "/").lstrip("/").lower()
    if yaml_path == target_path:
        path_matches.append(pipeline)
    if str(pipeline.get("name") or "").lower() == target_name:
        name_matches.append(pipeline)

matches = path_matches or name_matches
if len(matches) != 1:
    reason = "not found" if not matches else "ambiguous"
    raise SystemExit(
        f"Azure DevOps pipeline is {reason}; expected YAML path {sys.argv[2]!r} "
        f"or pipeline name {sys.argv[3]!r}."
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

az devops invoke \
  --organization "$ado_organization" \
  --area pipelines \
  --resource runs \
  --route-parameters project="$ado_project" pipelineId="$pipeline_id" \
  --api-version "7.1" \
  --http-method POST \
  --in-file "$state_dir/run-request.json" \
  --output json > "$state_dir/run.json"

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
  az pipelines runs show \
    --organization "$ado_organization" \
    --project "$ado_project" \
    --id "$run_id" \
    --output json > "$state_dir/run-status.json"
  mapfile -t run_state < <("${PYTHON[@]}" - "$state_dir/run-status.json" <<'PY'
import json
import sys

run = json.loads(open(sys.argv[1], encoding="utf-8-sig").read())
print(run.get("status") or "")
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
