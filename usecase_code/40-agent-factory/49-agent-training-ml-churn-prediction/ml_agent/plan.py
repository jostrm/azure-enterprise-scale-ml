"""Offline plans and plan-bound approval for every live operation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .configuration import fingerprint, paths, read_json, write_json
from .usecases import AIR, CHURN, DATA_VERSION_PREFIX, OPERATIONS, expected_names, model_name, usecase

SCHEMA = "aif49.ml-agent-plan/v1"
PUBLICATIONS = "publications.json"


def published_versions(state: Path) -> list[str]:
    record = Path(state) / PUBLICATIONS
    if not record.is_file():
        return []
    versions = read_json(record).get("versions", [])
    if not isinstance(versions, list) or any(not isinstance(item, str) for item in versions):
        raise ValueError("Corrupt publication record")
    return versions


def record_publication(state: Path, version: str) -> None:
    versions = published_versions(state)
    if version not in versions:
        write_json(Path(state) / PUBLICATIONS, {"versions": [*versions, version]})


def next_data_version(state: Path, *, fresh: bool) -> str:
    numbers = []
    for version in published_versions(state):
        match = re.fullmatch(re.escape(DATA_VERSION_PREFIX) + r"(\d+)", version)
        if match:
            numbers.append(int(match.group(1)))
    if not numbers:
        return f"{DATA_VERSION_PREFIX}1"
    return f"{DATA_VERSION_PREFIX}{max(numbers) + 1 if fresh else max(numbers)}"


def _lake(config: dict, dataset: str, version: str, use_case: str) -> dict:
    from azure_esml.domain_layer.shared_lake import SharedLake

    lake = SharedLake(config["aifactory"], config["environment"], config["shared_lake"]["prefix"])
    project = f"{config['project_number']:03d}"
    return {
        "master": lake.master(dataset, version),
        "project_in": lake.project(project, dataset, version) + "/in",
        "use_case_root": lake.use_case(project, use_case),
    }


def build_plan(config: dict, *, now: datetime | None = None, fresh: bool = False) -> dict:
    """Describe every name, path, run and Azure write before anything is executed."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%y%m%d%H%M")
    location = paths(config)
    reviewed = read_json(config["reviewed_rollout"])
    air_binding = reviewed["scenarios"][AIR]
    churn_version = next_data_version(location.state, fresh=fresh)
    entries = {}
    for name, version, key in ((CHURN, churn_version, "m49"), (AIR, air_binding["data_version"], "m05")):
        item = usecase(name)
        settings = config["usecases"][name]
        entry = {
            "model_number": item["model_number"], "task": item["task"], "mode": item["mode"],
            "operation": item["operation"], "operations": list(OPERATIONS[name]),
            "model_name": model_name(name), "expected_names": expected_names(name),
            "compute": settings["compute"], "data_version": version,
            "train_run_id": f"aif49-{key}-{'train' if name == CHURN else 'retrain'}-{stamp}",
            "inference_run_id": f"aif49-{key}-inf-{stamp}",
            "component_version": now.strftime("%Y%m%d%H%M"),
            "inference_rows": settings["inference_rows"],
            "lake": _lake(config, name, version, name),
            "esml_receipts": str(location.esml(name)),
        }
        if name == CHURN:
            entry["inference_seed"] = settings["inference_seed"]
            entry["synthetic"] = True
        else:
            entry["input_path"] = air_binding["input_path"]
            entry["champion_model_id"] = settings["champion_model_id"]
            entry["synthetic"] = False
        entries[name] = entry
    plan = {
        "schema": SCHEMA, "config_sha256": fingerprint(config), "owner": config["owner"],
        "created_at": now.isoformat(), "data_date_utc": now.strftime("%Y-%m-%d"),
        "scope": {"aifactory": config["aifactory"], "project": f"project{config['project_number']:03d}",
                  "environment": config["environment"], "datastore": config["shared_lake"]["datastore"],
                  "workspace": reviewed["runtime"]["workspace_name"],
                  "resource_group": reviewed["runtime"]["resource_group"]},
        "usecases": entries,
        "azure_writes": [
            f"Create-only lake publication of synthetic {CHURN} data version {churn_version} (master, shared silver, project IN).",
            f"Azure ML data assets and pipeline component for {model_name(CHURN)}; training job on {entries[CHURN]['compute']}.",
            f"Quality-gated registration of {model_name(CHURN)} (first version, explicit no-champion selection).",
            f"Azure ML data assets, component and retraining job for {model_name(AIR)} on {entries[AIR]['compute']}; "
            "registration only if the selection policy promotes the candidate.",
            "Create-only gold inference inputs and one GOLD_INFERENCE pipeline job per use case.",
            "Paid model responses for the conversations (the CLI also creates one owned Foundry prompt-agent "
            "version; the hosted agent mirrors its receipts below the M49 use case's agent-state folder).",
        ],
        "never": ["role assignments", "networking, private endpoints or DNS", "Search", "SKUs or tiers",
                  "model deployments", "compute creation or deletion", "endpoint creation",
                  "deletion of any model, data asset, endpoint or lake file"],
    }
    return plan


def plan_sha256(plan_path: Path) -> str:
    return hashlib.sha256(Path(plan_path).read_bytes()).hexdigest()


def save_plan(config: dict, plan: dict, *, unique: bool = False) -> tuple[Path, str]:
    """Write the plan; `unique` (hosted, several users) adds seconds and a random suffix, create-only."""
    location = paths(config)
    if unique:
        import secrets

        stamp = plan["created_at"][:19].replace(":", "").replace("-", "")
        path = location.state / "plans" / f"plan-{stamp}-{secrets.token_hex(4)}.json"
        if path.exists():
            raise ValueError("Plan file already exists; plan again")
        path = write_json(path, plan)
    else:
        path = write_json(location.state / "plans" / f"plan-{plan['created_at'][:16].replace(':', '')}.json", plan)
    return path, plan_sha256(path)


def approved_plan(plan_path: Path, sha256: str, config: dict) -> dict:
    """Return the approved plan only if its bytes and the current configuration are unchanged."""
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("Pass the approved plan SHA-256 exactly as printed by `plan`.")
    if plan_sha256(plan_path) != sha256:
        raise ValueError("The plan file differs from the approved SHA-256; review and approve it again.")
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if plan.get("schema") != SCHEMA or plan.get("config_sha256") != fingerprint(config):
        raise ValueError("Configuration changed after approval; create and approve a new plan.")
    return plan


def require(plan: dict, name: str, operation: str) -> dict:
    entry = plan.get("usecases", {}).get(name)
    if entry is None or operation not in entry.get("operations", []):
        raise PermissionError(f"The approved plan does not include {operation} for {name}.")
    return deepcopy(entry)
