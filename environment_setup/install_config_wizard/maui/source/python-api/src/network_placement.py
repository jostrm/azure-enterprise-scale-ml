"""Pure, draft-only placement preview for the append-only IPv4 allocator."""

import ipaddress

try:
    from .scaling_policy import (
        COMMON_SUBNET_KEYS, ENVIRONMENT_RANGE_KEYS, PROJECT_PREFIXES,
        SCALING_MODE_KEY, SCALING_MODES, SCALING_NETWORK_KEYS,
        ENVIRONMENT_LABELS, environment_octet, resolved_common_networks, network_validation_issues,
    )
except ImportError:
    from scaling_policy import (
        COMMON_SUBNET_KEYS, ENVIRONMENT_RANGE_KEYS, PROJECT_PREFIXES,
        SCALING_MODE_KEY, SCALING_MODES, SCALING_NETWORK_KEYS,
        ENVIRONMENT_LABELS, environment_octet, resolved_common_networks, network_validation_issues,
    )


PLACEMENT_KEYS = (SCALING_MODE_KEY, *SCALING_NETWORK_KEYS)
PEERING_GUIDANCE = (
    "Address ranges permit peering; actual Azure peering is not verified."
)
DRAFT_WARNING = (
    "Draft only: existing Azure networks are unchanged; this is not a migration."
)
ESTIMATE_ASSUMPTIONS = (
    "Estimate assumes only the four draft common subnets, then largest-first, aligned "
    "append-only placement after their highest end; gaps are not reused. "
    "Full project: 2x /23 + /24 + /25 + 3x /26 + /27 (1632 addresses). "
    "Not live inventory; other deployed subnets may reduce capacity."
)


def _capacity_supported(vnet, subnets):
    return 16 <= vnet.prefixlen <= 23 and all(subnet.prefixlen <= 29 for subnet in subnets.values())


def _highest_end(subnets):
    return max(int(subnet.broadcast_address) for subnet in subnets.values())


def _align_up(address, size):
    return ((address + size - 1) // size) * size


def estimate_full_projects(vnet, subnets):
    """Mathematical append estimate; callers must validate the supported range."""
    if not _capacity_supported(vnet, subnets):
        return None
    sizes = sorted((1 << (32 - prefix) for prefix in PROJECT_PREFIXES), reverse=True)
    first_start = _align_up(_highest_end(subnets) + 1, sizes[0])
    cursor = first_start
    for size in sizes:
        cursor = _align_up(cursor, size) + size
    end_exclusive = int(vnet.broadcast_address) + 1
    if cursor > end_exclusive:
        return 0
    # The 1632-address profile repeats at a 2048-address aligned stride.
    stride = _align_up(cursor - first_start, sizes[0])
    return 1 + (end_exclusive - cursor) // stride


def _environment(label, range_key, octet, vnet, subnets):
    common_start = min(int(subnet.network_address) for subnet in subnets.values())
    return {
        "environment": label.lower(),
        "range_key": range_key,
        "start_octet": octet,
        "vnet_cidr": str(vnet),
        "common_subnets": {key: str(subnet) for key, subnet in subnets.items()},
        "common_range": f"{ipaddress.IPv4Address(common_start)}-{ipaddress.IPv4Address(_highest_end(subnets))}",
        "estimated_full_projects": estimate_full_projects(vnet, subnets),
    }


def preview_network_placement(state):
    """Analyze raw network fields only, without defaults, persistence or Azure calls."""
    result = {
        "guidance": "",
        "is_peerable": False,
        "can_optimize": False,
        "optimization_changes": {},
        "optimization_description": "",
        "environments": [],
    }
    mode = state.get(SCALING_MODE_KEY)
    if not isinstance(mode, str) or mode not in SCALING_MODES:
        reason = "scaling-mode is missing or unsupported."
        result["guidance"] = f"Cannot peer: {reason} Capacity unknown; optimization unavailable. {DRAFT_WARNING}"
        result["optimization_description"] = result["guidance"]
        return result

    issues = network_validation_issues(state)
    if issues:
        result["guidance"] = (
            " ".join(issue["message"] for issue in issues)
            + " Capacity unknown; optimization unavailable. " + DRAFT_WARNING
        )
        result["optimization_description"] = result["guidance"]
        return result
    result["is_peerable"] = True
    resolved = []
    for label, range_key in zip(ENVIRONMENT_LABELS, ENVIRONMENT_RANGE_KEYS):
        octet = environment_octet(state, range_key)
        vnet, subnets = resolved_common_networks(state, range_key)
        resolved.append((label, range_key, octet, vnet, subnets))

    lines = []
    for label, range_key, octet, vnet, subnets in resolved:
        environment = _environment(label, range_key, octet, vnet, subnets)
        result["environments"].append(environment)
        lines.append(
            f"{label}: VNet {vnet}; common range {environment['common_range']} "
            f"(XX={octet}); estimated full projects: "
            f"{environment['estimated_full_projects'] if environment['estimated_full_projects'] is not None else 'unknown'}."
        )
    result["guidance"] = "\n".join(lines + [
        ESTIMATE_ASSUMPTIONS, PEERING_GUIDANCE, DRAFT_WARNING,
    ])
    if any(not _capacity_supported(vnet, subnets) for _, _, _, vnet, subnets in resolved):
        result["optimization_description"] = (
            "Full project capacity unknown; optimization unavailable outside supported VNet sizes /16 "
            "through /23 (at most 65536 addresses; allocator cannot cross a /16 boundary), or with "
            "common subnet masks narrower than /29. A /24 cannot fit the largest project subnet /23. "
            + PEERING_GUIDANCE
        )
        result["guidance"] += "\n" + result["optimization_description"]
        return result
    if any("XX" not in state[key] for key in COMMON_SUBNET_KEYS):
        result["optimization_description"] = (
            "Optimization unavailable: all four common subnet templates must use XX; "
            "fixed common CIDRs cannot be moved by the environment start ranges. " + DRAFT_WARNING
        )
        result["guidance"] += "\n" + result["optimization_description"]
        return result

    changes = {}
    descriptions = []
    for label, range_key, octet, vnet, subnets in resolved:
        best_octet, best_subnets = octet, subnets
        for candidate in range(256):
            try:
                candidate_state = {**state, **changes, range_key: str(candidate)}
                candidate_vnet, candidate_subnets = resolved_common_networks(candidate_state, range_key)
            except ValueError:
                continue
            if (candidate_vnet == vnet and _highest_end(candidate_subnets) < _highest_end(best_subnets)
                    and not network_validation_issues(candidate_state)):
                best_octet, best_subnets = str(candidate), candidate_subnets
        if best_octet != octet:
            changes[range_key] = best_octet
            optimized = _environment(label, range_key, best_octet, vnet, best_subnets)
            descriptions.append(
                f"{label}: {range_key} {octet} -> {best_octet}; VNet stays {vnet}; "
                f"common range becomes {optimized['common_range']}; "
                f"estimated full projects: {optimized['estimated_full_projects']}."
            )
    # Validate the combined plan, never merely independent candidate environments.
    if network_validation_issues({**state, **changes}):
        changes, descriptions = {}, []
    result["can_optimize"] = bool(changes)
    result["optimization_changes"] = changes
    result["optimization_description"] = "\n".join(
        (descriptions or ["Already optimal for non-overlapping VNets: earliest common placement inside each original VNet."])
        + [
            "Only the listed environment start ranges change. VNet CIDRs/masks and subnet templates stay unchanged.",
            ESTIMATE_ASSUMPTIONS, PEERING_GUIDANCE, DRAFT_WARNING,
        ]
    )
    return result
