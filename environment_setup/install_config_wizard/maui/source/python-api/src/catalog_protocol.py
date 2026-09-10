"""Strict adapter to the published factory_lifecycle contract, never legacy launchers."""

import base64
import hashlib
import json
import math
import re
from uuid import UUID

from pydantic import ValidationError

from src.catalog_storage import CatalogError, read_json
from src.factory_catalog_models import BindingTarget, LockEnrollment, RuntimeBinding


LEAF_TYPES = {"microsoft.network/publicipaddresses": "2024-05-01", "microsoft.compute/disks": "2024-03-02"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def load_binding(root, factory, scale, cli):
    path = root / "config-wizard" / "factories" / factory["key"] / "orchestrators" / (scale["orchestrator"] + ".json")
    if not path.is_file():
        raise CatalogError("Configure the factory's orchestrators/" + scale["orchestrator"] +
                           ".json with a reviewed remote and operator-provisioned Azure Blob lock enrollment before deployment.", 409)
    try:
        binding = RuntimeBinding.model_validate(read_json(path)).model_dump(mode="json")
    except ValidationError:
        raise CatalogError("Orchestrator binding must follow the closed lifecycle binding schema.", 409) from None
    if binding["orchestrator"] != scale["orchestrator"]:
        raise CatalogError("Orchestrator binding conflicts with the selected physical writer.", 409)
    pattern = (r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" if scale["orchestrator"] == "gha" else
               r"https://dev\.azure\.com/[A-Za-z0-9_.%-]+/[A-Za-z0-9_.%-]+/_git/[A-Za-z0-9_.%-]+")
    if (not re.fullmatch(pattern, binding["repository"]) or ".." in binding["ref"]
            or ".." in binding["locks"]["coordination_blob"]):
        raise CatalogError("The reviewed repository/ref/lock enrollment address is unsafe.", 409)
    matches = [item for item in binding["targets"] if item["scale_set_id"] == scale["id"]]
    if len(matches) != 1:
        raise CatalogError("The selected scale set needs exactly one explicit physical lock binding.", 409)
    target = matches[0]
    if target.get("execution"):
        binding.update(target["execution"])
    if binding["auth_namespace"] and not binding.get("runner"):
        raise CatalogError("Namespaced execution requires an explicit hosted or self-hosted Linux runner in the binding.", 409)
    rg_pattern = r"/subscriptions/([a-f0-9-]{36})/resourceGroups/[^/]+"
    for resource in [*target["resource_group_ids"], *target["common_dependency_ids"]]:
        match = re.fullmatch(rg_pattern, resource, re.I)
        if not match or (resource in target["resource_group_ids"] and match[1].lower() != scale["subscription_id"].lower()):
            raise CatalogError("Physical lock scopes must be explicit resource-group ARM IDs in the selected subscription.", 409)
    remote = cli.read("git", ["ls-remote", "--exit-code", binding["repository"], binding["ref"]], raw=True).split()
    if len(remote) != 2 or remote[1] != binding["ref"] or not re.fullmatch(r"[a-f0-9]{40}", remote[0]):
        raise CatalogError("The exact consumer repository ref is not published.", 409)
    resolved = {"route": {"kind": binding["orchestrator"], "writer_id": binding["writer_id"],
                      "repository": binding["repository"], "ref": binding["ref"], "commit": remote[0],
                      "shared_remote": binding["shared_remote"]},
            "locks": {"provider": "azure-blob-lease", **binding["locks"],
                      "scopes": target["resource_group_ids"], "common_dependencies": target["common_dependency_ids"]}}
    if bool(binding["auth_namespace"]) != bool(binding["deployment_object_id"]):
        raise CatalogError("Namespaced execution requires both auth_namespace and deployment_object_id.", 409)
    if binding["auth_namespace"]:
        resolved["route"].update(scoped_contract=1, auth_namespace=binding["auth_namespace"])
        resolved["_deployment_object_id"] = binding["deployment_object_id"]
        resolved["route"]["runner"] = binding["runner"]
    if binding["orchestrator"] == "gha":
        actor = cli.read("gh", ["api", "user", "--hostname", "github.com", "--method", "GET"])
        if not isinstance(actor, dict) or type(actor.get("id")) is not int or actor["id"] <= 0:
            raise CatalogError("A verified current GitHub account identity is required; sign in explicitly before preparation.", 409)
        resolved["route"]["github_user_id"] = actor["id"]
    enrollment = cli.read("az", ["rest", "--method", "GET", "--resource", "https://storage.azure.com/",
        "--url", binding["locks"]["account_url"] + "/" + binding["locks"]["container"] + "/" + binding["locks"]["coordination_blob"],
        "--output", "json"])
    if (not isinstance(enrollment, dict) or fingerprint(enrollment) != binding["locks"]["coordination_hash"]
            or enrollment.get("revision") != binding["locks"]["revision"]
            or enrollment.get("protocol") != "aifactory-physical-lock-v1"
            or enrollment.get("enforcement") != "all-writers-exclusive"):
        raise CatalogError("Live lock enrollment does not match the reviewed exclusive-writer hash/revision.", 409)
    writer = enrollment.get("writers", {}).get(binding["writer_id"])
    expected_writer = {key: resolved["route"][key] for key in ("kind", "repository", "shared_remote")}
    if binding["auth_namespace"]:
        expected_writer.update(auth_namespace=binding["auth_namespace"], deployment_object_id=binding["deployment_object_id"],
                               runner=binding["runner"])
    if writer != expected_writer:
        raise CatalogError("Live lock enrollment does not designate this exact writer/repository.", 409)
    expected_target = {"factory_id": factory["id"], "scaleset_id": scale["id"], "prefix": factory["prefix"],
                       "region": factory["region"], "environment": scale["environment"], "suffix": scale["suffix"],
                       "tenant_id": scale["tenant_id"], "subscription_id": scale["subscription_id"]}
    for resource in target["resource_group_ids"]:
        record = enrollment.get("scopes", {}).get(resource.lower(), {})
        if (record.get("writers") != [binding["writer_id"]] or record.get("target") != expected_target
                or {item.lower() for item in record.get("common_dependencies", [])}
                != {item.lower() for item in target["common_dependency_ids"]}):
            raise CatalogError("Live lock enrollment does not cover the exact selected target and all common dependencies.", 409)
    for resource in [*target["resource_group_ids"], *target["common_dependency_ids"]]:
        if resource.lower() not in enrollment.get("scopes", {}):
            raise CatalogError("Every shared common dependency must participate in the same lock enrollment.", 409)
    resolved["_delete_authorized"] = all(
        enrollment["scopes"][resource.lower()].get("allow_delete") is True
        and enrollment["scopes"][resource.lower()].get("scope_kind") == "aifactory-owned"
        for resource in target["resource_group_ids"])
    return resolved


def token_identity(cli, scale, clock):
    token = cli.read("az", ["account", "get-access-token", "--subscription", scale["subscription_id"],
                            "--resource", "https://management.azure.com/", "--output", "json"])
    try:
        encoded = token["accessToken"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        oid = str(UUID(claims["oid"]))
        expiry, before = float(claims["exp"]), float(claims.get("nbf", 0))
        if (str(claims["tid"]).lower() != scale["tenant_id"].lower() or not math.isfinite(expiry)
                or not math.isfinite(before) or expiry <= clock() or before > clock() + 60
                or claims.get("aud") not in ("https://management.azure.com", "https://management.azure.com/",
                                              "https://management.core.windows.net/", "797f4846-ba00-4fd7-ba43-dac1f8f63013")):
            raise ValueError("Identity mismatch")
    except (KeyError, IndexError, ValueError, TypeError):
        raise CatalogError("A current authenticated Azure object identity is required for the exact selected tenant/subscription.", 409) from None
    return oid


def operation_blockers(request, scale, binding):
    if scale["suffix"] == "000":
        raise CatalogError("Published lifecycle runtime requires a nonzero scale-set suffix; legacy 000 cannot be silently retargeted.", 409)
    if request["action"] == "deploy" and not request["project_id"]:
        raise CatalogError("Published runtime contract 1 cannot safely create common-only factory/scale-set resources. Install a release with frozen-config, isolated common-only creation support.", 409)
    if request["action"] == "delete-factory":
        raise CatalogError("Published runtime contract 1 lacks complete whole-factory nested/extension/data-plane inventory collectors. Full factory deletion is blocked, never reduced to a partial delete.", 409)
    if request["action"].startswith("delete") and not binding.get("_delete_authorized"):
        raise CatalogError("Live enrollment does not explicitly authorize deletion of the selected factory-owned physical scopes.", 409)
    if request["action"] == "deploy" and scale["orchestrator"] == "gha":
        raise CatalogError("Published runtime contract 1 lacks atomic reviewed-commit GHA dispatch; install a compatible release.", 409)
    if request["action"] == "deploy" and binding["route"]["shared_remote"]:
        raise CatalogError("Published runtime contract 1 lacks namespaced shared-remote authentication templates; use an isolated enrolled ADO repository or install compatible templates.", 409)


def deletion_document(evidence, allowlist, binding, revision, target):
    scopes = {scope.lower() for scope in binding["locks"]["scopes"]}
    approved = {item["resource_id"].lower() for item in allowlist}
    resources, groups = [], []
    for item in evidence["records"]:
        identifier = item["resource_id"]
        group = "/".join(identifier.split("/")[:5]).lower()
        if group not in scopes:
            continue
        if identifier.lower() != group and (
                item.get("shared") or item.get("factory_id") != target["factory_id"]
                or item.get("scale_set_id") != target["scaleset_id"]):
            raise CatalogError("Selected deletion scope contains foreign/shared children; complete deletion is blocked.", 409)
        if not item.get("body_hash"):
            raise CatalogError("A fresh full ARM resource fingerprint is required for deletion.", 409)
        common = {"id": identifier, "etag": item.get("etag"), "body_hash": item["body_hash"],
                  "delete": identifier.lower() in approved}
        if identifier.lower() == group:
            if common["delete"]:
                raise CatalogError("Published runtime cannot completely inventory resource-group extensions; resource-group deletion is blocked.", 409)
            groups.append(common)
            continue
        resource_type = str(item.get("type") or "").lower()
        if resource_type not in LEAF_TYPES:
            raise CatalogError("Full deletion is blocked by an unsupported provider inventory collector: " + resource_type, 409)
        resources.append({**common, "type": item["type"], "api_version": LEAF_TYPES[resource_type],
                          "depends_on": item.get("dependencies", []),
                          "owner": {"factory_id": item.get("factory_id"), "scaleset_id": item.get("scale_set_id"),
                                    **({"project_id": item["project_id"]} if item.get("project_id") else {})}})
    if {group["id"].lower() for group in groups} != scopes or not any(item["delete"] for item in resources):
        raise CatalogError("Deletion needs complete exact scoped resource/group inventory and a nonempty allowlist.", 409)
    if {item["id"].lower() for item in resources if item["delete"]} != approved:
        raise CatalogError("The exact deletion allowlist escaped the enrolled complete inventory scope.", 409)
    return {"inventory_complete": True, "revision": revision, "resources": resources, "resource_groups": groups,
            "inventory_hash": fingerprint(resources)}


def manifest(run_id, factory, scale, request, version, config, binding, evidence, allowlist, prepared_at, expires_at, frozen=False):
    projects = [p for p in factory["projects"] if p["id"] == request["project_id"] or (
        request["action"].startswith("delete") and any(placement["scale_set_id"] == scale["id"] for placement in p["placements"]))]
    operation = "delete" if request["action"].startswith("delete") else ("deploy-project" if request["project_id"] else "create-scaleset")
    account = next(item for item in evidence["accounts"] if item["subscription_id"] == scale["subscription_id"])
    document = {"schema": 1, "operation": operation,
                "run_id": run_id, "manifest_revision": 1, "prepared_at": prepared_at, "expires_at": expires_at,
                "source": {"commit": version["resolved_ref"], "ref": "refs/heads/" + version["branch"],
                           "version": version["requested_version"]},
                "target": {"factory_id": factory["id"], "scaleset_id": scale["id"], "prefix": factory["prefix"],
                           "region": factory["region"], "suffix": scale["suffix"], "environment": scale["environment"],
                           "subscription_id": scale["subscription_id"], "tenant_id": scale["tenant_id"],
                           "project_ids": [p["number"] for p in projects]},
                "identity": {"object_id": account["object_id"]},
                "route": binding["route"], "locks": binding["locks"], "config": config["targets"][scale["id"]]}
    if request["action"].startswith("delete") and not frozen:
        document["deletion"] = deletion_document(evidence, allowlist, binding, document["manifest_revision"], document["target"])
    document["manifest_hash"] = fingerprint(document)
    if len(canonical(document)) > 8 * 1024 * 1024:
        raise CatalogError("The frozen runtime manifest exceeds contract 1's bounded protected-input size.", 409)
    return document
