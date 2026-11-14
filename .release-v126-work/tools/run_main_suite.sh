#!/usr/bin/env bash
# Run the main offline IaC suite (prepare-cache, unit tiers all, syntax, bicep) on one worktree.
# Usage: run_main_suite.sh <worktree> <results-dir> [phases...]
set -uo pipefail
worktree="${1:?worktree}"
results="${2:?results dir}"
shift 2
phases=("$@")
[[ ${#phases[@]} -eq 0 ]] && phases=(prepare unit syntax bicep)

# prepare needs the network (through the sandbox proxy); every test phase runs in the clean CI-like environment.
export PATH="/home/user/tools/bicep:/home/user/tools/pwsh:/home/user/venvs/main/bin:$PATH"
export LIVE_AZURE=0 PYTHONUTF8=1
unset AIF_TEST_TIERS
python=/home/user/venvs/main/bin/python
ci=(/home/user/tools/cienv.sh /home/user/venvs/main/bin --)
tiers="${AIF_RUN_TIERS:-all}"
suite="$worktree/environment_setup/unit-tests/test-bicep"
mkdir -p "$results"

for phase in "${phases[@]}"; do
  start=$(date +%s.%N)
  echo "##### $phase start $(date -u +%H:%M:%S)" | tee -a "$results/timeline.log"
  case "$phase" in
    prepare)
      "$python" "$suite/run_bicep_matrix.py" --prepare-cache --bicep /home/user/tools/bicep/bicep \
        --report "$results/bicep-dependencies.json" >"$results/prepare.log" 2>&1
      code=$? ;;
    unit)
      timeout 2700 "${ci[@]}" "$python" "$suite/run_ci.py" --phase unit --tiers "$tiers" --require-ci-tools \
        --bicep /home/user/tools/bicep/bicep --results-dir "$results" >"$results/unit.log" 2>&1
      code=$? ;;
    syntax)
      timeout 2700 "${ci[@]}" "$python" "$suite/run_ci.py" --phase syntax \
        --results-dir "$results" >"$results/syntax.log" 2>&1
      code=$? ;;
    bicep)
      timeout 2700 "${ci[@]}" "$python" "$suite/run_ci.py" --phase bicep \
        --bicep /home/user/tools/bicep/bicep --results-dir "$results" >"$results/bicep.log" 2>&1
      code=$? ;;
  esac
  end=$(date +%s.%N)
  printf '##### %s exit=%s seconds=%.1f\n' "$phase" "$code" "$(echo "$end - $start" | bc)" | tee -a "$results/timeline.log"
done
echo "##### ALL DONE $(date -u +%H:%M:%S)" | tee -a "$results/timeline.log"
