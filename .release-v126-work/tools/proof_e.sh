#!/usr/bin/env bash
# Proof e: a scratch consumer repository with purple as the submodule `azure-enterprise-scale-ml` runs
# 01-start-v125-and-above.sh the way unit/test_azurefactory_starter.py does, offline.
# Usage: proof_e.sh <git url or path of purple> <branch> <work dir> [--depth-1]
set -uo pipefail
source_repo="${1:?purple git url or path}"
branch="${2:?branch}"
work="${3:?work dir}"
depth_flag="${4:-}"
ci=(/home/user/tools/cienv.sh /home/user/venvs/main/bin --)
fail() { echo "PROOF E FAILED: $*"; exit 1; }

rm -rf "$work"; mkdir -p "$work/consumer"; cd "$work/consumer" || exit 1
git init --quiet . || fail "git init"
depth=(); [[ "$depth_flag" == "--depth-1" ]] && depth=(--depth 1)
start=$(date +%s.%N)
git -c protocol.file.allow=always submodule --quiet add -b "$branch" "${depth[@]}" "$source_repo" azure-enterprise-scale-ml \
  >"$work/submodule-add.log" 2>&1 || { cat "$work/submodule-add.log"; fail "git submodule add"; }
end=$(date +%s.%N)
printf 'submodule add: seconds=%.1f commit=%s git_mb=%s tree_mb=%s files=%s\n' "$(echo "$end - $start" | bc)" \
  "$(git -C azure-enterprise-scale-ml rev-parse --short HEAD)" \
  "$(du -sm .git/modules/azure-enterprise-scale-ml | cut -f1)" \
  "$(du -sm --exclude=.git azure-enterprise-scale-ml | cut -f1)" \
  "$(git -C azure-enterprise-scale-ml ls-files | wc -l)"
git -c user.name=proof -c user.email=proof@example.invalid -c commit.gpgsign=false commit --quiet -m "Add the accelerator submodule" || fail "commit"

# 1. First run: installs both provider wrappers, the launcher libraries and the real CLI; initializes the register.
"${ci[@]}" bash azure-enterprise-scale-ml/01-start-v125-and-above.sh >"$work/start-1.out" 2>"$work/start-1.err" \
  || { cat "$work/start-1.err"; fail "first run exit code"; }
grep -q "Source commit:" "$work/start-1.out" || fail "no source commit line"
grep -q "payload SHA256:" "$work/start-1.out" || fail "no payload digest line"
for name in ADO-azurefactory.sh GHA-azurefactory.sh azurefactory.sh AIFactory-lifecycle.sh azurefactory/register.json \
            lib/factory_lifecycle.py lib/layout_router.sh ui/terminal.sh .azurefactory-tools/azurefactory/cli.py \
            .azurefactory-tools/persona-engine/personas/pipeline.py; do
  [[ -f "$name" ]] || fail "missing installed file $name"
done
for name in aifactory aifactory-templates 01-aif-copy-aifactory-templates.sh; do
  [[ ! -e "$name" ]] || fail "unexpected legacy path $name"
done

# 2. The installed launcher answers offline.
"${ci[@]}" bash ./azurefactory.sh api instructions >"$work/instructions.json" 2>"$work/instructions.err" \
  || { cat "$work/instructions.err"; fail "azurefactory.sh api instructions"; }
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["desktop_required"] is False' "$work/instructions.json" \
  || fail "instructions payload"

# 3. Second run: idempotent, refreshes nothing.
"${ci[@]}" bash azure-enterprise-scale-ml/01-start-v125-and-above.sh >"$work/start-2.out" 2>"$work/start-2.err" \
  || { cat "$work/start-2.err"; fail "second run exit code"; }
grep -q "Refreshed 0 files" "$work/start-2.out" || fail "second run was not a no-op"
echo "installed files: $(git status --porcelain --untracked-files=all | wc -l)"
echo "PROOF E PASSED: $(grep 'Source commit:' "$work/start-1.out") | $(grep 'payload SHA256:' "$work/start-1.out")"
