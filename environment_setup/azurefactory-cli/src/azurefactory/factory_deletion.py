"""Fail-closed checks for the named, whole-factory deletion review."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from .errors import ConfigError, FailureError

PURPOSE = "delete-aifactory-confirm"
CAPABILITY = "delete-aifactory-v1"
RETENTION_CONTRACT = "ordered-project-pipelines-v1"
REQUEST_FIELDS = {"contract_version", "folder", "factory_id", "expected_revision", "version_ref"}
PLAN_CONTRACT = "ordered-project-pipelines-v1"
DELETE_FLAGS = {"enableDeleteForDisabledResources": True, "deleteAllServicesForProject": True,
                "deleteKeyvaultAlso": True, "deleteAllForProject": True}
PROJECT_ORDER = ["foundry-capability-hosts", "target-project-search-shared-private-links",
                 "service-managed-lifecycle", "project-resources", "project-network"]
PIPELINE_DEFINITIONS = {"gha": ".github/workflows/factory-lifecycle.yml",
                        "ado": "aifactory/pipelines/factory-lifecycle.yml"}


def _contains(parent: str, child: str) -> bool:
    return child.lower() == parent.lower() or child.lower().startswith(parent.lower() + "/")


def validate_deletion_plan(plan: Any, factory_id: str, scales: dict[str, Any], factory: dict[str, Any],
                           targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Client-side recheck of the server's hashed ordered pipeline plan; never a local deletion plan."""
    def invalid(reason):
        raise ConfigError("Unsafe or incompatible factory deletion plan: " + reason
                          + ". Project teardown must use the reviewed GHA/ADO pipelines; no local fallback is allowed.")

    if not isinstance(plan, dict):
        invalid("missing ordered-project-pipelines-v1 plan")
    try:
        # The API's catalog_storage.digest uses indented UTF-8 JSON plus a newline, not receipt hashing.
        encoded = (json.dumps({key: value for key, value in plan.items() if key != "plan_hash"},
                              ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        invalid("the ordered pipeline plan is not strict UTF-8 JSON")
    if (plan.get("contract") != PLAN_CONTRACT
            or plan.get("factory_id") != factory_id or plan.get("policy") != "all-projects-before-common"
            or not _hash(plan.get("plan_hash"))
            or hashlib.sha256(encoded).hexdigest() != plan["plan_hash"]
            or not isinstance(plan.get("source_commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", plan["source_commit"])):
        invalid("missing, legacy or modified ordered-project-pipelines-v1 plan")
    protected = plan.get("protected_resources")
    if not isinstance(protected, list) or any(not _text(item) or not item.lower().startswith("/subscriptions/")
                                              for item in protected):
        invalid("missing protected-resource list")
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages or len({stage.get("id") for stage in stages
                                                          if isinstance(stage, dict)}) != len(stages):
        invalid("missing or duplicate stages")
    reviewed = {}
    for target in targets:
        for entry in target["delete"]:
            reviewed[entry.lower()] = target["scale_set_id"]
    expected = {(placement.get("scale_set_id"), project.get("id"))
                for project in factory.get("projects", []) if isinstance(project, dict)
                for placement in project.get("placements", []) if isinstance(placement, dict)
                if placement.get("scale_set_id") in scales}
    projects, covered, seen_common = [], set(), False
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("kind") not in ("project", "common"):
            invalid("unknown stage")
        scale = scales.get(stage.get("scale_set_id"))
        if (scale is None or stage.get("factory_id") != factory_id
                or any(stage.get(field) != scale[field] for field in ("environment", "subscription_id", "tenant_id"))):
            invalid("a stage changed its factory, scale set, subscription or tenant")
        deleted = stage.get("delete")
        if not isinstance(deleted, list) or not deleted:
            invalid("a stage has no exact deletions")
        for entry in deleted:
            if not _text(entry) or reviewed.get(entry.lower()) != scale["id"] or entry.lower() in covered:
                invalid("stage deletions differ from the reviewed exact inventory")
            covered.add(entry.lower())
        if stage["kind"] == "project":
            pipeline = stage.get("pipeline")
            if (seen_common or stage.get("depends_on") != [] or stage.get("inputs") != DELETE_FLAGS
                    or any(value is not True for value in stage["inputs"].values())
                    or stage.get("lifecycle_order") != PROJECT_ORDER or not isinstance(pipeline, dict)
                    or pipeline.get("provider") not in PIPELINE_DEFINITIONS
                    or pipeline.get("definition") != PIPELINE_DEFINITIONS[pipeline["provider"]]
                    or not _text(pipeline.get("repository")) or not _text(pipeline.get("ref"))
                    or not re.fullmatch(r"[0-9a-f]{40}", str(pipeline.get("commit", "")))):
                invalid("project pipelines need the pinned definition and all four boolean-true deletion flags "
                        "before any common teardown")
            projects.append(stage)
        else:
            seen_common = True
    for stage in stages:
        if stage["kind"] == "common" and stage.get("depends_on") != [item["id"] for item in projects]:
            invalid("common teardown must wait for every project pipeline in every environment")
    if ({(stage["scale_set_id"], stage.get("project_id")) for stage in projects} != expected
            or len(projects) != len(expected)):
        invalid("every registered project placement in every environment needs exactly one pipeline stage")
    if covered != set(reviewed):
        invalid("stages do not cover every reviewed deletion exactly once")
    if any(_contains(entry, keep) or _contains(keep, entry) for entry in covered for keep in protected):
        invalid("deletion overlaps protected hub, VPN, bootstrap or shared resources")
    return plan


def describe_deletion_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Stage": stage["id"], "Kind": stage["kind"], "Environment": stage["environment"],
             "Project": stage.get("project_number") or "common", "Resource group": stage["resource_group_id"],
             "Deletes": stage["delete"], "Waits for": stage["depends_on"],
             **({"Pipeline": stage["pipeline"], "Deletion flags": stage["inputs"],
                 "Project teardown order": stage["lifecycle_order"]} if stage["kind"] == "project" else {})}
            for stage in plan["stages"]]


def _text(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and value == value.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _uuid(value: Any) -> bool:
    try:
        parsed = UUID(value)
        return bool(parsed.int) and str(parsed) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_request(request: Any) -> None:
    if (not isinstance(request, dict) or set(request) - REQUEST_FIELDS
            or type(request.get("contract_version")) is not int or request["contract_version"] != 1
            or not _text(request.get("folder")) or not _uuid(request.get("factory_id"))
            or not _hash(request.get("expected_revision"))
            or ("version_ref" in request and not _text(request["version_ref"]))):
        raise ConfigError("Factory deletion requires contract 1, an exact folder and factory UUID, "
                          "a current revision fingerprint, and no narrowed or additional scope.")


def validate_deletion_preview(request: dict[str, Any], preview: Any) -> None:
    from .client import canonical_json_hash
    from .review import validate_preview

    def invalid(reason):
        raise ConfigError("Unsafe or incompatible factory deletion preview: " + reason + ".")

    validate_request(request)
    if (not isinstance(preview, dict) or type(preview.get("contract_version")) is not int
            or preview["contract_version"] != 1 or not isinstance(preview.get("capabilities"), list)
            or CAPABILITY not in preview["capabilities"]):
        invalid("the API must acknowledge delete-aifactory-v1; no fallback is allowed")
    validate_preview(preview)
    if (preview.get("operation_mode") != "runtime"
            or preview.get("action") != "delete-factory"
            or preview.get("folder") != request["folder"]
            or preview.get("factory_id") != request["factory_id"]
            or preview.get("scale_set_id") is not None or preview.get("project_id") is not None
            or preview.get("deletion_options") is not None
            or preview.get("source_revision") != request["expected_revision"]):
        invalid("the exact whole factory and saved revision were not preserved")
    if not _uuid(preview.get("confirmation_id")) or not _hash(preview.get("preview_hash")):
        invalid("missing exact confirmation identity or server preview fingerprint")
    if (preview.get("deletion_scope") != "whole-factory"
            or preview.get("preserve_entra_groups") is not True
            or preview.get("retain_saved_configuration") is not False):
        invalid("the backend did not prove whole-factory scope, Entra preservation and saved configuration handling")
    policy = preview.get("deletion_retention_policy")
    if (not isinstance(policy, dict) or policy.get("mode") != "preserve-reusable-infrastructure"
            or policy.get("required_execution_contract") != PLAN_CONTRACT
            or policy.get("execution_scope") != "whole-resource-groups"
            or policy.get("selective_retention_supported") is not False
            or not isinstance(policy.get("limitations"), list) or not policy["limitations"]
            or any(not _text(item) for item in policy["limitations"])):
        invalid("the API must explicitly acknowledge its whole-group retention policy and limitations")
    plan = preview.get("deletion_plan")
    if (not isinstance(plan, dict) or plan.get("contract") != PLAN_CONTRACT
            or canonical_json_hash(plan.get("retention_policy")) != canonical_json_hash(policy)):
        invalid("retention policy differs from the server execution plan")
    factory = preview.get("target")
    if (not isinstance(factory, dict) or factory.get("id") != request["factory_id"]
            or not _text(factory.get("key")) or not isinstance(factory.get("scale_sets"), list)
            or not factory["scale_sets"]):
        invalid("missing the exact factory and all its scale sets")
    phrase = preview.get("confirmation_phrase")
    if not _text(phrase) or phrase != "DELETE " + factory["key"]:
        invalid("the server confirmation phrase does not identify the reviewed factory")
    version = preview.get("source_version")
    if (not isinstance(version, dict)
            or any(not _text(version.get(field)) for field in ("requested_version", "branch", "resolved_ref"))
            or ("version_ref" in request and version.get("aifactory_version") != request["version_ref"])):
        invalid("missing or changed backend source version")
    for field in ("effects", "warnings", "retained_resources"):
        if not isinstance(preview.get(field), list) or any(not _text(item) for item in preview[field]):
            invalid("missing exact effects, warnings or retained resource manifest")
    scales = {}
    for scale in factory["scale_sets"]:
        if (not isinstance(scale, dict) or any(not _uuid(scale.get(field)) for field in
                                             ("id", "tenant_id", "subscription_id"))
                or scale.get("environment") not in ("dev", "stage", "prod") or scale["id"] in scales):
            invalid("invalid or duplicate scale-set identity")
        scales[scale["id"]] = scale
    targets = preview.get("deletion_targets")
    if not isinstance(targets, list) or not targets:
        invalid("empty deletion manifest")
    groups, deleted, retained, covered = set(), set(), set(), set()
    for target in targets:
        if not isinstance(target, dict) or not isinstance(target.get("scale_set_id"), str):
            invalid("invalid deletion target")
        scale = scales.get(target["scale_set_id"])
        if (scale is None or target.get("factory_id") != request["factory_id"]
                or target.get("project_id") is not None
                or any(target.get(field) != scale[field] for field in
                       ("environment", "subscription_id", "tenant_id"))):
            invalid("a deletion target broadened or changed its factory, scale set, subscription or tenant")
        name = target.get("resource_group")
        if (not _text(name) or not re.fullmatch(r"[\w().-]{1,90}", name)
                or name.endswith(".") or target.get("name") != name):
            invalid("invalid resource-group name")
        group = f"/subscriptions/{scale['subscription_id']}/resourceGroups/{name}"
        if target.get("resource_id") != group or group.lower() in groups:
            invalid("resource-group identity changed or appeared more than once")
        groups.add(group.lower())
        covered.add(scale["id"])
        members = {}
        for field in ("delete", "retain"):
            entries = target.get(field)
            if not isinstance(entries, list) or (field == "delete" and not entries):
                invalid("missing or empty resource manifest")
            members[field] = set()
            for entry in entries:
                if (not _text(entry) or "\\" in entry or "?" in entry or "#" in entry
                        or any(part in (".", "..", "") for part in entry.split("/")[1:])
                        or not (entry.lower() == group.lower() or
                                entry.lower().startswith(group.lower() + "/providers/"))
                        or entry.lower() in members[field]):
                    invalid("duplicate resource or resource outside its exact reviewed group")
                members[field].add(entry.lower())
        if (members["delete"] & members["retain"]
                or (group.lower() in members["delete"] and members["retain"])):
            invalid("deleted and retained resources contradict each other")
        if group.lower() not in members["delete"] or members["retain"]:
            invalid("the acknowledged whole-group runtime cannot execute selective retention")
        deleted.update(members["delete"])
        retained.update(members["retain"])
    if covered != set(scales):
        invalid("the manifest does not cover every scale set of the whole factory")
    plan = validate_deletion_plan(preview.get("deletion_plan"), request["factory_id"], scales, factory, targets)
    for field in ("protected_resources", "retained_resources"):
        entries = plan.get(field)
        if not isinstance(entries, list):
            invalid("missing frozen plan retention manifest")
        seen = set()
        for entry in entries:
            if (not _text(entry) or not re.fullmatch(
                    r"/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[^/?#\\\x00-\x20]+"
                    r"(?:/providers/[^?#\\\x00-\x20]+)?", entry)
                    or any(part in (".", "..", "") for part in entry.split("/")[1:])
                    or entry.lower() in seen):
                invalid("invalid or duplicate frozen retained resource")
            seen.add(entry.lower())
        if retained & seen:
            invalid("duplicate protected and retained resource entries")
        retained.update(seen)
    if any(keep == group or keep.startswith(group + "/") for group in groups for keep in retained):
        invalid("retained infrastructure overlaps a group selected for cascading deletion")
    listed_retained = preview["retained_resources"]
    if (len({item.lower() for item in listed_retained}) != len(listed_retained)
            or {item.lower() for item in listed_retained} != retained):
        invalid("retained resources differ from the exact target manifests and frozen plan resources")
    inventory = preview.get("inventory")
    if not isinstance(inventory, list) or any(
            not isinstance(item, dict) or not _text(item.get("resource_id")) for item in inventory):
        invalid("missing exact deletion inventory")
    ids = [item["resource_id"].lower() for item in inventory]
    if len(set(ids)) != len(ids) or set(ids) != deleted:
        invalid("deletion inventory is empty, incomplete or broader than the reviewed manifest")


def validate_job(job: Any, *, factory_id: str | None = None, job_id: str | None = None) -> None:
    if (not isinstance(job, dict) or job.get("action") != "delete-factory"
            or not _uuid(job.get("id")) or not _uuid(job.get("factory_id"))
            or (factory_id is not None and job["factory_id"] != factory_id)
            or (job_id is not None and job["id"] != job_id)
            or job.get("scale_set_id") is not None or job.get("project_id") is not None
            or job.get("status") not in ("queued", "running", "succeeded", "failed", "interrupted")):
        raise FailureError("Deletion returned an incompatible job or changed scope. "
                           "Inspect server state; never blindly retry confirmation.")
