#!/usr/bin/env bash

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
readonly REPO_ROOT="${AIFACTORY_REPO_ROOT:-C:/code/code_py_25/002_demo/azure-enterprise-scale-byor-110}"
readonly SUBMODULE_PATH="azure-enterprise-scale-ml"
readonly SUBMODULE_BRANCH="release/v1.24"
readonly WORKFLOW_FILE="infra-project.yml"
readonly CONFIG_FILE="aifactory/variables.json"
readonly CONFIG_TEMPLATE_FILE="aifactory/variables-template.json"
readonly ENVIRONMENT="dev"
readonly RUNNER_LABEL="aifactory-admin-vm"

cd "$REPO_ROOT"

if [[ "${AIFACTORY_LAUNCHER_STABLE:-}" != "1" ]]; then
  state_dir="$HOME/.aifactory-update-state/gh-$$"
  stable_launcher="$state_dir/GH-update-aifactory-and-run-project.sh"
  mkdir -p "$state_dir"
  mkdir -p "$state_dir/ui"
  cp "$AIF_UI_LIBRARY" "$state_dir/ui/terminal.sh"
  cp "${BASH_SOURCE[0]}" "$stable_launcher"
  chmod +x "$stable_launcher"
  export AIFACTORY_LAUNCHER_STABLE=1
  export AIFACTORY_LAUNCHER_STATE_DIR="$state_dir"
  export AIFACTORY_REPO_ROOT="$REPO_ROOT"
  exec bash "$stable_launcher" "$@"
fi

state_dir="${AIFACTORY_LAUNCHER_STATE_DIR:?Stable launcher state directory is missing.}"
trap 'rm -rf -- "$state_dir"' EXIT
aif_banner "GITHUB / UPDATE + RUN" "Preserve configuration. Refresh templates. Deploy with intent."
aif_value "Repository" "$REPO_ROOT"
aif_value "Environment" "$ENVIRONMENT"
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

confirm_update_github_variables() {
  local choice="${AIFACTORY_UPDATE_GITHUB_VARIABLES:-}"
  while true; do
    if [[ -z "$choice" ]]; then
      printf '%s' "$(aif_prompt "Update GitHub variables and secrets from .env? [y/N]: ")" >&2
      if ! IFS= read -r choice; then
        return 1
      fi
    fi
    choice="${choice%$'\r'}"
    case "${choice,,}" in
      y|yes)
        return 0
        ;;
      ""|n|no)
        return 1
        ;;
      *)
        aif_warn "Please enter 'y' for Yes or 'n' for No. Press Enter for No." >&2
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
      aif_info "JSON override disabled; the workflow will use GitHub variables and secrets."
      break
      ;;
    *)
      aif_warn "Please enter 'y' for Yes or 'n' for No. Press Enter for No." >&2
      json_override_choice=""
      ;;
  esac
done

for command in git gh; do
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
aif_section "02 / GitHub connection"
gh auth status >/dev/null

backup_dir="$HOME/.aifactory-backups/$(basename "$REPO_ROOT")/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"

if [[ -f .env ]]; then
  cp .env "$state_dir/current.env"
fi
if [[ "$use_json_override" == "true" && -f "$CONFIG_FILE" ]]; then
  cp "$CONFIG_FILE" "$state_dir/variables.json"
fi
if [[ -f .env.bak ]]; then
  cp .env.bak "$backup_dir/.env.bak"
fi

resume_after_bootstrap=false
aif_section "03 / Protect local work and refresh templates"
if [[ "${1:-}" == "--resume-after-bootstrap" ]]; then
  resume_after_bootstrap=true
fi
stash_created=false
submodule_stash_created=false
if [[ "$resume_after_bootstrap" == "false" ]]; then
  if [[ -n "$(git status --porcelain)" ]]; then
    stash_message="Before AI Factory template update $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    git stash push --include-untracked --message "$stash_message" >/dev/null
    stash_created=true
    aif_success "Existing work was protected in: $(git stash list -1 --format='%gd %s')"
  fi

  if [[ -d "$SUBMODULE_PATH/.git" || -f "$SUBMODULE_PATH/.git" ]] &&
     [[ -n "$(git -C "$SUBMODULE_PATH" status --porcelain)" ]]; then
    git -C "$SUBMODULE_PATH" stash push \
      --include-untracked \
      --message "Before AI Factory submodule update $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      >/dev/null
    submodule_stash_created=true
    aif_success "Existing submodule work was protected in: $(git -C "$SUBMODULE_PATH" stash list -1 --format='%gd %s')"
  fi

  git checkout main
  git pull --ff-only origin main
  git submodule update --init --recursive --remote
  git submodule foreach "git checkout '$SUBMODULE_BRANCH' && git pull --ff-only origin '$SUBMODULE_BRANCH'"

  printf 'g\n' | bash "$SUBMODULE_PATH/00-start.sh"
  bash "01-aif-copy-aifactory-templates.sh"
  bash "03-GH-bootstrap-files-no-env-overwrite.sh"
fi

if [[ "$use_json_override" == "true" && -f "$state_dir/variables.json" ]]; then
  cp "$state_dir/variables.json" "$CONFIG_FILE"
fi

if [[ ! -f .env.template ]]; then
  aif_error ".env.template was not generated." >&2
  exit 1
fi
if [[ "$use_json_override" == "true" && ! -f "$state_dir/variables.json" ]]; then
  aif_error "Active JSON configuration file is missing: $CONFIG_FILE" >&2
  exit 1
fi
if [[ "$use_json_override" == "true" && ! -f "$CONFIG_TEMPLATE_FILE" ]]; then
  aif_error "JSON configuration template was not generated: $CONFIG_TEMPLATE_FILE" >&2
  exit 1
fi

aif_section "04 / Configuration changes"
"${PYTHON[@]}" - \
  "$state_dir/current.env" \
  ".env.template" \
  "$state_dir/variables.json" \
  "$CONFIG_TEMPLATE_FILE" \
  "$use_json_override" <<'PY' | aif_stream
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

active_env_path = Path(sys.argv[1])
template_env_path = Path(sys.argv[2])
active_json_path = Path(sys.argv[3])
template_json_path = Path(sys.argv[4])
use_json = sys.argv[5] == "true"
removed_json_keys = {"useAdminVMBuildAgent"}
assignment = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
aliases = {
    "DEV_NETWORK_ENV": ("NETWORK_ENV_DEV",),
    "STAGE_NETWORK_ENV": ("NETWORK_ENV_STAGE",),
    "PROD_NETWORK_ENV": ("NETWORK_ENV_PROD",),
    "DISABLE_CONTRIBUTOR_ACCESS_FORUSERS": ("DISABLE_CONTRIBUTOR_ACCESS_FOR_USERS",),
    "DISABLE_RBAC_ADMIN_ON_RG_FORUSERS": ("DISABLE_RBAC_ADMIN_ON_RG_FOR_USERS",),
}


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


def env_values(path):
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
        if key in removed_json_keys:
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


active_env = env_values(active_env_path)
template_env = env_values(template_env_path)
renamed_env = []
for template_key in template_env:
    if template_key in active_env:
        continue
    for alias in aliases.get(template_key, ()):
        if alias in active_env:
            renamed_env.append(alias)
            break
found = print_section(
    ".env",
    [(key, value) for key, value in template_env.items() if key not in active_env],
    renamed_env,
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

if [[ "$use_json_override" == "true" ]]; then
  "${PYTHON[@]}" - "$CONFIG_FILE" "$CONFIG_TEMPLATE_FILE" "$RUNNER_LABEL" "$state_dir/current.env" <<'PY'
import json
import re
import shlex
import sys
from collections import OrderedDict
from pathlib import Path

active_path = Path(sys.argv[1])
template_path = Path(sys.argv[2])
runner_label = sys.argv[3]
env_path = Path(sys.argv[4])

if not active_path.is_file():
    raise SystemExit(f"Active configuration file is missing: {active_path}")
if not template_path.is_file():
    raise SystemExit(f"Template configuration file is missing: {template_path}")

active = json.loads(active_path.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict)
template = json.loads(template_path.read_text(encoding="utf-8-sig"), object_pairs_hook=OrderedDict)
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

merged = merge(template, active)
github_defaults = {
    "GITHUB_USERNAME": "",
    "GITHUB_USE_SSH": "false",
    "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
    "GITHUB_NEW_REPO": "",
    "GITHUB_NEW_REPO_VISIBILITY": "public",
}
github_values = dict(github_defaults)
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        assignment = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=(.*)$", line)
        if assignment and assignment[1] in github_defaults:
            words = shlex.split(assignment[2], comments=True)
            if len(words) > 1:
                raise ValueError(f"Expected one value for {assignment[1]}")
            github_values[assignment[1]] = words[0] if words else ""
for section in ("dev", "stage_prod"):
    if section not in merged:
        continue
    # Only backfill missing bootstrap identity; explicit JSON values always win.
    for key, value in github_values.items():
        if key not in active.get(section, {}):
            merged[section][key] = value
merged.setdefault("_wizard", {})["orchestrator"] = "gha"
dev = merged.setdefault("dev", OrderedDict())
dev["useSelfHostedBuildAgent"] = "true"
dev["selfHostedRunnerLabel"] = runner_label
dev["disable_whitelisting_for_build_agents"] = "true"
active_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
PY
fi

if [[ -f "$state_dir/current.env" ]]; then
  cp "$state_dir/current.env" .env
fi

"${PYTHON[@]}" - ".env" ".env.template" "$RUNNER_LABEL" <<'PY'
import re
import sys
from pathlib import Path

current_path = Path(sys.argv[1])
template_path = Path(sys.argv[2])
runner_label = sys.argv[3]

assignment = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

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
            return text[:index].rstrip(), text[index - 1 :]
    return text.rstrip(), ""

def read_assignments(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = assignment.match(line)
        if match:
            values[match.group(2)] = split_value_comment(match.group(3))[0]
    return values

current = read_assignments(current_path)
aliases = {
    "DEV_NETWORK_ENV": ("NETWORK_ENV_DEV",),
    "STAGE_NETWORK_ENV": ("NETWORK_ENV_STAGE",),
    "PROD_NETWORK_ENV": ("NETWORK_ENV_PROD",),
    "DISABLE_CONTRIBUTOR_ACCESS_FORUSERS": ("DISABLE_CONTRIBUTOR_ACCESS_FOR_USERS",),
    "DISABLE_RBAC_ADMIN_ON_RG_FORUSERS": ("DISABLE_RBAC_ADMIN_ON_RG_FOR_USERS",),
}
overrides = {
    "USE_SELF_HOSTED_BUILD_AGENT": '"true"',
    "SELF_HOSTED_RUNNER_LABEL": f'"{runner_label}"',
    "DISABLE_WHITELISTING_FOR_BUILD_AGENTS": '"true"',
}

used = set()
result = []
for line in template_path.read_text(encoding="utf-8-sig").splitlines():
    match = assignment.match(line)
    if not match:
        result.append(line)
        continue
    prefix, key, remainder = match.groups()
    _, comment = split_value_comment(remainder)
    value = overrides.get(key)
    if value is None and key in current:
        value = current[key]
        used.add(key)
    if value is None:
        for alias in aliases.get(key, ()):
            if alias in current:
                value = current[alias]
                used.add(alias)
                break
    result.append(f"{prefix}{key}={value}{comment}" if value is not None else line)

legacy = [key for key in current if key not in used and key not in overrides]
if legacy:
    result.extend(["", "# Legacy values preserved from the previous .env"])
    result.extend(f"{key}={current[key]}" for key in legacy)

template_path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY

if [[ -f .env ]]; then
  cp .env "$backup_dir/.env"
  mv -f .env .env.bak
fi
mv -f .env.template .env
rm -f "$CONFIG_TEMPLATE_FILE"

aif_section "05 / Synchronize GitHub configuration"
if [[ "$use_json_override" == "true" ]]; then
  aif_info "JSON override supplies deployment variables; bulk .env synchronization is optional."
  aif_info "The JSON file will still be uploaded as one AIFACTORY_CONFIG_JSON secret. Existing authentication secrets must already be configured."
fi
if [[ "$use_json_override" != "true" ]] || confirm_update_github_variables; then
  printf 'd\n\n\nn\n' | bash "10-GH-create-or-update-github-variables.sh"
else
  aif_info "Skipped bulk GitHub variable/secret updates from .env. The workflow will use JSON override: $config_override_file"
fi

github_repo=$("${PYTHON[@]}" - <<'PY'
import re
from pathlib import Path

for line in Path(".env").read_text(encoding="utf-8-sig").splitlines():
    if not line.startswith("GITHUB_NEW_REPO="):
        continue
    value = line.split("=", 1)[1].split(" #", 1)[0].strip().strip("'\"")
    while value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        raise SystemExit(f"Invalid GITHUB_NEW_REPO value: {value!r}")
    print(value)
    break
else:
    raise SystemExit("GITHUB_NEW_REPO is missing from .env")
PY
)

if [[ "$use_json_override" == "true" ]]; then
  gh secret set AIFACTORY_CONFIG_JSON \
    --repo "$github_repo" \
    --env "$ENVIRONMENT" \
    < "$CONFIG_FILE"
fi

grep -q 'AIFACTORY_CONFIG_JSON' ".github/workflows/$WORKFLOW_FILE"
grep -q 'runner_selection' ".github/workflows/$WORKFLOW_FILE"

exclude_file="$(git rev-parse --git-path info/exclude)"
mkdir -p "$(dirname "$exclude_file")"
grep -qxF "/$CONFIG_FILE" "$exclude_file" 2>/dev/null || printf '/%s\n' "$CONFIG_FILE" >> "$exclude_file"

cp "$state_dir/GH-update-aifactory-and-run-project.sh" "$REPO_ROOT/GH-update-aifactory-and-run-project.sh"
chmod +x "$REPO_ROOT/GH-update-aifactory-and-run-project.sh"

aif_section "06 / Review and publish"
git add -A
git rm --cached --ignore-unmatch .env.bak >/dev/null
git restore --staged -- .env 2>/dev/null || true
git restore --staged -- "$CONFIG_FILE" 2>/dev/null || true
if ! git diff --cached --quiet; then
  if ! confirm_commit_and_continue; then
    git restore --staged -- .
    aif_warn "Commit declined. Changes remain in the working tree; no push or workflow run was started."
    exit 0
  fi
  git commit \
    -m "Update AI Factory templates and GitHub workflow" \
    -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
  git push origin main
else
  aif_info "No tracked template changes required a commit."
fi

dispatch_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
gh workflow run "$WORKFLOW_FILE" \
  --repo "$github_repo" \
  --ref main \
  --raw-field environment="$ENVIRONMENT" \
  --raw-field config_file="$config_override_file" \
  --raw-field runner_selection=self-hosted \
  --raw-field self_hosted_runner_label="$RUNNER_LABEL"

run_id=""
for _ in {1..30}; do
  run_id=$(gh run list \
    --repo "$github_repo" \
    --workflow "$WORKFLOW_FILE" \
    --branch main \
    --event workflow_dispatch \
    --limit 10 \
    --json databaseId,createdAt \
    --jq ".[] | select(.createdAt >= \"$dispatch_time\") | .databaseId" |
    head -n 1)
  [[ -n "$run_id" ]] && break
  sleep 2
done

if [[ -z "$run_id" ]]; then
  aif_error "Workflow was dispatched but its run ID could not be resolved." >&2
  exit 1
fi

aif_section "07 / Deployment"
aif_value "Run" "$run_id"
gh run watch "$run_id" --repo "$github_repo" --exit-status

if [[ "$stash_created" == "true" ]]; then
  aif_info "Pre-existing work remains protected in $(git stash list -1 --format='%gd')."
  aif_warn "Review generated changes before restoring that stash to avoid overwriting the update."
fi
if [[ "$submodule_stash_created" == "true" ]]; then
  aif_info "Pre-existing submodule work remains protected in $(git -C "$SUBMODULE_PATH" stash list -1 --format='%gd')."
fi
aif_value "Backups" "$backup_dir"
aif_complete "GitHub Actions run $run_id succeeded."
