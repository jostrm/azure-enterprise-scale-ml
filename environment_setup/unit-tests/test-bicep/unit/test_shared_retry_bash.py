"""Offline contract: the one shared Bash retry helper (scripts/modules/aif-retry.sh).

A deployment step that hits a transient Azure error (throttling, a 5xx, a timeout, another operation in progress,
an identity that has not replicated yet, a name that does not resolve yet) used to fail the job and cost a whole
run attempt. `aif_retry` runs the command again for those errors only: bounded attempts, exponential backoff with
jitter, the command's own exit code, and a final message with the last error and the attempt count.

The helper generalizes the loop that GHA step 69b already has (test_foundry_account_update_retry.py) and the
classification of `az_capture` in scripts/preflight.sh.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "environment_setup/aifactory/bicep/scripts/modules/aif-retry.sh"

TRANSIENT = {
    "throttled-429": 'ERROR: (TooManyRequests) Too many requests. Please retry after 17 seconds.',
    "status-429": "ERROR: Operation returned an invalid status code 'Too Many Requests' (429)",
    "subscription-throttled": '{"code": "SubscriptionRequestsThrottled", "message": "Number of requests exceeded"}',
    "internal-server-error": 'ERROR: {"code": "InternalServerError", "message": "Encountered internal server error."}',
    "service-unavailable": "ERROR: (ServiceUnavailable) The service is temporarily unavailable. Status code: 503",
    "bad-gateway": "ERROR: 502 Server Error: Bad Gateway for url: https://management.azure.com/",
    "gateway-timeout": 'ERROR: {"code": "GatewayTimeout", "message": "The gateway did not receive a response"}',
    "request-timeout": "ERROR: The operation timed out while waiting for a response.",
    "another-operation": ('ERROR: {"code": "AnotherOperationInProgress", "message": "Another operation on this or '
                          'dependent resource is in progress."}'),
    "request-conflict": ("ERROR: {\"code\": \"RequestConflict\", \"message\": \"Another operation is in progress on "
                         "the resource '/subscriptions/x/providers/Microsoft.CognitiveServices/accounts/a'.\"}"),
    "principal-not-found": ('ERROR: {"code": "PrincipalNotFound", "message": "Principal 0f0f does not exist in the '
                            'directory 1a1a. Check that you have the correct principal ID."}'),
    "retryable-error": '{"code": "RetryableError", "message": "A retryable error occurred."}',
    "dns-not-yet": "ERROR: <urllib3.connection.HTTPSConnection>: Failed to establish a new connection: "
                   "[Errno -3] Temporary failure in name resolution",
    "dns-curl": "curl: (6) Could not resolve host: kv-prj001.vault.azure.net",
    "connection-reset": "ERROR: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))",
}
NOT_TRANSIENT = {
    "invalid-template": 'ERROR: {"code": "InvalidTemplateDeployment", "message": "The template deployment failed."}',
    "authorization": 'ERROR: (AuthorizationFailed) The client does not have authorization to perform action',
    # Numbers that look like HTTP status codes but are quantities.
    "quota-with-500": ('ERROR: {"code": "InsufficientQuota", "message": "This operation require 500 new capacity '
                       'in quota Tokens Per Minute, which is bigger than the current available capacity 429."}'),
    "name-with-503": "ERROR: (ResourceNotFound) The Resource 'Microsoft.Storage/storageAccounts/sa503502' was not found.",
    "soft-deleted": 'ERROR: {"code": "FlagMustBeSetForRestore", "message": "An existing resource with ID x has been soft-deleted."}',
    "bicep-error": "ERROR: main.bicep(12,7) : Error BCP035: The specified object is missing required properties.",
    # A resource that is merely called "throttle" (the FinOps logic app) is not throttling.
    "throttle-in-a-name": ('ERROR: {"code": "InvalidTemplate", "message": "Deployment template validation failed '
                           "for resource 'logic-aimodel-throttle-dev'.\"}"),
    "status-with-more-digits": "ERROR: The script ended with status: 5021 (see the log).",
}

# Runs `aif_retry` on a fake command. $OUTCOMES holds one word per call: ok, or a key of the error tables.
# Every call and every sleep is logged; sleeps return at once (a simulated clock).
HARNESS = r"""
calls="$WORK/calls"; : > "$calls"
sleep() { echo "sleep $*" >> "$calls"; }
fake_az() {
  echo "call $*" >> "$calls"
  n=$(grep -c '^call ' "$calls")
  outcome=$(echo "$OUTCOMES" | cut -d' ' -f"$n")
  if [ "${outcome:-ok}" = ok ]; then echo "stdout of call $n"; return 0; fi
  echo "partial stdout of call $n"
  cat "$WORK/errors/$outcome" >&2
  return "${FAIL_CODE:-1}"
}
source "$HELPER"
"""


def bash_executable() -> str | None:
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


def run(tmp_path: Path, outcomes: str, command: str = 'aif_retry --label "63-cognitive-services" -- fake_az deployment sub create',
        environment: dict[str, str] | None = None, strict_shell: bool = True):
    bash = bash_executable()
    if not bash:
        pytest.skip("bash is required (Git Bash on Windows)")
    errors = tmp_path / "errors"
    errors.mkdir(exist_ok=True)
    for name, text in {**TRANSIENT, **NOT_TRANSIENT}.items():
        (errors / name).write_text(text + "\n", encoding="utf-8")
    # GitHub runs `shell: bash` as bash --noprofile --norc -eo pipefail; Azure DevOps runs plain bash.
    arguments = [bash, "--noprofile", "--norc", *(["-eo", "pipefail"] if strict_shell else []), "-s"]
    result = subprocess.run(
        arguments, input=(HARNESS + command + "\n").encode("utf-8"), capture_output=True, check=False, timeout=60,
        env={key: value for key, value in os.environ.items() if not key.startswith(("AIF_RETRY", "GITHUB_", "TF_BUILD"))}
        | {"WORK": tmp_path.as_posix(), "HELPER": HELPER.as_posix(), "OUTCOMES": outcomes} | (environment or {}))
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    attempts = [line for line in calls if line.startswith("call ")]
    sleeps = [int(line.split()[1]) for line in calls if line.startswith("sleep ")]
    return result.returncode, result.stdout.decode(), result.stderr.decode(), attempts, sleeps


def test_success_runs_once_and_passes_stdout_through(tmp_path):
    code, out, err, attempts, sleeps = run(tmp_path, "ok")
    assert (code, len(attempts), sleeps) == (0, 1, [])
    assert out == "stdout of call 1\n" and err == ""


@pytest.mark.parametrize("error", sorted(TRANSIENT))
def test_a_transient_error_is_retried(tmp_path, error):
    code, out, err, attempts, sleeps = run(tmp_path, f"{error} ok")
    assert code == 0, err
    assert len(attempts) == 2 and len(sleeps) == 1
    assert TRANSIENT[error] in err, "the failed attempt's error stays visible"
    assert "attempt 1 of 3" in err and "63-cognitive-services" in err
    assert out.endswith("stdout of call 2\n")


@pytest.mark.parametrize("error", sorted(NOT_TRANSIENT))
def test_any_other_error_is_returned_at_once(tmp_path, error):
    code, _, err, attempts, sleeps = run(tmp_path, f"{error} ok", environment={"FAIL_CODE": "7"})
    assert (code, len(attempts), sleeps) == (7, 1, []), err
    assert NOT_TRANSIENT[error] in err
    assert "not a transient error" in err and "attempt 1" in err


def test_attempts_are_bounded_and_the_final_failure_names_the_last_error_and_the_count(tmp_path):
    code, _, err, attempts, sleeps = run(tmp_path, " ".join(["throttled-429"] * 3 + ["another-operation"] * 20),
                                         command='aif_retry --attempts 4 --label "61-foundation" -- fake_az deployment sub create',
                                         environment={"FAIL_CODE": "3"})
    assert (code, len(attempts), len(sleeps)) == (3, 4, 3), err
    last_line = [line for line in err.splitlines() if line.strip()][-1]
    assert "61-foundation" in last_line and "4 attempts" in last_line
    assert "AnotherOperationInProgress" in last_line, "the final message carries the last error"


def test_backoff_is_exponential_with_jitter_and_capped(tmp_path):
    command = 'aif_retry --attempts 7 --base-delay 10 --max-delay 120 -- fake_az x'
    seen = set()
    for round_number in range(6):
        work = tmp_path / str(round_number)
        work.mkdir()
        _, _, _, attempts, sleeps = run(work, " ".join(["gateway-timeout"] * 7), command=command)
        assert len(attempts) == 7 and len(sleeps) == 6
        for index, seconds in enumerate(sleeps):
            ceiling = min(120, 10 * 2 ** index)
            assert ceiling // 2 <= seconds <= ceiling, (index, seconds, sleeps)
        seen.add(tuple(sleeps))
    assert len(seen) > 1, "the waits must differ between runs (jitter)"


def test_the_environment_can_turn_retries_off_and_tune_them(tmp_path):
    code, _, _, attempts, sleeps = run(tmp_path, "throttled-429 ok", environment={"AIF_RETRY_ATTEMPTS": "1"})
    assert code != 0 and len(attempts) == 1 and sleeps == []


def test_a_call_site_can_name_more_transient_errors(tmp_path):
    (tmp_path / "errors").mkdir()
    command = "aif_retry --also 'ForbiddenByFirewall|Public network access is disabled' -- fake_az keyvault secret set"
    NOT_TRANSIENT_FIREWALL = "ERROR: (Forbidden) Public network access is disabled and request is not from a trusted service."
    (tmp_path / "errors" / "firewall").write_text(NOT_TRANSIENT_FIREWALL + "\n", encoding="utf-8")
    code, _, err, attempts, _ = run(tmp_path, "firewall ok", command=command)
    assert code == 0 and len(attempts) == 2, err
    work = tmp_path / "default"
    work.mkdir()
    (work / "errors").mkdir()
    (work / "errors" / "firewall").write_text(NOT_TRANSIENT_FIREWALL + "\n", encoding="utf-8")
    code, _, _, attempts, _ = run(work, "firewall ok", command="aif_retry -- fake_az keyvault secret set")
    assert code != 0 and len(attempts) == 1, "a firewall refusal is only transient where the call site says so"


def test_arguments_reach_the_command_unchanged(tmp_path):
    command = ("aif_retry -- fake_az deployment sub create --parameters tags='{\"Owner\": \"a b\", \"x\": \"1&2\"}' "
               "--parameters IPwhiteList=\"10.0.0.1, 10.0.0.2\" --name 'has  two spaces'")
    code, _, err, attempts, _ = run(tmp_path, "ok", command=command)
    assert code == 0, err
    assert attempts == ['call deployment sub create --parameters tags={"Owner": "a b", "x": "1&2"} '
                        '--parameters IPwhiteList=10.0.0.1, 10.0.0.2 --name has  two spaces']


def test_captured_output_is_the_commands_stdout(tmp_path):
    command = 'result=$(aif_retry -- fake_az deployment show); echo "captured=[$result]"'
    code, out, _, _, _ = run(tmp_path, "ok", command=command)
    assert code == 0 and out == "captured=[stdout of call 1]\n"


@pytest.mark.parametrize("marker_first", [True, False])
def test_a_long_error_output_is_still_classified(tmp_path, marker_first):
    """`grep -q` stops reading at the first match; under pipefail that must not turn a match into a miss."""
    noise = "\n".join(f"WARNING: line {number} of a long deployment log" for number in range(20000))
    marker = TRANSIENT["another-operation"]
    (tmp_path / "errors").mkdir()
    (tmp_path / "errors" / "long").write_text((marker + "\n" + noise if marker_first else noise + "\n" + marker) + "\n",
                                              encoding="utf-8")
    code, _, err, attempts, _ = run(tmp_path, "long ok")
    assert code == 0 and len(attempts) == 2, err[-400:]


@pytest.mark.parametrize("shell_options", ["set -euo pipefail", "set -e", ":"])
def test_a_failure_that_prints_nothing_keeps_its_exit_code(tmp_path, shell_options):
    """A command can fail without a word on stderr. The step must end with that command's exit code, also under
    `set -euo pipefail`, where an empty error file once ended the script with 1 (found by test_rbac_common_rg.py)."""
    (tmp_path / "errors").mkdir()
    (tmp_path / "errors" / "silent").write_text("", encoding="utf-8")
    code, _, err, attempts, sleeps = run(
        tmp_path, "silent ok", command=f"{shell_options}; aif_retry_deployment --label quiet -- fake_az deployment sub create",
        environment={"FAIL_CODE": "9"}, strict_shell=False)
    assert (code, len(attempts), sleeps) == (9, 1, []), err
    assert "'quiet' failed on attempt 1 (exit 9)" in err


def test_it_works_with_nounset(tmp_path):
    code, _, err, attempts, _ = run(tmp_path, "throttled-429 ok",
                                    command="set -u; aif_retry -- fake_az deployment sub create")
    assert code == 0 and len(attempts) == 2, err


def test_it_works_without_errexit_too(tmp_path):
    code, _, err, attempts, _ = run(tmp_path, "dns-not-yet ok", strict_shell=False)
    assert code == 0 and len(attempts) == 2, err


@pytest.mark.parametrize("command", ["aif_retry fake_az x", "aif_retry --attempts 0 -- fake_az x",
                                     "aif_retry --base-delay ten -- fake_az x", "aif_retry --"])
def test_wrong_use_is_refused_before_anything_runs(tmp_path, command):
    code, _, err, attempts, _ = run(tmp_path, "ok", command=command)
    assert code == 2 and attempts == [] and "usage: aif_retry" in err


def test_notices_use_the_log_commands_of_the_host(tmp_path):
    _, out, err, _, _ = run(tmp_path, "throttled-429 ok", environment={"GITHUB_ACTIONS": "true"})
    assert "::warning::" in out + err
    work = tmp_path / "ado"
    work.mkdir()
    _, out, err, _, _ = run(work, "throttled-429 ok", environment={"TF_BUILD": "True"})
    assert "##[warning]" in out + err


def test_deployments_get_one_policy_in_one_place(tmp_path):
    """`aif_retry_deployment` is `aif_retry` with the patience a subscription deployment needs: 4 attempts, 30 s base."""
    command = 'aif_retry_deployment --label "61-foundation" -- fake_az deployment sub create'
    code, _, err, attempts, sleeps = run(tmp_path, " ".join(["another-operation"] * 10), command=command)
    assert code != 0 and len(attempts) == 4, err
    assert [15 <= sleeps[0] <= 30, 30 <= sleeps[1] <= 60, 60 <= sleeps[2] <= 120] == [True, True, True], sleeps
    assert "61-foundation" in err and "4 attempts" in err
    work = tmp_path / "tuned"
    work.mkdir()
    code, _, _, attempts, sleeps = run(work, " ".join(["another-operation"] * 10), command=command,
                                       environment={"AIF_DEPLOY_RETRY_ATTEMPTS": "2", "AIF_DEPLOY_RETRY_BASE_DELAY": "4"})
    assert len(attempts) == 2 and len(sleeps) == 1 and 2 <= sleeps[0] <= 4


def test_sourcing_the_helper_runs_nothing_and_defines_its_functions(tmp_path):
    command = "declare -F | cut -d' ' -f3 | grep '^aif_' | sort | tr '\\n' ' '"
    code, out, err, attempts, sleeps = run(tmp_path, "ok", command=command)
    assert code == 0 and attempts == [] and sleeps == [], err
    assert out.split() == ["aif_is_transient_error", "aif_retry", "aif_retry_delay", "aif_retry_deployment"]
