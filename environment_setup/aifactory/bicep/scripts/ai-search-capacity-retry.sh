#!/usr/bin/env bash
# Shared capacity candidate validation; retain the historical Search entry points.

aif_capacity_normalize() {
  local value="${1:-}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value,,}"
}

aif_capacity_retry_enabled() {
  case "$(aif_capacity_normalize "${1:-}")" in
    true|1|yes) return 0 ;;
    false|0|no) return 1 ;;
    *) printf 'Invalid %s value: %s (use true or false).\n' "${2:-capacity retry switch}" "${1:-}" >&2; return 2 ;;
  esac
}

aif_capacity_candidate_order() {
  local selected configured="${2:-}" retry="${3-false}" label="${4:-Azure AI Search}" candidate retry_status
  selected="$(aif_capacity_normalize "${1:-}")"
  local -a values=()
  [[ -n "$selected" && "$selected" =~ ^[a-z0-9_]+$ ]] || {
    printf 'The selected %s SKU must be a nonempty SKU name.\n' "$label" >&2
    return 2
  }
  if aif_capacity_retry_enabled "$retry"; then retry_status=0; else retry_status=$?; fi
  if [[ "$retry_status" -eq 1 ]]; then
    printf '%s\n' "$selected"
    return 0
  fi
  [[ "$retry_status" -eq 0 ]] || return 2
  # Split explicitly so a trailing comma remains an empty candidate.
  while [[ "$configured" == *,* ]]; do
    values+=("${configured%%,*}")
    configured="${configured#*,}"
  done
  values+=("$configured")
  (( ${#values[@]} >= 1 && ${#values[@]} <= 3 )) || {
    printf '%s retry candidates must contain one to three comma-separated SKUs.\n' "$label" >&2
    return 2
  }
  local -A seen=()
  local selected_found=false
  for candidate in "${values[@]}"; do
    candidate="$(aif_capacity_normalize "$candidate")"
    [[ -n "$candidate" && "$candidate" =~ ^[a-z0-9_]+$ ]] || {
      printf 'Invalid %s retry SKU: %s\n' "$label" "$candidate" >&2
      return 2
    }
    [[ -z "${seen[$candidate]:-}" ]] || {
      printf '%s retry candidates must not repeat SKU %s.\n' "$label" "$candidate" >&2
      return 2
    }
    seen[$candidate]=true
    [[ "$candidate" != "$selected" ]] || selected_found=true
  done
  [[ "$selected_found" == true ]] || {
    printf 'Selected %s SKU %s is not in its retry candidate array.\n' "$label" "$selected" >&2
    return 2
  }
  printf '%s\n' "$selected"
  for candidate in "${values[@]}"; do
    candidate="$(aif_capacity_normalize "$candidate")"
    [[ "$candidate" == "$selected" ]] || printf '%s\n' "$candidate"
  done
  return 0
}

aif_ai_search_retry_enabled() {
  aif_capacity_retry_enabled "${1:-}" aisearchRetryCapcityArray
}

aif_ai_search_candidate_order() {
  aif_capacity_candidate_order "${1:-}" "${2:-}" "${3-false}" "Azure AI Search"
}

aif_ai_search_is_capacity_failure() {
  grep -Eqi '(SkuNotAvailable|SkuNotAvailableForSubscription|InsufficientCapacity|CapacityUnavailable|capacity[[:space:]]+(is[[:space:]]+)?not[[:space:]]+available|insufficient[[:space:]]+capacity)' "$1"
}
