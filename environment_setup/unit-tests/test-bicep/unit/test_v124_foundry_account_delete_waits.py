"""v1.24 delete-services-if-disabled.sh: the Foundry V2 account delete waits for its nested projects.

Live evidence (aif-157, byor-157 run 42751438602, 2026-11-10, main/release-v1.25 fixed in ee62d324): a Foundry
project DELETE answers 202 and the project can still be listed (and block the account) for minutes. The account
DELETE right after was refused with CannotDeleteResource. On v1.24 that refusal was only a warning, so the account
was silently left behind. The script now waits until the project list is empty and retries the account delete on
CannotDeleteResource, both bounded. Runs the real script with a fake `az` on PATH; no Azure calls.
"""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "delete-services-if-disabled.sh"

FAKE_AZ = textwrap.dedent('''\
    #!/usr/bin/env bash
    # Fake Azure CLI: logs every call; answers only the Foundry V2 calls, empty success otherwise.
    state="$FAKE_STATE"
    echo "$*" >> "$state/calls.log"
    count() { local n; n=$(cat "$state/$1" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$state/$1"; echo "$n"; }
    case "$*" in
      *"resource list"*"Microsoft.CognitiveServices/accounts"*) echo "aif2acct" ;;
      "account show"*) echo "00000000-0000-0000-0000-000000000000" ;;
      *"--method GET"*"/accounts/aif2acct/projects?"*)
        deleted=$(cat "$state/project_deleted" 2>/dev/null || echo 0)
        # Before its DELETE the project is listed; after it, it stays listed for $FAKE_LISTED_AFTER more reads.
        if [ "$deleted" = 0 ] || [ "$(count listed_after)" -le "$FAKE_LISTED_AFTER" ]; then echo "aif2acct/proj1"; fi ;;
      *"--method DELETE"*"/accounts/aif2acct/projects/proj1?"*) echo 1 > "$state/project_deleted" ;;
      *"--method GET"*"capabilityHosts"*) ;;
      "cognitiveservices account delete"*)
        n=$(count account_deletes)
        if [ "$n" -le "$FAKE_REFUSALS" ]; then
          echo "ERROR: (CannotDeleteResource) Cannot delete resource while nested resources exist." >&2; exit 1
        fi ;;
      *) ;;
    esac
    exit 0
    ''')


def run(tmp_path, *, listed_after, refusals):
    bash = shutil.which("bash")
    assert bash, "bash is required to run the v1.24 deletion script"
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    for name, body in (("az", FAKE_AZ), ("sleep", "#!/usr/bin/env bash\necho \"$1\" >> \"$FAKE_STATE/sleeps.log\"\n"),
                       ("curl", "#!/usr/bin/env bash\necho 404\n")):
        path = bin_dir / name
        path.write_text(body, encoding="utf-8", newline="\n")
        path.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""), "FAKE_STATE": str(state),
           "FAKE_LISTED_AFTER": str(listed_after), "FAKE_REFUSALS": str(refusals),
           "dev_test_prod_sub_id": "00000000-0000-0000-0000-000000000000", "projectNumber": "002",
           "envName": "dev", "locationSuffix": "sdc", "commonRGNamePrefix": "aif-", "projectPrefix": "esml-",
           "aifactorySuffixRG": "-001", "projectSuffix": "-rg", "enableDeleteForDisabledResources": "true",
           "enableAIFoundry": "false", "aiFoundryV2Exists": "true"}
    result = subprocess.run([bash, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=300,
                            encoding="utf-8", errors="replace")
    calls = (state / "calls.log").read_text(encoding="utf-8").splitlines()
    sleeps = (state / "sleeps.log").read_text().split() if (state / "sleeps.log").exists() else []
    return result, calls, sleeps


def test_account_delete_waits_for_a_project_still_listed_and_retries_the_nested_refusal(tmp_path):
    result, calls, sleeps = run(tmp_path, listed_after=3, refusals=2)
    output = result.stdout + result.stderr
    deletes = [call for call in calls if call.startswith("cognitiveservices account delete")]
    assert len(deletes) == 3, output[-3000:]
    assert "Deleted AI Foundry V2 (soft-deleted)" in output
    # The account delete is only tried once the project list was read empty after the project DELETE:
    # three reads still list it, the fourth is empty.
    first_delete = calls.index(deletes[0])
    project_delete = next(i for i, call in enumerate(calls) if "--method DELETE" in call and "/projects/proj1?" in call)
    reads = [call for call in calls[project_delete:first_delete] if "/accounts/aif2acct/projects?" in call]
    assert len(reads) == 4
    assert sleeps, "the waits must pause between reads"


def test_nested_refusal_retries_are_bounded_and_end_with_the_warning(tmp_path):
    result, calls, _ = run(tmp_path, listed_after=0, refusals=1000)
    output = result.stdout + result.stderr
    deletes = [call for call in calls if call.startswith("cognitiveservices account delete")]
    assert 10 <= len(deletes) <= 40, output[-3000:]
    assert "Could not delete AI Foundry V2" in output
