#!/usr/bin/env python3
"""Validate selected Azure Managed Redis settings without changing saved configuration."""
from __future__ import annotations

import argparse
import os
import sys


DEFAULTS = {
    "enableRedisManaged": False,
    "skuRedisManagedDev": "Balanced_B1",
    "skuRedisManagedStageProd": "Balanced_B5",
    "highAvailabilityRedisManaged": "Enabled",
    "evictionPolicyRedisManaged": "NoEviction",
    "clusteringPolicyRedisManaged": "OSSCluster",
}
ALIASES = dict(zip(DEFAULTS, (
    "ENABLE_REDIS_MANAGED", "SKU_REDIS_MANAGED_DEV", "SKU_REDIS_MANAGED_STAGEPROD",
    "HIGH_AVAILABILITY_REDIS_MANAGED", "EVICTION_POLICY_REDIS_MANAGED",
    "CLUSTERING_POLICY_REDIS_MANAGED",
)))
SKUS = ("Balanced_B0", "Balanced_B1", "Balanced_B5", "Balanced_B10")
OPTIONS = {
    "skuRedisManagedDev": SKUS,
    "skuRedisManagedStageProd": SKUS,
    "highAvailabilityRedisManaged": ("Enabled", "Disabled"),
    "evictionPolicyRedisManaged": (
        "AllKeysLFU", "AllKeysLRU", "AllKeysRandom", "NoEviction",
        "VolatileLFU", "VolatileLRU", "VolatileRandom", "VolatileTTL",
    ),
    "clusteringPolicyRedisManaged": ("OSSCluster", "EnterpriseCluster", "NoCluster"),
}


def selected_values(values):
    return {key: values.get(key, values.get(key.upper(), values.get(ALIASES[key], default)))
            for key, default in DEFAULTS.items()}


def validate(values, environment=None, cloud=None):
    """Validate both SKU choices when no environment is selected."""
    selected = selected_values(values)
    enabled = selected["enableRedisManaged"]
    if str(enabled).lower() not in ("true", "false"):
        raise ValueError("enableRedisManaged must be true or false.")
    if str(enabled).lower() == "false":
        return
    if cloud is not None and cloud != "AzureCloud":
        raise ValueError(
            "RedisManaged supports only commercial Azure (AzureCloud) in this accelerator. "
            "Disable enableRedisManaged until service availability and DNS suffixes are verified."
        )
    if environment not in (None, "dev", "stage", "test", "prod"):
        raise ValueError("RedisManaged environment must be dev, stage, test or prod.")
    unused = "skuRedisManagedStageProd" if environment == "dev" else "skuRedisManagedDev"
    for key, options in OPTIONS.items():
        if environment is not None and key == unused:
            continue
        if selected[key] not in options:
            raise ValueError(f"{key} must be one of: {', '.join(options)}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=("dev", "stage", "test", "prod"))
    parser.add_argument("--cloud", help="Verified az cloud show --query name -o tsv result.")
    parser.add_argument("--azure-devops", action="store_true",
                        help="Publish effective/defaulted task variables for older YAML configurations.")
    args = parser.parse_args()
    try:
        validate(os.environ, args.environment, args.cloud)
    except ValueError as error:
        print(f"RedisManaged configuration error: {error}", file=sys.stderr)
        return 1
    if args.azure_devops:
        for key, value in selected_values(os.environ).items():
            text = str(value).lower() if key == "enableRedisManaged" else str(value)
            escaped = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"##vso[task.setvariable variable={key}]{escaped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
