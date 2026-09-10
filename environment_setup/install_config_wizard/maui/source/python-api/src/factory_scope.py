"""Read the current factory's Azure scope without combining historical snapshots."""

import json
from pathlib import Path


def current_factory_scope(folder, factory_id=None, scale_set_id=None):
    root = Path(folder)
    if (root / "config-wizard" / "catalog.json").exists():
        from src.factory_catalog import catalog_scope
        return catalog_scope(folder, factory_id, scale_set_id)
    if factory_id is not None or scale_set_id is not None:
        raise ValueError("Explicit catalog scope cannot be applied to a legacy root.")
    full_path = root / "config-wizard" / "factory_state.json"
    variables_path = root / "variables.json"
    if full_path.is_file():
        document = json.loads(full_path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("Current factory state must be a JSON object.")
        dev = stage = document
    elif variables_path.is_file():
        document = json.loads(variables_path.read_text(encoding="utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("Current factory variables must be a JSON object.")
        dev, stage = document.get("dev", {}), document.get("stage_prod", {})
        if not isinstance(dev, dict) or not isinstance(stage, dict):
            raise ValueError("Current factory dev and stage_prod variables must be objects.")
    else:
        from src import wizard
        candidate, _ = wizard._startup_import_candidate(str(root), {})
        values = {}
        if candidate:
            if Path(candidate).name == ".env":
                wizard._import_env_to_state(candidate, values)
            elif Path(candidate).suffix in (".yaml", ".yml"):
                wizard._import_yaml_to_state(candidate, values)
        dev = stage = values

    def read(section, key):
        value = str(section.get(key) or "").strip()
        return "" if "<todo>" in value.lower() else value

    dev_sub = read(dev, "dev_sub_id")
    subscriptions = {
        "dev": dev_sub,
        "stage": read(stage, "test_sub_id") or read(dev, "test_sub_id") or dev_sub,
        "prod": read(stage, "prod_sub_id") or read(dev, "prod_sub_id") or dev_sub,
    }
    tenants = {
        "dev": read(dev, "tenantId"),
        "stage": read(stage, "tenantId") or read(dev, "tenantId"),
        "prod": read(stage, "tenantId") or read(dev, "tenantId"),
    }
    subscriptions = {env: sub for env, sub in subscriptions.items() if sub}
    subscription_tenants = {}
    for env, sub in subscriptions.items():
        tenant = tenants[env]
        if tenant:
            previous = subscription_tenants.setdefault(sub, tenant)
            if previous.casefold() != tenant.casefold():
                raise ValueError("The same subscription has conflicting tenant IDs in current factory variables.")
    monitoring_targets = []
    monitoring_regions = set()
    for env, sub in subscriptions.items():
        section = dev if env == "dev" else stage
        region = read(section, "admin_location") or read(dev, "admin_location")
        short = read(section, "admin_locationSuffix") or read(dev, "admin_locationSuffix")
        prefix = read(section, "admin_aifactoryPrefixRG") or read(dev, "admin_aifactoryPrefixRG")
        suffix = read(section, "admin_aifactorySuffixRG") or read(dev, "admin_aifactorySuffixRG")
        if region:
            monitoring_regions.add(region.casefold())
        if short:
            monitoring_targets.append({
                "environment": env,
                "subscription_id": sub,
                "region": region.casefold(),
                "location_suffix": short.casefold(),
                "prefix": prefix,
                "suffix": suffix,
                "project_suffix": read(section, "projectSuffix") or read(dev, "projectSuffix"),
            })
    return {
        "subscriptions": subscriptions,
        "subscription_ids": sorted(set(subscriptions.values())),
        "tenant_ids": sorted(set(tenants.values()) - {""}),
        "subscription_tenants": subscription_tenants,
        "monitoring_regions": sorted(monitoring_regions),
        "monitoring_targets": monitoring_targets,
    }
