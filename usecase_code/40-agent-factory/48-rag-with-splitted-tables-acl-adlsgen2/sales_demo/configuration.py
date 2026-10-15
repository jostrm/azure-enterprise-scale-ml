"""Consumer-owned configuration and hash-pinned publication integrity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit
from uuid import UUID


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or PurePosixPath(value).is_absolute()
            or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", part)
                   or ".." in part for part in value.split("/"))):
        raise ValueError("An explicit literal relative storage path is required.")
    return value


def local_file(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative_path(relative).split("/"))
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("Publication file escapes its selected local root.")
    return path


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Entra identifiers must be UUID strings.")
    return str(UUID(value))


def _storage_id(config: dict) -> None:
    value = config["storage_resource_id"]
    expected = (
        f"/subscriptions/{config['subscription_id']}/resourceGroups/"
    )
    if (not value.lower().startswith(expected.lower())
            or not re.fullmatch(
                r"/subscriptions/[0-9a-f-]{36}/resourceGroups/[A-Za-z0-9_.-]+"
                r"/providers/Microsoft.Storage/storageAccounts/[a-z0-9]{3,24}", value)
            or value.split("/")[-1] != config["storage_account"]):
        raise ValueError("Storage must be an exact account in the selected subscription.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", config["container"]) or "--" in config["container"]:
        raise ValueError("An explicit resolved container is required.")


def make_config(factory, binding: dict, artifacts: Path, factory_config: Path, target: str) -> dict:
    """Resolve the lake from existing configuration, not portal URL assumptions."""
    if binding.get("location") != "common" or not binding.get("container"):
        raise ValueError("Select an existing common-lake binding with an explicit container.")
    publication_path = artifacts.resolve() / "publication.json"
    publication = read_json(publication_path)
    version = relative_path(publication["version"])
    if "/" in version or publication["dataset"] != "car-sales":
        raise ValueError("The generated car-sales publication needs a single version identifier.")
    project = f"project{factory.project_number}"
    environment = factory.environment
    storage_id = binding["storage_account_resource_id"]
    common_scope = (
        f"/subscriptions/{factory.subscription_id}/resourceGroups/{factory.common_resource_group}"
        "/providers/Microsoft.Storage/storageAccounts/"
    )
    if not storage_id.lower().startswith(common_scope.lower()):
        raise ValueError("Common-lake binding contradicts the selected factory scope.")
    result = {
        "owner": f"aif48-{project}-{environment}", "dataset": "car-sales", "version": version,
        "tenant_id": factory.tenant_id, "subscription_id": factory.subscription_id,
        "project": project, "environment": environment, "factory_config": str(factory_config.resolve()),
        "target": target, "storage_resource_id": storage_id,
        "storage_account": storage_id.split("/")[-1], "container": binding["container"],
        "master_prefix": f"mlops/v1/master/environments/{environment}/datasets/car-sales/versions/{version}",
        "project_prefix": (
            f"mlops/v1/projects/{project}/environments/{environment}"
            f"/usecases/car-sales/rag/corpora/car-sales/versions/{version}"
        ),
        "paths_approved": False,
        "search_endpoint": f"https://{factory.search_name}.search.windows.net" if factory.search_name else "",
        "embedding_endpoint": "",
        "embedding_deployment": factory.embedding_deployment,
        "model_deployment": factory.model_deployment,
        "project_endpoint": "", "backend_identity_client_id": "", "search_identity_object_id": "",
        "acl_test_principal_ids": [], "denied_test_user_ids": [],
        "artifacts_root": str(artifacts.resolve()), "publication_file": str(publication_path),
        "publication_sha256": digest(publication_path.read_bytes()),
        "publication_state": str(artifacts.resolve().parent / f"{version}-verified-publication.json"),
        "partition_policies": {
            key: {"allowed_group_ids": [], "allowed_user_ids": []} for key in ("json", "excel")
        },
        "image": None,
    }
    _storage_id(result)
    return result


def load_config(path: Path) -> dict:
    result = read_json(path)
    for name in ("tenant_id", "subscription_id"):
        result[name] = _uuid(result[name])
    for name in ("backend_identity_client_id", "search_identity_object_id"):
        if result.get(name):
            result[name] = _uuid(result[name])
    for name in ("acl_test_principal_ids", "denied_test_user_ids"):
        if name in result:
            if not isinstance(result[name], list):
                raise ValueError("Test identities must be explicit Entra identifier lists.")
            result[name] = [_uuid(value) for value in result[name]]
    if (result["dataset"] != "car-sales" or not re.fullmatch(r"project[0-9]{3}", result["project"])
            or result["environment"] not in {"dev", "test", "prod"}
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,44}", result["owner"])
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", result["version"])):
        raise ValueError("Invalid dataset, project, environment, owner or version.")
    _storage_id(result)
    version, environment, project = result["version"], result["environment"], result["project"]
    expected_paths = {
        "master_prefix": f"mlops/v1/master/environments/{environment}/datasets/car-sales/versions/{version}",
        "project_prefix": (
            f"mlops/v1/projects/{project}/environments/{environment}"
            f"/usecases/car-sales/rag/corpora/car-sales/versions/{version}"
        ),
    }
    for key, expected in expected_paths.items():
        if relative_path(result[key]).rstrip("/") != expected:
            raise ValueError("Storage path contradicts the selected immutable publication.")
    artifact_root = Path(result["artifacts_root"]).resolve()
    publication_path = Path(result["publication_file"]).resolve()
    if publication_path != artifact_root / "publication.json":
        raise ValueError("The integrity manifest must belong to the selected artifact root.")
    raw = publication_path.read_bytes()
    if digest(raw) != result["publication_sha256"]:
        raise ValueError("Publication integrity pin changed; regenerate and explicitly review configuration.")
    publication = json.loads(raw)
    if (set(publication) - {"dataset", "version", "seed", "state", "partitions", "files", "schema_version"}
            or publication["dataset"] != result["dataset"] or publication["version"] != version
            or publication.get("state") != "generated"):
        raise ValueError("Invalid integrity manifest; evaluation answers cannot enter runtime configuration.")
    partitions = publication["partitions"]
    if len(partitions) != 2 or {p["id"] for p in partitions} != {"json", "excel"}:
        raise ValueError("The primary publication requires both distinct sales partitions.")
    policies = result["partition_policies"]
    if set(policies) != {"json", "excel"}:
        raise ValueError("Explicit authorization policy is required for each partition.")
    hydrated = []
    for partition in partitions:
        key = partition["id"]
        policy = policies[key]
        if set(policy) - {"allowed_group_ids", "allowed_user_ids"}:
            raise ValueError("Authorization policy cannot replace publication integrity.")
        for field in ("allowed_group_ids", "allowed_user_ids"):
            if field in policy and not isinstance(policy[field], list):
                raise ValueError("Explicit Entra permission lists are required.")
            if field in policy:
                policy[field] = [_uuid(identity) for identity in policy[field]]
        for field, prefix in (("input_path", f"ingestion/{key}/"), ("rows_path", f"structured/{key}/")):
            if not relative_path(partition[field]).startswith(prefix):
                raise ValueError("Source or structured rows escape the partition boundary.")
        for field in ("input_sha256", "rows_sha256", "sale_ids_sha256"):
            if not re.fullmatch(r"[a-f0-9]{64}", partition[field]):
                raise ValueError("Publication requires exact lowercase SHA-256 pins.")
        if (partition["source"] != key or type(partition["row_count"]) is not int
                or partition["row_count"] <= 0 or partition["expected_chunks"] != 3
                or type(partition["input_tokens"]) is not int or partition["input_tokens"] <= 9000):
            raise ValueError("Invalid partition identity, size or coverage contract.")
        hydrated.append({**partition, **policy})
    result["partitions"] = hydrated
    result["publication"] = publication
    return result


def readiness(config: dict) -> list[str]:
    missing = []
    if config.get("paths_approved") is not True:
        missing.append("Approve the exact master/project dataset paths.")
    for key, suffix in (
        ("search_endpoint", ".search.windows.net"),
        ("embedding_endpoint", ".openai.azure.com"),
        ("project_endpoint", ".services.ai.azure.com"),
    ):
        parsed = urlsplit(config.get(key, ""))
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(suffix)
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.port not in (None, 443)):
            missing.append(f"Resolve {key} through read-only discovery.")
    for key in ("backend_identity_client_id", "search_identity_object_id"):
        if not config.get(key):
            missing.append(f"Select {key}; no implicit identity fallback.")
        else:
            _uuid(config[key])
    for partition in config["partitions"]:
        if not partition.get("allowed_group_ids"):
            missing.append(f"Select Entra reader groups for {partition['id']}.")
    groups = {item for p in config["partitions"] for item in p.get("allowed_group_ids", [])}
    users = {item for p in config["partitions"] for item in p.get("allowed_user_ids", [])}
    if len(groups) + len(users) + 5 > 32:
        missing.append("The directory ACL would exceed ADLS's 32-entry limit.")
    if config.get("search_identity_object_id") in users:
        missing.append("An ingestion identity cannot be configured as a delegated test reader.")
    if not config.get("acl_test_principal_ids") or not config.get("denied_test_user_ids"):
        missing.append("Select allowed and denied test principals for broad-role and ACL checks.")
    if config.get("embedding_deployment") != "text-embedding-3-large":
        missing.append("Select the text-embedding-3-large deployment.")
    return missing
