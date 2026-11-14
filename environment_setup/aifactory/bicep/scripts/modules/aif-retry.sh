#!/usr/bin/env bash
# Shared retry helper for pipeline steps and operator scripts (Bash). Source it: it only defines functions.
#
#   source <path>/scripts/modules/aif-retry.sh
#   aif_retry [--attempts N] [--base-delay S] [--max-delay S] [--label TEXT] [--also REGEX]
#             [--before-retry FUNCTION] -- command [args...]
#   aif_retry_deployment [--label TEXT] -- az deployment sub create ...
#
# Runs the command. When it fails with a TRANSIENT Azure or network error, it waits and runs the command again:
# at most N attempts in total (default 3), exponential backoff with jitter (base 10 s, at most 300 s). Every other
# failure is returned at once with the command's own exit code, so a real error is never hidden or delayed.
#
#   * stdout passes through unchanged, so `result=$(aif_retry -- az ...)` still works.
#   * stderr of each attempt is shown when the attempt ends, and is what decides "transient".
#   * The final failure prints the last error and the attempt count.
#   * Safe under `bash -eo pipefail` (GitHub Actions) and in plain bash (Azure DevOps, Git Bash on Windows).
#
# Transient means: throttling (429), a 5xx, a timeout, a dropped connection, a name that does not resolve yet,
# "another operation is in progress", and an identity that has not replicated yet (PrincipalNotFound).
# A call site can name more with --also, for example a firewall rule that is still propagating, and can repair
# a known broken state before the next attempt with --before-retry (called with the error file and the command).
#
# Only wrap commands that are safe to run twice. `az deployment sub create` is: the templates are idempotent
# and a re-run with the same name is what an operator would do by hand.
#
# Tunables: AIF_RETRY_ATTEMPTS, AIF_RETRY_BASE_DELAY, AIF_RETRY_MAX_DELAY (AIF_RETRY_ATTEMPTS=1 turns retries off).
# The loop generalizes GHA step 69b (RequestConflict) and the classification of az_capture in preflight.sh.

# Codes and phrases, never bare numbers or word stems: "capacity 500" in a quota message is not an HTTP 500,
# and a resource that is called "...-throttle" is not throttling.
AIF_RETRY_TRANSIENT_PATTERN='AnotherOperationInProgress|another operation (on this or dependent resource )?is in progress'
AIF_RETRY_TRANSIENT_PATTERN+='|PrincipalNotFound|RetryableError|ServerBusy'
AIF_RETRY_TRANSIENT_PATTERN+='|TooManyRequests|too many requests|throttled|throttling'
AIF_RETRY_TRANSIENT_PATTERN+='|InternalServerError|internal server error|ServiceUnavailable|service unavailable'
AIF_RETRY_TRANSIENT_PATTERN+='|temporarily unavailable|BadGateway|bad gateway|GatewayTimeout|gateway.?time.?out'
AIF_RETRY_TRANSIENT_PATTERN+='|RequestTimeout|OperationTimedOut|timed out|time-?out (expired|reached)'
AIF_RETRY_TRANSIENT_PATTERN+='|status( code)?[:= ]+.?(429|50[0234])([^0-9]|$)|\((429|50[0234])\)|(429|50[0234]) (client|server) error'
AIF_RETRY_TRANSIENT_PATTERN+='|connection (reset|aborted|refused)|ConnectionResetError|RemoteDisconnected'
AIF_RETRY_TRANSIENT_PATTERN+='|remote end closed connection|max retries exceeded|EOF occurred in violation of protocol'
AIF_RETRY_TRANSIENT_PATTERN+='|could not resolve host|name or service not known|temporary failure in name resolution'
AIF_RETRY_TRANSIENT_PATTERN+='|getaddrinfo failed|NameResolutionError'

# aif_is_transient_error TEXT [EXTRA_REGEX]: status 0 when TEXT shows a transient error.
aif_is_transient_error() {
  local pattern="$AIF_RETRY_TRANSIENT_PATTERN"
  [ -z "${2:-}" ] || pattern+="|$2"
  # A here-string, not a pipe: `grep -q` stops at the first match, and under `set -o pipefail` the writer of a
  # pipe would then die of SIGPIPE on a long log and turn the match into a failure.
  grep -qiE -- "$pattern" <<< "${1:-}"
}

# aif_retry_delay ATTEMPT BASE MAX: seconds to wait after failed attempt ATTEMPT (1-based).
# Exponential (BASE, 2*BASE, 4*BASE ... at most MAX) with equal jitter: half fixed, half random,
# so runs that failed together do not all come back in the same second.
aif_retry_delay() {
  local attempt="$1" base="$2" max="$3" exponent delay half
  exponent=$(( attempt - 1 )); [ "$exponent" -le 20 ] || exponent=20
  delay=$(( base * (1 << exponent) ))
  [ "$delay" -le "$max" ] || delay="$max"
  half=$(( delay / 2 ))
  printf '%s' $(( half + RANDOM % (delay - half + 1) ))
}

aif_retry() {
  local attempts="${AIF_RETRY_ATTEMPTS:-3}" base="${AIF_RETRY_BASE_DELAY:-10}" max="${AIF_RETRY_MAX_DELAY:-300}"
  local label="" also="" before_retry="" usage error_file attempt=1 status delay last_error
  usage='usage: aif_retry [--attempts N] [--base-delay S] [--max-delay S] [--label TEXT] [--also REGEX] [--before-retry FUNCTION] -- command [args...]'
  while [ $# -gt 0 ]; do
    case "$1" in
      --attempts)   attempts="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --base-delay) base="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --max-delay)  max="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --label)      label="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --also)       also="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --before-retry) before_retry="${2:-}"; shift 2 || { echo "$usage" >&2; return 2; } ;;
      --)           shift; break ;;
      *)            echo "aif_retry: '--' must come before the command. $usage" >&2; return 2 ;;
    esac
  done
  if [ $# -eq 0 ] || ! [[ "$attempts" =~ ^[1-9][0-9]*$ && "$base" =~ ^[0-9]+$ && "$max" =~ ^[0-9]+$ ]]; then
    echo "aif_retry: a command, attempts of 1 or more, and whole seconds are required. $usage" >&2
    return 2
  fi
  [ -n "$label" ] || label="$1"
  error_file="$(mktemp 2>/dev/null || printf '%s' "${TMPDIR:-/tmp}/aif_retry.$$.$RANDOM")"

  while :; do
    # `if` keeps a failing command from ending the script under `set -e`; stdout is not touched.
    if "$@" 2>"$error_file"; then status=0; else status=$?; fi
    cat "$error_file" >&2
    if [ "$status" -eq 0 ]; then rm -f "$error_file"; return 0; fi

    # The last non-blank line. One awk, not `grep | tail`: grep ends with 1 on an empty file, and under
    # `set -eo pipefail` that would end the script here with 1 instead of the command's own exit code.
    last_error="$(awk 'NF { line = $0 } END { print substr(line, 1, 600) }' "$error_file")"
    if ! aif_is_transient_error "$(cat "$error_file")" "$also"; then
      rm -f "$error_file"
      echo "aif_retry: '$label' failed on attempt $attempt (exit $status): not a transient error, not retried." >&2
      return "$status"
    fi
    if [ "$attempt" -ge "$attempts" ]; then
      rm -f "$error_file"
      _aif_retry_notice error "aif_retry: '$label' failed after $attempt attempts (exit $status); the error stayed transient. Last error: $last_error"
      return "$status"
    fi
    delay="$(aif_retry_delay "$attempt" "$base" "$max")"
    _aif_retry_notice warning "aif_retry: '$label' attempt $attempt of $attempts hit a transient error; next attempt in ${delay}s. Error: $last_error"
    # Self-heal hook: repair what is known to be broken before trying again. It never decides the outcome.
    [ -z "$before_retry" ] || "$before_retry" "$error_file" "$@" || true
    sleep "$delay"   # failure backoff, not an idle wait
    attempt=$(( attempt + 1 ))
  done
}

# aif_retry_deployment [--label TEXT] -- az deployment sub create ...
# The one retry policy for subscription deployments in the pipelines: 4 attempts, waits of 15-30 s, 30-60 s and
# 60-120 s. A deployment that fails on a transient error is run again with the same name and inputs, which is
# what the operator would do; any other error fails the step at once, as before.
#
# Self-heal: a cancelled or timed-out run can leave its deployment running in Azure. The next run uses the same
# deployment name and is refused with DeploymentActive. That is waited out (the earlier deployment's own state is
# polled every 10 s, for at most 20 minutes) and the deployment is then run again.
# Tunables: AIF_DEPLOY_RETRY_ATTEMPTS, AIF_DEPLOY_RETRY_BASE_DELAY, AIF_DEPLOY_RETRY_MAX_DELAY,
#           AIF_DEPLOY_ACTIVE_WAIT_SECONDS.
aif_retry_deployment() {
  aif_retry --attempts "${AIF_DEPLOY_RETRY_ATTEMPTS:-4}" --base-delay "${AIF_DEPLOY_RETRY_BASE_DELAY:-30}" \
    --max-delay "${AIF_DEPLOY_RETRY_MAX_DELAY:-300}" --also 'DeploymentActive' \
    --before-retry _aif_wait_for_active_deployment "$@"
}

# Called before a retry with the error file and the command. When the error is DeploymentActive, waits until the
# deployment of that name is no longer running. A lookup that fails ends the wait: the retry decides.
_aif_wait_for_active_deployment() {
  local error_file="$1" name="" subscription="" previous="" argument state waited=0
  local budget="${AIF_DEPLOY_ACTIVE_WAIT_SECONDS:-1200}"
  shift
  grep -q 'DeploymentActive' "$error_file" 2>/dev/null || return 0
  for argument in "$@"; do
    case "$previous" in
      --name|-n) name="$argument" ;;
      --subscription) subscription="$argument" ;;
    esac
    previous="$argument"
  done
  [ -n "$name" ] || return 0
  echo "aif_retry: deployment '$name' from an earlier run is still active; waiting up to ${budget}s for it to end." >&2
  while [ "$waited" -lt "$budget" ]; do
    if [ -n "$subscription" ]; then
      state="$(az deployment sub show --name "$name" --subscription "$subscription" --query properties.provisioningState -o tsv 2>/dev/null || true)"
    else
      state="$(az deployment sub show --name "$name" --query properties.provisioningState -o tsv 2>/dev/null || true)"
    fi
    state="${state//$'\r'/}"
    case "$state" in
      Running|Accepted|Canceling|Creating|Updating|Deleting) ;;
      "") echo "aif_retry: could not read the state of deployment '$name'; trying the deployment again." >&2; return 0 ;;
      *)  echo "aif_retry: deployment '$name' is now $state." >&2; return 0 ;;
    esac
    sleep 10
    waited=$(( waited + 10 ))
  done
  echo "aif_retry: deployment '$name' was still active after ${budget}s." >&2
}

# One line on stderr, marked the way the host shows warnings and errors in its run summary.
_aif_retry_notice() {
  local level="$1" text="$2"
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    echo "::${level}::${text}" >&2
  elif [ -n "${TF_BUILD:-}" ]; then
    echo "##[${level}]${text}" >&2
  else
    echo "$text" >&2
  fi
}
