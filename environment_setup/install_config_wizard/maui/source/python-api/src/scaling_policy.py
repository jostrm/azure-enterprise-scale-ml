"""Draft-only scaling profiles and IPv4 address-budget guidance."""

import copy
import ipaddress
import re
from itertools import combinations


SCALING_MODE_KEY = "scaling-mode"
DEFAULT_SCALING_MODE = "shared-subscriptions"
COMMON_PREFIXES = (26, 26, 26, 26)
PROJECT_PREFIXES = (23, 23, 24, 25, 26, 26, 26, 27)
SCREENSHOT_PROJECT_PREFIXES = PROJECT_PREFIXES[:-1]


def address_budget(prefixes):
    return sum(1 << (32 - prefix) for prefix in prefixes)


def smallest_ipv4_prefix(addresses):
    """Round an address budget up to a power of two, never individual subnets."""
    if not isinstance(addresses, int) or isinstance(addresses, bool) or not 0 < addresses <= 2**32:
        raise ValueError("IPv4 address budget must be between 1 and 4294967296")
    return 32 - (addresses - 1).bit_length()


def project_capacity(cidr_prefix, common_prefixes=COMMON_PREFIXES, project_prefixes=PROJECT_PREFIXES):
    """An address-budget upper bound; alignment and occupied gaps can reduce it."""
    return max(0, ((1 << (32 - cidr_prefix)) - address_budget(common_prefixes))
               // address_budget(project_prefixes))


_SHARED_NETWORK = {
    "common_vnet_cidr": "172.16.XX.0/18",
    "dev_cidr_range": "0",
    "test_cidr_range": "64",
    "prod_cidr_range": "128",
    "common_subnet_cidr": "172.16.XX.0/26",
    "common_subnet_scoring_cidr": "172.16.XX.64/26",
    "common_pbi_subnet_cidr": "172.16.XX.128/26",
    "common_bastion_subnet_cidr": "172.16.XX.192/26",
}
_OWN_NETWORK = {
    **_SHARED_NETWORK,
    "common_vnet_cidr": "172.16.XX.0/20",
    "dev_cidr_range": "0",
    "test_cidr_range": "16",
    "prod_cidr_range": "32",
}
_LEGACY_TEMPLATE_NETWORK = {
    **_SHARED_NETWORK,
    "common_vnet_cidr": "172.16.0.0/16",
    "dev_cidr_range": "61",
    "test_cidr_range": "62",
    "prod_cidr_range": "63",
}
_LEGACY_SHARED_NETWORK = {
    **_SHARED_NETWORK,
    "common_vnet_cidr": "172.16.0.0/18",
    "dev_cidr_range": "15",
    "test_cidr_range": "20",
    "prod_cidr_range": "25",
}
# Recognized only for an explicit preset application or changed mode selection.
SCALING_NETWORK_PROFILES = [
    _OWN_NETWORK, _SHARED_NETWORK, _LEGACY_TEMPLATE_NETWORK, _LEGACY_SHARED_NETWORK,
    {**_LEGACY_SHARED_NETWORK, "dev_cidr_range": "0", "test_cidr_range": "0", "prod_cidr_range": "0"},
]
SCALING_NETWORK_KEYS = tuple(_SHARED_NETWORK)
COMMON_SUBNET_KEYS = tuple(key for key in _SHARED_NETWORK if key.endswith("cidr") and key != "common_vnet_cidr")
ENVIRONMENT_RANGE_KEYS = ("dev_cidr_range", "test_cidr_range", "prod_cidr_range")
ENVIRONMENT_LABELS = ("Dev", "Stage", "Prod")
NETWORK_REPAIR_GUIDANCE = (
    "Apply network defaults to explicitly replace addressing with non-overlapping "
    "XX /18 (0/64/128) or /20 (0/16/32) networks. Consecutive 61/62/63 works for /24, "
    "not /18 or /16. Imported values are unchanged."
)
_NETWORK_WARNING = (
    "New-network draft defaults only; no Azure network is resized. Existing spread-out "
    "subnets cannot be shrunk to /20. Imported/custom addresses are preserved unless "
    "you explicitly apply network defaults."
)
SCALING_MODES = {
    "own-subscriptions": {
        "label": "A) Own subscriptions per project",
        "cidr_prefix": 20,
        "description": "Separate subscriptions per project; aligned /20 networks for Dev, Stage and Prod.",
        "capacity_description": (
            "Four common /26s (256 addresses) + one full project (1632) = 1888; "
            "double the total budget to 3776, rounded up to /20 (4096 addresses). "
            "The earlier profile without webapp /27 uses 1856, doubled to 3712: also /20. "
            "The current aligned, append-only allocator fits one full project in this /20, "
            "not two; doubled address-budget headroom does not guarantee a second full profile. "
            + _NETWORK_WARNING
        ),
        "network_defaults": _OWN_NETWORK,
        "address_count": 4096,
        "common_address_count": address_budget(COMMON_PREFIXES),
        "project_address_count": address_budget(PROJECT_PREFIXES),
        "doubled_address_budget": 2 * (address_budget(COMMON_PREFIXES) + address_budget(PROJECT_PREFIXES)),
        "current_allocator_full_project_capacity": 1,
    },
    "shared-subscriptions": {
        "label": "B) Common subscriptions for up to 8 projects",
        "cidr_prefix": 18,
        "description": "Each environment/subscription has its own non-overlapping, network-aligned VNet.",
        "capacity_description": (
            "Each /18 preset fits approximately 7 full allocator profiles, not a guarantee of 8. "
            "Actual capacity depends on the current draft and deployed subnets; address ranges permit peering, "
            "but actual peering is not verified."
        ),
        "network_defaults": _SHARED_NETWORK,
        "address_count": 16384,
        "common_address_count": address_budget(COMMON_PREFIXES),
        "project_address_count": address_budget(PROJECT_PREFIXES),
        "address_budget_project_capacity": project_capacity(18),
        "current_allocator_full_project_capacity_by_environment": {"dev": 7, "stage": 7, "prod": 7},
        "ten_project_minimum_prefix": smallest_ipv4_prefix(
            address_budget(COMMON_PREFIXES) + 10 * address_budget(PROJECT_PREFIXES)),
    },
}


def vnet_format_help():
    examples = []
    for label, mode in (("Shared", "shared-subscriptions"), ("Own", "own-subscriptions")):
        network = SCALING_MODES[mode]["network_defaults"]
        examples.append({
            "mode": label,
            "template": network["common_vnet_cidr"],
            "ranges": " / ".join(network[key] for key in ENVIRONMENT_RANGE_KEYS),
        })
    return {
        "examples": examples,
        "notes": [
            "Currently supported end-to-end: IPv4 templates with XX in the third octet. "
            "XX is replaced by dev_cidr_range, test_cidr_range or prod_cidr_range. "
            "Every resolved VNet must be network-aligned and must not overlap the other environments.",
            "The CIDR mask, not the address's historical class, determines alignment. "
            "For 172.16.XX.0/18 use steps of 64; for /20 use steps of 16. "
            "For 172.16.XX.0/16 the third octet must be 0, so this template cannot create three distinct /16 VNets. "
            "Consecutive 61 / 62 / 63 works with /24, which is too small for the full project subnet layout.",
            "10.XX.0.0/18 with XX=61 becomes 10.61.0.0/18: valid private IPv4, "
            "but second-octet placeholders are NOT yet supported by the wizard and pipeline preflight. "
            "The same placement can support distinct /16 networks once that feature is implemented.",
            "Private IPv4 ranges include 10.0.0.0/8 and 172.16.0.0/12 (172.16 through 172.31). "
            "172 does not have to begin with 172.16, but 172.61 is outside private space. "
            "VNet and subnet templates must use a consistent address plan; peering also needs routing configuration.",
        ],
    }


def require_scaling_mode(mode):
    if not isinstance(mode, str) or mode not in SCALING_MODES:
        raise ValueError("scaling-mode must be own-subscriptions or shared-subscriptions")
    return mode


def apply_scaling_mode(state, mode, apply_defaults=False):
    """Apply a user choice atomically, auto-switching only untouched known profiles."""
    require_scaling_mode(mode)
    previous_mode = state.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE)
    untouched = any(all(key in state and state[key] == value for key, value in profile.items())
                    for profile in SCALING_NETWORK_PROFILES)
    changes = {SCALING_MODE_KEY: mode}
    if apply_defaults or (mode != previous_mode and untouched):
        changes.update(copy.deepcopy(SCALING_MODES[mode]["network_defaults"]))
    state.update(changes)
    return state


def environment_octet(state, range_key):
    cidr_range = state.get(range_key)
    if (not isinstance(cidr_range, str) or not re.fullmatch(r"[0-9]{1,3}", cidr_range)
            or not 0 <= int(cidr_range) <= 255):
        raise ValueError(f"{range_key} must be an IPv4 third octet (0-255)")
    return cidr_range


def resolve_network(state, key, octet):
    template = state.get(key)
    if not isinstance(template, str) or not re.fullmatch(
        r"[0-9]{1,3}\.[0-9]{1,3}\.(?:XX|[0-9]{1,3})\.[0-9]{1,3}/[0-9]{1,2}", template
    ):
        raise ValueError(f"{key} must be an explicit IPv4 CIDR or use XX only as its third octet.")
    resolved = template.replace("XX", octet)
    try:
        return ipaddress.IPv4Network(resolved, strict=True)
    except ValueError:
        raise ValueError(f"{key} ({resolved}) is invalid or not network-aligned.") from None


def resolved_common_networks(state, range_key):
    """Resolve the existing XX convention without masking misaligned addresses."""
    octet = environment_octet(state, range_key)
    return resolve_network(state, "common_vnet_cidr", octet), {
        key: resolve_network(state, key, octet) for key in COMMON_SUBNET_KEYS
    }


def network_validation_issues(state):
    """Validate address intent for all three environments, independently of capacity."""
    issues = []
    vnets = []
    for label, range_key in zip(ENVIRONMENT_LABELS, ENVIRONMENT_RANGE_KEYS):
        try:
            octet = environment_octet(state, range_key)
            vnet = resolve_network(state, "common_vnet_cidr", octet)
        except ValueError as error:
            issues.append({"field": range_key, "code": "invalid_scaling_network",
                           "message": f"Cannot peer: {label}: {error} {NETWORK_REPAIR_GUIDANCE}"})
            continue
        vnets.append((label, vnet))
        subnets = {}
        for key in COMMON_SUBNET_KEYS:
            try:
                subnet = resolve_network(state, key, octet)
            except ValueError as error:
                issues.append({"field": key, "code": "invalid_scaling_network",
                               "message": f"Cannot peer: {label}: {error}"})
                continue
            subnets[key] = subnet
            if not subnet.subnet_of(vnet):
                issues.append({"field": key, "code": "subnet_outside_vnet",
                               "message": f"Cannot peer: {label}: {key} ({subnet}) is outside {vnet}."})
        for (left_key, left), (right_key, right) in combinations(subnets.items(), 2):
            if left.overlaps(right):
                issues.append({"field": right_key, "code": "subnet_overlap",
                               "message": f"Cannot peer: {label}: {left_key} ({left}) overlaps "
                                          f"{right_key} ({right}) in {vnet}."})
    for (left_label, left), (right_label, right) in combinations(vnets, 2):
        if left.overlaps(right):
            fixed = (" A fixed common_vnet_cidr ignores environment ranges for the VNet; "
                     "XX in common subnets alone does not create distinct VNets."
                     if "XX" not in state["common_vnet_cidr"] else "")
            issues.append({"field": "common_vnet_cidr", "code": "vnet_overlap",
                           "message": f"Cannot peer: {left_label} ({left}) overlaps {right_label} "
                                      f"({right}).{fixed} {NETWORK_REPAIR_GUIDANCE}"})
    return issues


def scaling_validation_issues(state):
    issues = []
    try:
        require_scaling_mode(state.get(SCALING_MODE_KEY, DEFAULT_SCALING_MODE))
    except ValueError as error:
        issues.append({"field": SCALING_MODE_KEY, "code": "invalid_scaling_mode", "message": str(error)})
    # Partial legacy state updates are normalized by their existing callers.
    # Never invent network defaults here; complete imports are always checked.
    if all(key in state for key in SCALING_NETWORK_KEYS):
        issues.extend(network_validation_issues(state))
    return issues


def require_scaling_configuration(state):
    issues = scaling_validation_issues(state)
    if issues:
        raise ValueError("; ".join(issue["message"] for issue in issues))
