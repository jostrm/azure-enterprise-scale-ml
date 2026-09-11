#!/usr/bin/env python3
"""AIFACTORY_LIFECYCLE_CONTRACT=1: frozen, scoped, fail-closed execution.

See factory_lifecycle_contract.txt beside this module for the wire format and
operator-provisioned distributed locking prerequisite. Import, --help,
capabilities and inspect never authenticate, deploy, or modify a repository.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


CONTRACT = 1
MAX_DOCUMENT = 8 * 1024 * 1024
ARM = "https://management.azure.com"
SOURCE_ORIGIN = "https://github.com/jostrm/azure-enterprise-scale-ml"
GUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
RG_ID = re.compile(r"/subscriptions/(" + GUID + r")/resourceGroups/([A-Za-z0-9_.()-]{1,90})", re.I)
RESOURCE_ID = re.compile(RG_ID.pattern + r"/providers/([A-Za-z0-9.]+)/([A-Za-z0-9]+)/([A-Za-z0-9_.()-]{1,128})", re.I)
NESTED_ID = re.compile(RG_ID.pattern + r"/providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9_.()%-]+/[A-Za-z0-9_.()%-]+)+", re.I)
TAG_KEYS = {"factory_id": "aifactory.factory_id", "scaleset_id": "aifactory.scaleset_id",
            "project_id": "aifactory.project_id"}
# These ARM types have no independently managed child-resource collections.
# A new type requires an audited collector, not a caller-provided assertion.
LEAF_TYPES = {
    "microsoft.network/publicipaddresses": "2024-05-01",
    "microsoft.compute/disks": "2024-03-02",
}
RG_API = "2022-09-01"
SCOPED_CONTRACT = "AIFACTORY_SCOPED_DEPLOYMENT_CONTRACT=1"
SCOPED_GHA = ".github/workflows/factory-lifecycle.yml"
SCOPED_ADO = "aifactory/pipelines/factory-lifecycle.yml"
SCOPED_SOURCE = "bootstrap/templates/factory-lifecycle-"
COMMON_TEMPLATES = {name: "environment_setup/aifactory/bicep/esml-common/main/" + name + ".bicep"
                    for name in ("11-rgCommon", "12-networkCommon", "13-rgLevel")}
PROJECT_TEMPLATES = {"environment_setup/aifactory/bicep/esml-genai-1/" + name + ".bicep" for name in (
    "31-network", "01-foundation", "02-core-infrastructure", "03-cognitive-services", "04-databases",
    "05-compute-services", "06-ai-platform", "07-ml-data-platform", "08-rbac-security",
    "08b-rbac-common-rg", "09-ai-foundry-2025-v4", "10-aifactory-dashboards", "11-integration",
)}
EXTENSION_COLLECTIONS = (
    ("Microsoft.Authorization/roleAssignments", "2022-04-01"),
    ("Microsoft.Authorization/denyAssignments", "2018-07-01-preview"),
    ("Microsoft.Authorization/locks", "2016-09-01"),
    ("Microsoft.Authorization/policyAssignments", "2022-06-01"),
    ("Microsoft.Authorization/policyExemptions", "2022-07-01-preview"),
    ("Microsoft.Insights/diagnosticSettings", "2021-05-01-preview"),
)
UNSUPPORTED_COLLECTION_CODES = {
    "DiagnosticSettingsNotSupported", "ResourceTypeNotSupported", "UnsupportedResourceType",
    "ResourceTypeNotSupportedForDiagnosticSettings", "ScopeNotSupported",
}
MANAGED_GROUP_PARENT_TYPES = {
    "microsoft.containerservice/managedclusters", "microsoft.databricks/workspaces",
    "microsoft.synapse/workspaces", "microsoft.solutions/applications",
    "microsoft.machinelearningservices/workspaces",
}
ADO_PIPELINE = "aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/infra-project-genai.yaml"
ADO_FILES = {
    ADO_PIPELINE:
        "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-genai.yaml",
    "aifactory/esml-infra/azure-devops/bicep/yaml/esml-infra-project/jobs/job-0-reviewed-project-config.yaml":
        "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-0-reviewed-project-config.yaml",
}


class Blocked(ValueError):
    """A stable, non-secret error code suitable for a persistent receipt."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Blocked(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def manifest_digest(document):
    return digest({key: value for key, value in document.items() if key != "manifest_hash"})


def timestamp(value):
    require(isinstance(value, str), "invalid-timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "timezone-required")
        return result.timestamp()
    except (ValueError, OverflowError):
        raise Blocked("invalid-timestamp") from None


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def clean_path(value):
    path = Path(value).absolute()
    require(not any(item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction())
                    for item in (path, *path.parents)), "linked-path-forbidden")
    return path.resolve()


def arm_scope(resource_id):
    require(isinstance(resource_id, str), "invalid-arm-id")
    match = RG_ID.match(resource_id)
    require(match is not None and (match.end() == len(resource_id) or resource_id[match.end()] == "/"),
            "resource-group-scope-required")
    return match.group().lower()


def guid(value):
    return isinstance(value, str) and re.fullmatch(GUID, value) is not None


def hash_value(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def valid_ref(value):
    return (isinstance(value, str) and re.fullmatch(r"refs/(?:heads|tags)/[A-Za-z0-9_./-]+", value)
            and ".." not in value and "//" not in value and not value.endswith("/"))


def validate_manifest(document, now=None):
    _validate_manifest(document)
    now = time.time() if now is None else now
    require(timestamp(document["prepared_at"]) <= now < timestamp(document["expires_at"]),
            "manifest-expired-or-invalid-lifetime")
    return document


def _validate_manifest(document):
    """Validate immutable content; execution additionally requires a live claim."""
    require(isinstance(document, dict) and document.get("schema") == CONTRACT, "unsupported-manifest-schema")
    require(hash_value(document.get("manifest_hash")) and manifest_digest(document) == document["manifest_hash"],
            "manifest-hash-mismatch")
    require(document.get("operation") in ("create-factory", "create-scaleset", "deploy-project", "delete"),
            "unsupported-operation")
    require(guid(document.get("run_id")), "invalid-run-id")
    require(type(document.get("manifest_revision")) is int and document["manifest_revision"] > 0,
            "invalid-manifest-revision")
    created, expires = timestamp(document.get("prepared_at")), timestamp(document.get("expires_at"))
    require(0 < expires - created <= 3600, "manifest-expired-or-invalid-lifetime")
    for name in ("target", "identity", "route", "source", "config", "locks"):
        require(isinstance(document.get(name), dict), "missing-" + name)
    target, source, route = document["target"], document["source"], document["route"]
    require(target.get("factory_type", "ai") == "ai", "unsupported-factory-type")
    for name in ("factory_id", "scaleset_id", "prefix", "region"):
        require(isinstance(target.get(name), str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", target[name]),
                "invalid-target-" + name)
    require(guid(target.get("tenant_id")) and guid(target.get("subscription_id")), "invalid-azure-target")
    require(guid(document["identity"].get("object_id")), "missing-authenticated-object-id")
    require(target.get("environment") in ("dev", "stage", "prod"), "invalid-environment")
    require(isinstance(target.get("suffix"), str) and re.fullmatch(r"[0-9]{3}", target["suffix"])
            and target["suffix"] != "000", "invalid-scaleset-suffix")
    projects = target.get("project_ids")
    require(isinstance(projects, list) and all(isinstance(item, str) and re.fullmatch(r"[0-9]{3}", item)
                                             and item != "000" for item in projects)
            and len(set(projects)) == len(projects), "invalid-project-identities")
    require(isinstance(source.get("commit"), str) and re.fullmatch(r"[0-9a-f]{40}", source["commit"])
            and valid_ref(source.get("ref")) and isinstance(source.get("version"), str) and source["version"],
            "exact-published-version-required")
    require(route.get("kind") in ("gha", "ado") and isinstance(route.get("writer_id"), str)
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", route["writer_id"]), "invalid-writer")
    require(type(route.get("shared_remote")) is bool, "explicit-remote-sharing-required")
    repository = route.get("repository")
    require(isinstance(repository, str), "invalid-repository")
    parsed = urlsplit(repository)
    require(parsed.scheme == "https" and not parsed.username and not parsed.password and not parsed.query
            and not parsed.fragment and parsed.port in (None, 443), "credential-free-repository-required")
    require((route["kind"] == "gha" and parsed.netloc == "github.com"
             and re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", parsed.path))
            or (route["kind"] == "ado" and parsed.netloc == "dev.azure.com"
                and re.fullmatch(r"/[A-Za-z0-9_. -]+/[A-Za-z0-9_. -]+/_git/[A-Za-z0-9_. -]+", unquote(parsed.path))
                and len(parsed.path.split("/")) == len(unquote(parsed.path).split("/"))),
            "unsupported-repository")
    require(isinstance(route.get("commit"), str) and re.fullmatch(r"[0-9a-f]{40}", route["commit"])
            and valid_ref(route.get("ref")), "exact-consumer-version-required")
    locks = document["locks"]
    require(locks.get("provider") == "azure-blob-lease", "distributed-lock-provider-required")
    require(isinstance(locks.get("account_url"), str) and re.fullmatch(
        r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net", locks["account_url"]), "unsupported-lock-endpoint")
    require(isinstance(locks.get("container"), str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]",
                                                                 locks["container"]), "invalid-lock-container")
    require(isinstance(locks.get("coordination_blob"), str)
            and re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,255}", locks["coordination_blob"])
            and ".." not in locks["coordination_blob"], "invalid-enrollment-blob")
    require(hash_value(locks.get("coordination_hash")) and type(locks.get("revision")) is int
            and locks["revision"] > 0, "missing-enrollment-revision")
    scopes = locks.get("scopes")
    dependencies = locks.get("common_dependencies")
    require(isinstance(scopes, list) and scopes and isinstance(dependencies, list), "physical-lock-scopes-required")
    for scope in scopes + dependencies:
        require(isinstance(scope, str) and RG_ID.fullmatch(scope), "resource-group-lock-required")
    require(len(set(item.lower() for item in scopes)) == len(scopes), "duplicate-lock-scope")
    require(all(arm_scope(item).split("/")[2] == target["subscription_id"].lower() for item in scopes),
            "lock-subscription-mismatch")
    inherited = locks.get("inherited_leases", {})
    require(isinstance(inherited, dict) and set(inherited) <= {value.lower() for value in scopes + dependencies}
            and all(guid(value) for value in inherited.values()), "invalid-inherited-physical-leases")
    if document["operation"] == "deploy-project":
        require(len(projects) == 1, "one-project-per-run-required")
        if "deployment" not in document:
            validate_project(document)
    if "deployment" in document:
        validate_deployment_plan(document)
    if document["operation"] == "delete":
        validate_deletion(document)
    return document


def validate_project(document):
    target, config = document["target"], document["config"]
    section = "dev" if target["environment"] == "dev" else "stage_prod"
    values = config.get(section)
    require(isinstance(values, dict), "exact-config-environment-required")
    subscription_key = {"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}[target["environment"]]
    expected = {"tenantId": target["tenant_id"], subscription_key: target["subscription_id"],
                "project_number_000": target["project_ids"][0], "admin_location": target["region"],
                "admin_aifactoryPrefixRG": target["prefix"], "admin_aifactorySuffixRG": "-" + target["suffix"]}
    for key, value in expected.items():
        actual = str(values.get(key, ""))
        if key in ("tenantId", subscription_key):
            actual, value = actual.lower(), value.lower()
        require(actual == value, "config-target-mismatch-" + key)
    require(str(config.get("dev", {}).get("project_number_000", "")) == target["project_ids"][0],
            "config-dev-project-identity-mismatch")
    require(not any(str(values.get(key, "")).lower() in ("true", "1", "yes") for key in (
        "deleteAllForProject", "deleteAllServicesForProject", "enableDeleteForDisabledResources",
    )), "deletion-config-forbidden")


def validate_deployment_plan(document):
    plan, target, route = document["deployment"], document["target"], document["route"]
    require(isinstance(plan, dict) and plan.get("contract") == 1
            and plan.get("configuration_hash") == digest(document["config"]), "frozen-deployment-plan-required")
    require(guid(document["identity"].get("deployment_object_id")), "bound-deployment-principal-required")
    require(route.get("scoped_contract") == 1 and isinstance(route.get("auth_namespace"), str)
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", route["auth_namespace"]), "namespaced-route-required")
    runner = route.get("runner")
    require(isinstance(runner, dict) and runner.get("os") == "linux"
            and runner.get("kind") in ("hosted", "self-hosted"), "explicit-linux-scoped-runner-required")
    if runner["kind"] == "hosted":
        require(runner.get("image") in ("ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"), "unsupported-hosted-runner-image")
    elif route["kind"] == "gha":
        labels = runner.get("labels")
        require(isinstance(labels, list) and 2 <= len(labels) <= 16
                and all(isinstance(label, str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", label) for label in labels)
                and {"self-hosted", "linux"} <= {label.lower() for label in labels}, "explicit-self-hosted-labels-required")
    else:
        require(isinstance(runner.get("pool"), str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", runner["pool"]),
                "explicit-ado-agent-pool-required")
        require(isinstance(runner.get("agent_name", ""), str)
                and re.fullmatch(r"[A-Za-z0-9_. -]{0,128}", runner.get("agent_name", "")), "invalid-ado-agent-name")
    config = document["config"]
    section = "dev" if target["environment"] == "dev" else "stage_prod"
    values = config
    if "dev" in config or "stage_prod" in config:
        require(isinstance(config.get(section), dict), "exact-config-environment-required")
        values = config[section]
    if "useSelfHostedBuildAgent" in values:
        require(str(values["useSelfHostedBuildAgent"]).lower() in ("true", "false")
                and (str(values["useSelfHostedBuildAgent"]).lower() == "true") == (runner["kind"] == "self-hosted"),
                "runner-selection-conflicts-with-frozen-config")
    if runner["kind"] == "self-hosted":
        if route["kind"] == "gha" and values.get("selfHostedRunnerLabel"):
            require(str(values["selfHostedRunnerLabel"]) in runner["labels"], "runner-label-conflicts-with-config")
        elif route["kind"] == "ado":
            for key, field in (("adminVMBuildAgentPool", "pool"), ("adminVMBuildAgentName", "agent_name")):
                require(not values.get(key) or str(values[key]) == runner.get(field), "ado-runner-conflicts-with-config")
    if document["operation"] in ("create-factory", "create-scaleset") and "BYO_subnets" in values:
        require(str(values["BYO_subnets"]).lower() in ("true", "false")
                and (str(values["BYO_subnets"]).lower() == "true") == (plan.get("network_mode") == "byo"),
                "network-mode-conflicts-with-frozen-config")
    require(isinstance(plan.get("steps"), list) and plan["steps"], "nonempty-deployment-plan-required")
    require(isinstance(plan.get("changes"), list) and plan["changes"], "combined-plan-what-if-required")
    known = plan.get("known_ownership", {})
    require(isinstance(known, dict) and all(
        isinstance(key, str) and key == key.lower() and NESTED_ID.fullmatch(key)
        and isinstance(value, dict) and guid(value.get("run_id")) and hash_value(value.get("receipt_hash"))
        for key, value in known.items()), "invalid-known-ownership-evidence")
    steps, projects, common, seen = plan["steps"], set(), set(), set()
    allowed_scopes = {value.lower() for value in document["locks"]["scopes"]}
    for step in steps:
        require(isinstance(step, dict) and isinstance(step.get("id"), str)
                and re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", step["id"]) and step["id"] not in seen
                and step["id"] != "factory",
                "unique-deployment-step-required")
        dependencies = step.get("depends_on")
        require(isinstance(dependencies, list) and all(value in seen for value in dependencies),
                "deployment-dependencies-not-ordered")
        seen.add(step["id"])
        template, kind = step.get("template"), step.get("kind")
        require((kind == "common" and template in COMMON_TEMPLATES.values())
                or (kind == "project" and template in PROJECT_TEMPLATES), "canonical-deployment-template-required")
        require(hash_value(step.get("template_hash")) and isinstance(step.get("parameters"), dict),
                "frozen-template-parameters-required")
        parameters = step["parameters"]
        require(all(isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in parameters),
                "invalid-arm-parameter-name")
        expected = {"env": "test" if target["environment"] == "stage" else target["environment"],
                    "location": target["region"], "commonRGNamePrefix": target["prefix"],
                    "aifactorySuffixRG": "-" + target["suffix"]}
        require(all(parameters.get(key) == value for key, value in expected.items()), "arm-plan-target-mismatch")
        require("tenantId" not in parameters or str(parameters["tenantId"]).lower() == target["tenant_id"].lower(),
                "arm-plan-tenant-mismatch")
        require(step.get("scope") in ("subscription", "resource-group"), "deployment-scope-required")
        if step["scope"] == "resource-group":
            require(str(step.get("resource_group", "")).lower() in allowed_scopes, "deployment-resource-group-not-locked")
        require(isinstance(step.get("resource_groups"), list) and step["resource_groups"]
                and {scope.lower() for scope in step["resource_groups"]} <= allowed_scopes,
                "deployment-write-scopes-not-locked")
        tag_parameter = ("tagsProject" if template.endswith("/09-ai-foundry-2025-v4.bicep") else "tags")
        tags = parameters.get(tag_parameter)
        if template.endswith("/08b-rbac-common-rg.bicep"):
            owner = step.get("owner", {})
            tags = {TAG_KEYS[key]: value for key, value in owner.items() if key in TAG_KEYS}
        require(isinstance(tags, dict) and all(tags.get(TAG_KEYS[key]) == target[key]
                                              for key in ("factory_id", "scaleset_id")), "deployment-ownership-tags-required")
        if kind == "project":
            project = step.get("project_id")
            require(project in target["project_ids"] and parameters.get("projectNumber") == project
                    and tags.get(TAG_KEYS["project_id"]) == project, "deployment-project-identity-mismatch")
            projects.add(project)
        else:
            require("project_id" not in step and "projectNumber" not in parameters
                    and TAG_KEYS["project_id"] not in tags, "common-only-project-leak")
            common.add(template)
        require("changes" not in step or isinstance(step["changes"], list), "invalid-step-what-if")
        ids = set()
        for change in step.get("changes", []):
            require(isinstance(change, dict) and isinstance(change.get("resource_id"), str),
                    "invalid-reviewed-arm-change")
            resource_id = change["resource_id"].lower()
            require(resource_id not in ids and arm_scope(resource_id) in {
                scope.lower() for scope in step["resource_groups"]}, "arm-change-outside-reviewed-scopes")
            require(change.get("change_type") in ("Create", "Modify", "NoChange"),
                    "destructive-or-unknown-arm-change")
            ids.add(resource_id)
    require(projects == set(target["project_ids"]), "selected-project-plan-incomplete")
    if document["operation"] in ("create-factory", "create-scaleset"):
        required = {COMMON_TEMPLATES["11-rgCommon"], COMMON_TEMPLATES["13-rgLevel"]}
        require(plan.get("network_mode") in ("managed", "byo"), "explicit-network-mode-required")
        if plan["network_mode"] == "managed":
            required.add(COMMON_TEMPLATES["12-networkCommon"])
        require(required <= common, "common-foundation-plan-incomplete")
    else:
        require(document["operation"] == "deploy-project" and not common, "unexpected-common-deployment")
    combined_ids = set()
    for change in plan["changes"]:
        require(isinstance(change, dict) and isinstance(change.get("resource_id"), str)
                and arm_scope(change["resource_id"]) in allowed_scopes
                and change.get("change_type") in ("Create", "Modify", "NoChange"),
                "combined-plan-change-outside-scope")
        require(change["resource_id"].lower() not in combined_ids, "duplicate-combined-plan-change")
        combined_ids.add(change["resource_id"].lower())


def validate_deletion(document):
    data = document.get("deletion")
    require(isinstance(data, dict) and data.get("inventory_complete") is True, "complete-inventory-required")
    require(data.get("revision") == document["manifest_revision"], "inventory-revision-mismatch")
    resources, groups = data.get("resources"), data.get("resource_groups")
    require(isinstance(resources, list) and isinstance(groups, list) and groups, "inventory-resources-required")
    require(all(isinstance(item, dict) for item in groups + resources), "invalid-inventory-entry")
    full = data.get("inventory_mode") == "arm-provider-closure-v1"
    require(any(item.get("delete") is True for item in groups + resources), "nonempty-delete-allowlist-required")
    require(data.get("inventory_hash") == digest(resources), "inventory-hash-mismatch")
    scopes = {item.lower() for item in document["locks"]["scopes"]}
    require({str(item.get("id", "")).lower() for item in groups} == scopes, "inventory-scope-mismatch")
    ids = set()
    target = document["target"]
    for item in groups + resources:
        require(isinstance(item, dict) and isinstance(item.get("id"), str), "invalid-inventory-entry")
        resource_id = item["id"].lower()
        require(resource_id not in ids, "duplicate-inventory-resource")
        ids.add(resource_id)
        require(arm_scope(resource_id) in scopes and type(item.get("delete")) is bool,
                "resource-outside-approved-scope")
        require((item.get("etag") is None or isinstance(item["etag"], str) and item["etag"])
                and hash_value(item.get("body_hash")),
                "resource-fingerprint-required")
    for group in groups:
        require(RG_ID.fullmatch(group["id"]), "invalid-resource-group-id")
        require(not group["delete"] or full, "resource-group-extension-inventory-collector-required")
        if group["delete"]:
            require(group.get("owner") == {key: target[key] for key in ("factory_id", "scaleset_id")},
                    "owned-resource-group-required")
    for resource in resources:
        match = (NESTED_ID if full else RESOURCE_ID).fullmatch(resource["id"])
        require(match is not None, "unsupported-nested-resource")
        resource_type = str(resource.get("type", "")).lower()
        require(resource_type == resource_type_from_id(resource["id"]).lower(), "resource-type-mismatch")
        require(full or resource_type in LEAF_TYPES and resource.get("api_version") == LEAF_TYPES[resource_type],
                "unsupported-resource-inventory-collector")
        require(isinstance(resource.get("api_version"), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", resource["api_version"]), "invalid-resource-api-version")
        owner = resource.get("owner")
        require(isinstance(owner, dict) and owner.get("factory_id") == target["factory_id"]
                and owner.get("scaleset_id") == target["scaleset_id"], "unknown-resource-ownership")
        require(not owner.get("project_id") or owner["project_id"] in target["project_ids"],
                "project-ownership-mismatch")
        depends = resource.get("depends_on")
        require(isinstance(depends, list) and all(isinstance(value, str) for value in depends),
                "explicit-dependencies-required")
    deleted_ids = {item["id"].lower() for item in resources if item["delete"]}
    external_scopes = {scope.lower() for scope in document["locks"]["common_dependencies"]}
    for item in resources:
        require(all((value.lower() in ids or arm_scope(value) in external_scopes)
                    and value.lower() != item["id"].lower() for value in item["depends_on"]),
                "unknown-resource-dependency")
        require(item["delete"] or not any(value.lower() in deleted_ids for value in item["depends_on"]),
                "retained-resource-depends-on-deletion")
    for group in groups:
        if group["delete"]:
            require(all(item["delete"] for item in resources if arm_scope(item["id"]) == group["id"].lower()),
                    "cannot-delete-shared-resource-group")
    if full:
        require(isinstance(data.get("closure"), dict) and hash_value(data.get("closure_hash"))
                and digest(data["closure"]) == data["closure_hash"], "complete-provider-closure-required")
    if not full:
        deletion_order(resources)


def resource_type_from_id(resource_id):
    relative = resource_id.lower().rsplit("/providers/", 1)[-1]
    parts = relative.split("/")
    return parts[0] + "/" + "/".join(parts[1::2])


def deletion_order(resources):
    remaining = {item["id"].lower(): item for item in resources if item["delete"]}
    ordered = []
    while remaining:
        referenced = {dependency.lower() for item in remaining.values() for dependency in item["depends_on"]}
        ready = sorted(set(remaining) - referenced)
        require(ready, "cyclic-deletion-dependencies")
        for resource_id in ready:
            ordered.append(remaining.pop(resource_id))
    return ordered


def capabilities():
    return {
        "contract": CONTRACT, "manifest_schema": CONTRACT,
        "protected_inputs": ["stdin", "windows-current-user-dpapi"],
        "local_preview": True, "distributed_lock": "azure-blob-infinite-lease-v1",
        "project_routes": ["ado", "gha"],
        "project_environments": ["dev", "stage", "prod"],
        "scoped_worker_os": ["linux"], "scoped_runners": ["hosted", "self-hosted"],
        "scoped_group_ownership_receipt": "resource-group-ownership-v1",
        "delete_leaf_types": sorted(LEAF_TYPES), "delete_empty_owned_resource_groups": True,
        "delete_owned_resource_groups": "arm-provider-closure-v1",
        "factory_cohort": "physical-lease-cohort-v1",
        "creation": "frozen-arm-deployment-plan-v1", "shared_remote_namespaced_auth": True,
        "blockers": {
            "legacy_creation": "A frozen complete ARM deployment plan and published scoped template are required.",
            "legacy_gha": "The published scoped GHA workflow is required; legacy workflow_dispatch is not used.",
            "incomplete_deletions": "Complete provider/child/extension closure and known ownership are required.",
        },
    }


def operation_blockers(document):
    reasons = []
    scoped = "deployment" in document
    if document["operation"] in ("create-factory", "create-scaleset") and not scoped:
        reasons.append("frozen-scoped-deployment-plan-required")
    if document["operation"] == "deploy-project" and document["route"]["kind"] == "gha" and not scoped:
        reasons.append("published-scoped-github-template-required")
    if document["route"]["shared_remote"] and document["operation"] != "delete" and not scoped:
        reasons.append("published-namespaced-auth-contract-required")
    return reasons


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Cloud:
    """No shell expansion, CLI output passthrough, interactive auth or retries."""

    def __init__(self, document, command_runner=None, opener=None, expected_object_id=None):
        self.document = document
        self.runner = command_runner or subprocess.run
        self.opener = opener or build_opener(NoRedirect)
        self.tokens = {}
        self.token_expiries = {}
        self.expected_object_id = expected_object_id or document["identity"]["object_id"]
        self.pipeline_identity = expected_object_id is not None
        self.workload_client_id = None

    def command(self, argv, cwd=None, data=None):
        command = list(argv)
        if command[0] == "git":
            executable = shutil.which("git")
            if not executable and sys.platform == "win32":
                executable = r"C:\Program Files\Git\cmd\git.exe"
            require(executable and Path(executable).is_file(), "git-unavailable")
            command[0] = executable
        if command[0] == "az" and sys.platform == "win32":
            launcher = shutil.which("az.cmd") or shutil.which("az")
            require(launcher is not None, "azure-cli-unavailable")
            path = Path(launcher)
            if path.suffix.lower() in (".cmd", ".bat"):
                python = path.parent.parent / "python.exe"
                require(python.is_file(), "azure-cli-safe-launcher-unavailable")
                command = [str(python), "-IBm", "azure.cli", *command[1:]]
            else:
                command[0] = str(path)
        if command[0] == "gh" and sys.platform == "win32":
            executable = shutil.which("gh.exe")
            require(executable is not None, "github-cli-safe-launcher-unavailable")
            command[0] = executable
        try:
            result = self.runner(command, cwd=cwd, input=data, shell=False, text=True, encoding="utf-8",
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        except (OSError, subprocess.SubprocessError):
            raise Blocked("command-unavailable-or-timed-out") from None
        require(result.returncode == 0, "command-failed")
        require(len(result.stdout.encode("utf-8")) <= MAX_DOCUMENT, "command-response-too-large")
        return result.stdout.strip()

    def token(self, audience):
        if self.token_expiries.get(audience, 0) <= time.time() + 60:
            self.tokens.pop(audience, None)
        if audience not in self.tokens:
            target = self.document["target"]
            if self.pipeline_identity and self.document["route"]["kind"] == "gha":
                value = {"accessToken": self.github_workload_token(audience)}
            else:
                raw = self.command(["az", "account", "get-access-token", "--resource", audience,
                                    "--subscription", target["subscription_id"], "--output", "json"])
                value = json.loads(raw)
            try:
                token = value["accessToken"]
                payload = token.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                require(str(claims.get("tid", "")).lower() == target["tenant_id"].lower()
                        and str(claims.get("oid", "")).lower() == self.expected_object_id.lower(),
                        "authenticated-identity-mismatch")
                require(float(claims.get("exp", 0)) > time.time() + 60, "authentication-expiring")
            except Blocked:
                raise
            except (KeyError, ValueError, IndexError, TypeError):
                raise Blocked("invalid-authentication-response") from None
            self.tokens[audience] = token
            self.token_expiries[audience] = float(claims["exp"])
        return self.tokens[audience]

    def identity_json(self, request):
        try:
            with self.opener.open(request, timeout=60) as response:
                require(response.code == 200, "workload-identity-request-failed")
                raw = response.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, "workload-identity-response-too-large")
            value = json.loads(raw)
            require(isinstance(value, dict), "invalid-workload-identity-response")
            return value
        except (HTTPError, URLError, OSError, ValueError):
            raise Blocked("workload-identity-request-unverified") from None

    def github_workload_token(self, audience):
        """Renew this exact CI identity without putting an assertion in argv."""
        require(guid(self.workload_client_id), "pipeline-client-binding-missing")
        url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
        credential = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
        parsed = urlsplit(url)
        require(os.environ.get("GITHUB_ACTIONS") == "true" and credential and parsed.scheme == "https"
                and parsed.hostname and parsed.hostname.endswith(".actions.githubusercontent.com")
                and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment,
                "trusted-github-oidc-context-required")
        query = parse_qs(parsed.query)
        requested_audience = "api://AzureADTokenExchange"
        require("audience" not in query or query["audience"] == [requested_audience], "github-oidc-audience-mismatch")
        if "audience" not in query:
            url += ("&" if parsed.query else "?") + "audience=" + quote(requested_audience, safe="")
        assertion = self.identity_json(Request(url, headers={"Authorization": "Bearer " + credential})).get("value", "")
        require(isinstance(assertion, str) and len(assertion.split(".")) == 3, "invalid-github-oidc-assertion")
        try:
            raw = assertion.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        except (ValueError, IndexError, TypeError):
            raise Blocked("invalid-github-oidc-assertion") from None
        route = self.document["route"]
        repository = urlsplit(route["repository"]).path.strip("/").removesuffix(".git")
        require(claims.get("iss") == "https://token.actions.githubusercontent.com"
                and claims.get("aud") == requested_audience and claims.get("repository") == repository
                and claims.get("sha") == route["commit"]
                and claims.get("ref") == "refs/tags/aifactory-runs/" + self.document["run_id"]
                and claims.get("environment") == route["auth_namespace"]
                and isinstance(claims.get("sub"), str) and claims["sub"]
                and str(claims.get("run_id", "")) == os.environ.get("GITHUB_RUN_ID"),
                "github-workload-identity-binding-mismatch")
        target = self.document["target"]
        body = urlencode({"client_id": self.workload_client_id, "scope": audience.rstrip("/") + "/.default",
                          "client_assertion": assertion, "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                          "grant_type": "client_credentials"}).encode("utf-8")
        response = self.identity_json(Request(
            "https://login.microsoftonline.com/" + target["tenant_id"] + "/oauth2/v2.0/token", method="POST", data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}))
        require(isinstance(response.get("access_token"), str), "workload-access-token-missing")
        return response["access_token"]

    def verify_identity(self, require_default=False):
        target = self.document["target"]
        argv = ["az", "account", "show"]
        if not require_default:
            argv += ["--subscription", target["subscription_id"]]
        account = json.loads(self.command([*argv, "--output", "json"]))
        require(str(account.get("id", "")).lower() == target["subscription_id"].lower()
                and str(account.get("tenantId", "")).lower() == target["tenant_id"].lower(),
                "authenticated-scope-mismatch")
        require(account.get("environmentName") == "AzureCloud", "public-azure-cloud-required")
        if self.pipeline_identity and self.document["route"]["kind"] == "gha":
            user = account.get("user") or {}
            require(user.get("type") == "servicePrincipal" and guid(user.get("name")),
                    "github-pipeline-principal-required")
            self.workload_client_id = user["name"]
        self.tokens.clear()
        self.token_expiries.clear()
        self.token(ARM)

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        parsed = urlsplit(url)
        allowed_hosts = {urlsplit(ARM).netloc, urlsplit(self.document["locks"]["account_url"]).netloc, "dev.azure.com"}
        require(parsed.scheme == "https" and parsed.netloc in allowed_hosts and not parsed.username
                and not parsed.password and not parsed.fragment, "untrusted-service-endpoint")
        request_headers = {"Authorization": "Bearer " + self.token(audience), "Content-Type": "application/json"}
        request_headers.update(headers or {})
        body = canonical(data) if data is not None else None
        request = Request(url, method=method, data=body, headers=request_headers)
        try:
            response = self.opener.open(request, timeout=60)
        except HTTPError as error:
            if error.code not in allowed:
                raise Blocked("remote-request-failed-" + str(error.code)) from None
            response = error
        except (URLError, OSError, TimeoutError):
            raise Blocked("remote-request-unverified") from None
        with response:
            status, response_headers = response.code, dict(response.headers)
            raw = response.read(MAX_DOCUMENT + 1)
        require(status in allowed, "unexpected-remote-status")
        require(len(raw) <= MAX_DOCUMENT, "remote-response-too-large")
        if not raw:
            return status, response_headers, None
        try:
            return status, response_headers, json.loads(raw)
        except ValueError:
            raise Blocked("invalid-remote-json") from None

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        arm_scope(resource_id)
        return self.request(method, ARM + quote(resource_id, safe="/().-_") + "?api-version=" + api_version,
                            ARM, allowed=allowed, headers=headers)

    def list_resources(self, scope):
        url = ARM + quote(scope, safe="/().-_") + "/resources?api-version=" + RG_API
        rows, visited = [], set()
        while url:
            require(url not in visited and len(visited) < 100, "incomplete-or-cyclic-inventory")
            require(url.startswith(ARM + "/subscriptions/") and arm_scope(urlsplit(url).path) == scope.lower(),
                    "inventory-pagination-scope-mismatch")
            visited.add(url)
            _, _, page = self.request("GET", url, ARM)
            require(isinstance(page, dict) and isinstance(page.get("value"), list), "incomplete-inventory")
            rows.extend(page["value"])
            require(len(rows) <= 10000, "inventory-too-large")
            url = page.get("nextLink")
        return rows

    def assert_no_active_deployments(self, scope):
        url = ARM + quote(scope, safe="/().-_") + "/providers/Microsoft.Resources/deployments?api-version=2022-09-01"
        visited = set()
        while url:
            require(url not in visited and len(visited) < 100, "incomplete-deployment-inventory")
            require(url.startswith(ARM + "/subscriptions/") and arm_scope(urlsplit(url).path) == scope.lower(),
                    "deployment-pagination-scope-mismatch")
            visited.add(url)
            _, _, page = self.request("GET", url, ARM)
            require(isinstance(page, dict) and isinstance(page.get("value"), list), "incomplete-deployment-inventory")
            require(all((row.get("properties") or {}).get("provisioningState") in (
                "Succeeded", "Failed", "Canceled") for row in page["value"]), "active-or-unknown-deployment")
            url = page.get("nextLink")

    def assert_no_active_runs(self, enrollment):
        scopes = self.document["locks"]["scopes"] + self.document["locks"]["common_dependencies"]
        writers = {writer for scope in scopes for writer in enrollment["scopes"][scope.lower()]["writers"]}
        for writer_id in sorted(writers):
            writer = enrollment["writers"].get(writer_id)
            require(isinstance(writer, dict), "dependency-writer-not-enrolled")
            repository = writer.get("repository", "")
            parsed = urlsplit(repository)
            require(not parsed.query and not parsed.fragment and not parsed.username and not parsed.password
                    and parsed.scheme == "https", "invalid-enrolled-repository")
            if writer.get("kind") == "gha":
                require(parsed.netloc == "github.com" and re.fullmatch(
                    r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", parsed.path), "invalid-enrolled-repository")
                name = parsed.path.strip("/").removesuffix(".git")
                for status in ("queued", "in_progress", "waiting", "pending", "requested"):
                    page = json.loads(self.command([
                        "gh", "api", "repos/" + name + "/actions/runs?per_page=1&status=" + status,
                        "--hostname", "github.com",
                    ]))
                    require(isinstance(page, dict) and isinstance(page.get("workflow_runs"), list)
                            and type(page.get("total_count")) is int, "incomplete-remote-run-inventory")
                    require(page["total_count"] == 0 and not page["workflow_runs"], "active-or-queued-remote-run")
            elif writer.get("kind") == "ado":
                path = unquote(parsed.path)
                require(parsed.netloc == "dev.azure.com" and re.fullmatch(
                    r"/[A-Za-z0-9_. -]+/[A-Za-z0-9_. -]+/_git/[A-Za-z0-9_. -]+", path),
                    "invalid-enrolled-repository")
                organization, project, _, name = path.strip("/").split("/")
                api = "https://dev.azure.com/" + quote(organization, safe="") + "/" + quote(project, safe="") + "/_apis"
                audience = "https://app.vssps.visualstudio.com/"
                _, _, repo = self.request("GET", api + "/git/repositories/" + quote(name, safe="") + "?api-version=7.1",
                                          audience)
                require(isinstance(repo, dict) and guid(repo.get("id")), "invalid-enrolled-repository-id")
                _, _, page = self.request("GET", api + "/build/builds?repositoryId=" + repo["id"]
                                          + "&repositoryType=TfsGit&statusFilter=inProgress,notStarted,cancelling,postponed"
                                          + "&%24top=1&api-version=7.1", audience)
                require(isinstance(page, dict) and isinstance(page.get("value"), list)
                        and type(page.get("count")) is int, "incomplete-remote-run-inventory")
                require(page["count"] == 0 and not page["value"], "active-or-queued-remote-run")
            else:
                raise Blocked("unsupported-enrolled-writer")

    def provider_schema(self, namespace):
        subscription = self.document["target"]["subscription_id"]
        _, _, body = self.request("GET", ARM + "/subscriptions/" + subscription + "/providers/"
                                  + quote(namespace, safe=".") + "?api-version=2021-04-01", ARM)
        require(isinstance(body, dict) and isinstance(body.get("resourceTypes"), list),
                "incomplete-provider-schema")
        return body

    def collection(self, path, api_version, *, extension=False):
        url = ARM + quote(path, safe="/().-_") + "?api-version=" + api_version
        if "/microsoft.authorization/" in path.lower():
            url += "&%24filter=atScope()"
        values, seen = [], set()
        while url:
            require(url not in seen and len(seen) < 100 and url.startswith(ARM + "/")
                    and arm_scope(urlsplit(url).path) == arm_scope(path), "incomplete-child-inventory")
            seen.add(url)
            status, _, body = self.request("GET", url, ARM, allowed=(200, 400, 404, 405))
            if status != 200:
                code = (body or {}).get("error", {}).get("code")
                require(extension and code in UNSUPPORTED_COLLECTION_CODES, "unsupported-child-inventory-endpoint")
                return [], code
            require(isinstance(body, dict) and isinstance(body.get("value"), list),
                    "incomplete-child-inventory")
            for row in body["value"]:
                require(isinstance(row, dict) and isinstance(row.get("id"), str), "invalid-child-inventory")
                # atScope() can include inherited assignments; they are not
                # children and must never become deletion authorization.
                if row["id"].lower().startswith(path.lower().rstrip("/") + "/"):
                    values.append(row)
                else:
                    require(extension and "/microsoft.authorization/" in path.lower(),
                            "child-inventory-escaped-scope")
            require(len(values) <= 10000, "child-inventory-too-large")
            url = body.get("nextLink")
        require(len({row["id"].lower() for row in values}) == len(values), "duplicate-child-inventory")
        return sorted(values, key=lambda row: row["id"].lower()), None

    def compile_template(self, source_root, relative):
        path = clean_path(source_root / Path(relative))
        require(path.is_relative_to(source_root) and path.is_file(), "canonical-template-unavailable")
        template = json.loads(self.command(["az", "bicep", "build", "--file", str(path), "--stdout"], cwd=str(source_root)))
        require(isinstance(template, dict) and isinstance(template.get("parameters"), dict), "invalid-compiled-template")
        return template


def collect_resource_closure(cloud, scopes):
    """Complete registered child-resource closure, including scoped extensions.

    Unsupported list endpoints fail closed. Known inline ARM child operations
    are covered by the full parent body fingerprint, not invented resources.
    """
    schemas, versions, bodies = {}, {}, {}
    closure = {"providers": {}, "collections": {}, "resources": {}, "groups": {}}
    singleton = {
        "microsoft.storage/storageaccounts/blobservices": "default",
        "microsoft.storage/storageaccounts/fileservices": "default",
        "microsoft.storage/storageaccounts/queueservices": "default",
        "microsoft.storage/storageaccounts/tableservices": "default",
        "microsoft.storage/storageaccounts/managementpolicies": "default",
    }
    inline = {"microsoft.keyvault/vaults/accesspolicies"}
    terminal_extensions = {kind.lower() for kind, _ in EXTENSION_COLLECTIONS}

    def provider(namespace):
        key = namespace.lower()
        if key not in schemas:
            body = cloud.provider_schema(namespace)
            entries = {}
            for row in body["resourceTypes"]:
                require(isinstance(row, dict) and isinstance(row.get("resourceType"), str)
                        and isinstance(row.get("apiVersions"), list), "incomplete-provider-schema")
                entries[row["resourceType"].lower()] = row["apiVersions"]
            schemas[key] = entries
            closure["providers"][key] = digest(body)
        return schemas[key]

    def version(kind):
        namespace, relative = kind.split("/", 1)
        available = provider(namespace).get(relative.lower(), [])
        stable = sorted((value for value in available if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), reverse=True)
        fallback = sorted((value for value in available if re.fullmatch(r"\d{4}-\d{2}-\d{2}-preview", value)), reverse=True)
        require(stable or fallback, "resource-api-version-not-discoverable")
        return (stable or fallback)[0]

    queue = []

    def add_collection(path, api, extension=False, single=None):
        if single:
            status, headers, body = cloud.arm("GET", path + "/" + single, api, allowed=(200, 404))
            rows, unsupported = ([] if status == 404 else [body]), None
        else:
            rows, unsupported = cloud.collection(path, api, extension=extension)
        entry = {"api_version": api, "ids": sorted(row["id"].lower() for row in rows),
                 "body_hash": digest(rows), "unsupported": unsupported}
        closure["collections"][path.lower()] = entry
        for row in rows:
            resource_id = row["id"].lower()
            if resource_id not in versions:
                versions[resource_id] = api
                queue.append(row["id"])

    def extensions(scope):
        for kind, api in EXTENSION_COLLECTIONS:
            if RG_ID.fullmatch(scope) and kind == "Microsoft.Insights/diagnosticSettings":
                closure["collections"][(scope + "/providers/" + kind).lower()] = {
                    "not_applicable": "resource-group-activity-logs-are-subscription-scoped"}
                continue
            add_collection(scope + "/providers/" + kind, api, extension=True)

    for scope in sorted(scopes, key=str.lower):
        _, headers, body = cloud.arm("GET", scope, RG_API)
        bodies[scope.lower()] = body
        closure["groups"][scope.lower()] = {"body_hash": digest(body), "etag": body.get("etag") or
                                            next((v for k, v in headers.items() if k.lower() == "etag"), None)}
        roots = cloud.list_resources(scope)
        closure["collections"][scope.lower() + "/resources"] = {
            "api_version": RG_API, "ids": sorted(row["id"].lower() for row in roots),
            "body_hash": digest(sorted(roots, key=lambda row: row["id"].lower())), "unsupported": None}
        for row in roots:
            resource_id = row["id"]
            require(arm_scope(resource_id) == scope.lower(), "inventory-escaped-resource-group")
            api = version(resource_type_from_id(resource_id))
            if resource_id.lower() not in versions:
                versions[resource_id.lower()] = api
                queue.append(resource_id)
        extensions(scope)
    visited = set()
    while queue:
        resource_id = queue.pop(0)
        key = resource_id.lower()
        if key in visited:
            continue
        require(len(visited) < 10000, "resource-closure-too-large")
        visited.add(key)
        kind, api = resource_type_from_id(resource_id), versions[key]
        _, headers, body = cloud.arm("GET", resource_id, api)
        require(isinstance(body, dict) and body.get("id", "").lower() == key, "resource-closure-identity-mismatch")
        bodies[key] = body
        closure["resources"][key] = {"type": kind, "api_version": api, "body_hash": digest(body),
                                    "etag": body.get("etag") or next((v for k, v in headers.items() if k.lower() == "etag"), None)}
        if kind in terminal_extensions:
            continue
        namespace, relative = kind.split("/", 1)
        for child in sorted(provider(namespace)):
            tail = child.removeprefix(relative + "/")
            if not child.startswith(relative + "/") or "/" in tail:
                continue
            full_type = namespace + "/" + child
            if full_type in inline:
                closure["collections"][key + "/" + tail] = {"inline_parent_hash": digest(body)}
            else:
                add_collection(resource_id + "/" + tail, version(full_type), single=singleton.get(full_type))
        extensions(resource_id)
    return closure, bodies


def cross_group_references(body, own_scope):
    result = set()

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.lower().startswith("/subscriptions/"):
            try:
                if arm_scope(value) != own_scope:
                    result.add(value.lower())
            except Blocked:
                pass

    visit(body)
    return result


def managed_group_cascades(body, subscription):
    groups = set()
    keys = {"managedresourcegroupid", "managedresourcegroupname", "managedresourcegroup", "noderesourcegroup"}

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in keys and isinstance(item, str) and item:
                    scope = item if item.lower().startswith("/subscriptions/") else (
                        "/subscriptions/" + subscription + "/resourceGroups/" + item)
                    require(RG_ID.fullmatch(scope), "unknown-managed-group-cascade")
                    groups.add(scope.lower())
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(body)
    return groups


def verify_group_ownership(body, owner, bodies):
    tags = body.get("tags") or {}
    if any(TAG_KEYS[key] in tags for key in ("factory_id", "scaleset_id")):
        verify_ownership(body, owner)
        return None
    parent_id = str(body.get("managedBy", "")).lower()
    require(NESTED_ID.fullmatch(parent_id) and resource_type_from_id(parent_id) in MANAGED_GROUP_PARENT_TYPES
            and parent_id in bodies, "owned-resource-group-marker-required")
    parent = bodies[parent_id]
    require(str(body.get("id", "")).lower() in managed_group_cascades(parent, arm_scope(parent_id).split("/")[2]),
            "managed-group-parent-link-unverified")
    verify_ownership(parent, owner)
    return parent_id


def inherited_new_resource_owner(resource_id, bodies):
    parent = resource_id
    while "/" in parent:
        parent = parent.rsplit("/", 1)[0]
        body = bodies.get(parent, {})
        tags = body.get("tags") or {}
        owner = {key: tags[TAG_KEYS[key]] for key in TAG_KEYS if TAG_KEYS[key] in tags}
        if owner:
            return owner
        if RG_ID.fullmatch(parent) and body.get("managedBy"):
            manager = bodies.get(str(body["managedBy"]).lower(), {})
            tags = manager.get("tags") or {}
            owner = {key: tags[TAG_KEYS[key]] for key in TAG_KEYS if TAG_KEYS[key] in tags}
            if owner:
                verify_group_ownership(body, {key: owner[key] for key in ("factory_id", "scaleset_id") if key in owner}, bodies)
                return owner
    return {}


def freeze_deletion_inventory(cloud, document, ownership_records):
    """Read-only exact RG inventory builder; untaggable owners need real receipts."""
    cloud.verify_identity()
    BlobLocks(cloud, document).verify_enrollment()
    scopes = document["locks"]["scopes"]
    closure, bodies = collect_resource_closure(cloud, scopes)
    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    groups, resources = [], []
    for scope in scopes:
        manager = verify_group_ownership(bodies[scope.lower()], owner, bodies)
        entry = {"id": scope, **closure["groups"][scope.lower()], "delete": True, "owner": owner}
        if manager:
            entry.update(ownership_source="managed-parent", managed_parent_id=manager)
        groups.append(entry)
    for resource_id, metadata in closure["resources"].items():
        body = bodies[resource_id]
        tags = body.get("tags") or {}
        tagged = {key: tags[TAG_KEYS[key]] for key in TAG_KEYS if TAG_KEYS[key] in tags}
        if tagged:
            item = {"owner": tagged, "ownership_source": "tags"}
        else:
            item = dict(ownership_records.get(resource_id, {}))
            require(item.get("ownership_source") == "deployment-receipt" and item.get("ownership_evidence"),
                    "known-child-ownership-record-required")
        resources.append({**item, "id": resource_id, **metadata, "delete": True,
                          "depends_on": sorted(cross_group_references(body, arm_scope(resource_id)))})
    result = {"inventory_mode": "arm-provider-closure-v1", "inventory_complete": True,
              "revision": document["manifest_revision"], "resource_groups": groups, "resources": resources,
              "inventory_hash": digest(resources), "closure": closure, "closure_hash": digest(closure)}
    draft = {**document, "deletion": result}
    validate_deletion(draft)
    verify_full_inventory(cloud, draft)
    return result


def verified_receipt_owner(locks, evidence, resource_id, body_hash, cache):
    require(isinstance(evidence, dict) and guid(evidence.get("run_id"))
            and hash_value(evidence.get("receipt_hash")), "child-ownership-evidence-required")
    cache_key = (evidence["run_id"], evidence["receipt_hash"])
    if cache_key not in cache:
        _, _, receipt = locks.request("GET", "runs/" + evidence["run_id"] + ".worker.json")
        require(isinstance(receipt, dict) and digest(receipt) == evidence["receipt_hash"]
                and receipt.get("schema") == 1 and receipt.get("run_id") == evidence["run_id"]
                and receipt.get("status") == "succeeded" and hash_value(receipt.get("manifest_hash")),
                "child-ownership-receipt-unverified")
        cache[cache_key] = receipt
    receipt = cache[cache_key]
    matches = [row for row in receipt.get("ownership", []) if row.get("resource_id", "").lower() == resource_id.lower()]
    require(len(matches) == 1 and matches[0].get("body_hash") == body_hash, "child-instance-ownership-unverified")
    owner = matches[0].get("owner")
    require(isinstance(owner, dict) and all(receipt.get("target", {}).get(key) == owner.get(key)
                                          for key in ("factory_id", "scaleset_id")),
            "child-receipt-target-mismatch")
    return owner


def verify_full_inventory(cloud, document, removed_groups=()):
    data = document["deletion"]
    removed = {scope.lower() for scope in removed_groups}
    groups = [group for group in data["resource_groups"] if group["id"].lower() not in removed]
    scopes = [group["id"] for group in groups]
    if not scopes:
        return {}
    cascades = {}
    closure, bodies = collect_resource_closure(cloud, scopes)
    expected = data["closure"]
    # Provider schemas are global to the subscription; retain only those still
    # required after an earlier approved resource group has been removed.
    for namespace, fingerprint in closure["providers"].items():
        require(expected["providers"].get(namespace) == fingerprint, "provider-schema-changed")
    for section in ("groups", "resources", "collections"):
        retained = {key: value for key, value in expected[section].items() if arm_scope(key) not in removed}
        require(closure[section] == retained, "complete-resource-closure-changed")
    expected_ids = {item["id"].lower() for item in data["resources"] if arm_scope(item["id"]) not in removed}
    require(set(closure["resources"]) == expected_ids, "unlisted-child-or-extension-resource")
    for group in groups:
        manager = verify_group_ownership(bodies[group["id"].lower()], group["owner"], bodies)
        require(not manager or group.get("ownership_source") == "managed-parent"
                and group.get("managed_parent_id") == manager, "managed-group-ownership-not-reviewed")
        cloud.assert_no_active_deployments(group["id"])
    resources = {item["id"].lower(): item for item in data["resources"]}
    receipt_cache = {}
    evidence_reader = BlobLocks(cloud, document)
    for key in expected_ids:
        item = resources[key]
        approved_groups = {group["id"].lower() for group in data["resource_groups"] if group["delete"]}
        managed = managed_group_cascades(bodies[key], document["target"]["subscription_id"])
        require(managed <= approved_groups,
                "implicit-managed-group-not-authorized")
        cascades.setdefault(arm_scope(key), set()).update(managed)
        provisioning = (bodies[key].get("properties") or {}).get("provisioningState")
        require(provisioning is None or provisioning in ("Succeeded", "Failed", "Canceled"),
                "active-or-unknown-resource-operation")
        require(cross_group_references(bodies[key], arm_scope(key)) <= {value.lower() for value in item["depends_on"]},
                "undeclared-cross-group-resource-dependency")
        verify_fingerprint(item, bodies[key], {"etag": closure["resources"][key]["etag"]})
        if item.get("ownership_source", "tags") == "tags":
            verify_ownership(bodies[key], item["owner"])
        else:
            require(item.get("ownership_source") == "deployment-receipt", "unknown-child-ownership-source")
            evidence = item.get("ownership_evidence", {})
            require(verified_receipt_owner(evidence_reader, evidence, key, item["body_hash"], receipt_cache) == item["owner"],
                    "child-not-owned-by-reviewed-deployment")
    return cascades


def delete_owned_groups(cloud, locks, document, receipt, persist, sleep=time.sleep):
    locks.authorize(document)
    require(all(group["delete"] for group in document["deletion"]["resource_groups"])
            and all(row["delete"] for row in document["deletion"]["resources"]), "whole-owned-groups-only")
    initial_cascades = verify_full_inventory(cloud, document)
    resources = document["deletion"]["resources"]
    groups = document["deletion"]["resource_groups"]
    planned = {group["id"].lower(): {"id": group["id"], "delete": True, "depends_on": []} for group in groups}
    for scope, managed in initial_cascades.items():
        planned[scope]["depends_on"].extend(sorted(managed - {scope}))
    for resource in resources:
        scope = arm_scope(resource["id"])
        for dependency in resource["depends_on"]:
            other = arm_scope(dependency)
            if other != scope and other in planned:
                planned[scope]["depends_on"].append(other)
    removed = []
    for group in deletion_order(list(planned.values())):
        if group["id"].lower() in {scope.lower() for scope in removed}:
            continue
        locks.authorize(document)
        locks.assert_held()
        cloud.verify_identity()
        cloud.assert_no_active_runs(locks.enrollment)
        cascades = verify_full_inventory(cloud, document, removed)
        locks.authorize(document)
        locks.assert_held()
        receipt["mutation_started"] = True
        receipt["pending_resource_group"] = group["id"]
        persist()
        cloud.arm("DELETE", group["id"], RG_API, allowed=(200, 202, 204))
        wait_absent(cloud, locks, group["id"], RG_API, sleep)
        for item in resources:
            if arm_scope(item["id"]) == group["id"].lower():
                wait_absent(cloud, locks, item["id"], item["api_version"], sleep)
                receipt["deleted_resources"].append(item["id"])
        receipt["deleted_resources"].append(group["id"])
        removed.append(group["id"])
        pending = list(cascades.get(group["id"].lower(), set()))
        cascading = set()
        while pending:
            managed = pending.pop()
            if managed not in cascading:
                cascading.add(managed)
                pending.extend(cascades.get(managed, set()))
        for managed in sorted(cascading):
            if managed in {scope.lower() for scope in removed}:
                continue
            status, _, body = cloud.arm("GET", managed, RG_API, allowed=(200, 404))
            if status == 200 and (body.get("properties") or {}).get("provisioningState") != "Deleting":
                continue
            wait_absent(cloud, locks, managed, RG_API, sleep)
            for item in resources:
                if arm_scope(item["id"]) == managed:
                    wait_absent(cloud, locks, item["id"], item["api_version"], sleep)
                    receipt["deleted_resources"].append(item["id"])
            receipt["deleted_resources"].append(managed)
            removed.append(managed)
        receipt.pop("pending_resource_group", None)
        persist()


class _ExecutionClaim:
    """A frozen manifest bound to a durable one-shot claim and live physical leases."""

    def __init__(self, document, proof):
        self.manifest = canonical(document)
        self.proof = canonical(proof)

    def verify(self, document, locks):
        require(canonical(document) == self.manifest, "claimed-manifest-changed")
        _validate_manifest(document)
        locks.verify_enrollment()
        locks.assert_held()
        proof = locks.read_claim()
        require(canonical(proof) == self.proof, "execution-claim-changed")
        require(isinstance(proof, dict) and proof.get("schema") == 1 and guid(proof.get("claim_id"))
                and proof.get("run_id") == document["run_id"]
                and proof.get("manifest_hash") == document["manifest_hash"]
                and proof.get("source") == document["source"]
                and proof.get("lease_context_hash") == digest(locks.held),
                "execution-claim-binding-mismatch")
        accepted = timestamp(proof.get("accepted_at"))
        require(timestamp(document["prepared_at"]) <= accepted < timestamp(document["expires_at"])
                and accepted <= time.time(),
                "execution-claim-outside-consent")
        _, _, current = locks.request("GET", "runs/" + document["run_id"] + ".json")
        require(isinstance(current, dict) and current.get("execution_claim") == proof
                and (current.get("state") == "claimed" or current.get("status") == "running"),
                "execution-claim-not-active")


class BlobLocks:
    """Pre-provisioned physical RG leases survive client failure until reconciliation."""

    def __init__(self, cloud, document):
        self.cloud, self.document = cloud, document
        self.settings = document["locks"]
        self.base = self.settings["account_url"] + "/" + self.settings["container"] + "/"
        self.held = {}
        self.inherited = set(self.settings.get("inherited_leases", {}))
        self.enrollment = None
        self.execution_claim = None
        self.cohort_guard = None

    def request(self, method, blob, data=None, headers=None, allowed=(200,), query=""):
        safe_headers = {"x-ms-version": "2023-11-03", "x-ms-date":
                        datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")}
        safe_headers.update(headers or {})
        return self.cloud.request(method, self.base + quote(blob, safe="/") + query, "https://storage.azure.com/",
                                  data=data, headers=safe_headers, allowed=allowed)

    def verify_enrollment(self):
        _, _, enrollment = self.request("GET", self.settings["coordination_blob"])
        require(digest(enrollment) == self.settings["coordination_hash"], "lock-enrollment-changed")
        require(isinstance(enrollment, dict) and enrollment.get("schema") == 1
                and enrollment.get("protocol") == "aifactory-physical-lock-v1"
                and enrollment.get("enforcement") == "all-writers-exclusive"
                and enrollment.get("revision") == self.settings["revision"], "invalid-lock-enrollment")
        route = self.document["route"]
        writers = enrollment.get("writers", {})
        require(isinstance(writers, dict) and route["writer_id"] in writers, "writer-not-enrolled")
        writer = writers[route["writer_id"]]
        require(all(writer.get(key) == route[key] for key in ("kind", "repository", "shared_remote")),
                "writer-binding-changed")
        if "deployment" in self.document:
            require(writer.get("auth_namespace") == route["auth_namespace"]
                    and writer.get("deployment_object_id") == self.document["identity"]["deployment_object_id"]
                    and writer.get("runner") == route["runner"],
                    "namespaced-deployment-identity-not-enrolled")
            require(not any(key != route["writer_id"] and value.get("kind") == route["kind"]
                            and unquote(str(value.get("repository", ""))).lower().removesuffix(".git") ==
                            unquote(route["repository"]).lower().removesuffix(".git")
                            and str(value.get("auth_namespace", "")).lower() == route["auth_namespace"].lower()
                            for key, value in writers.items()), "remote-auth-namespace-shared-by-writers")
        scopes = enrollment.get("scopes", {})
        dependencies = set()
        for scope in self.settings["scopes"]:
            binding = scopes.get(scope.lower(), {})
            require(binding.get("writers") == [route["writer_id"]], "one-designated-writer-per-target-required")
            target = {key: self.document["target"][key] for key in (
                "factory_id", "scaleset_id", "environment", "tenant_id", "subscription_id", "prefix", "region", "suffix")}
            require(binding.get("target") == target and binding.get("scope_kind") == "aifactory-owned",
                    "physical-target-enrollment-mismatch")
            require(self.document["operation"] != "delete" or binding.get("allow_delete") is True,
                    "physical-target-deletion-not-enrolled")
            required = binding.get("common_dependencies")
            require(isinstance(required, list), "common-dependency-enrollment-required")
            dependencies.update(item.lower() for item in required)
        require(dependencies == {item.lower() for item in self.settings["common_dependencies"]},
                "common-dependency-locks-mismatch")
        for scope in dependencies:
            require(scope in scopes and isinstance(scopes[scope].get("writers"), list)
                    and scopes[scope]["writers"], "common-dependency-not-enrolled")
        self.enrollment = enrollment

    @staticmethod
    def blob_name(scope):
        return "locks/" + hashlib.sha256(scope.lower().encode("utf-8")).hexdigest() + ".lock"

    def acquire(self):
        self.verify_enrollment()
        scopes = sorted({item.lower() for item in self.settings["scopes"] + self.settings["common_dependencies"]})
        try:
            for scope in scopes:
                self.acquire_scope(scope)
            self.verify_enrollment()
        except BaseException:
            self.release()
            raise

    def acquire_scope(self, scope):
        if scope in self.inherited:
            lease = self.settings["inherited_leases"][scope]
            self.request("PUT", self.blob_name(scope), headers={
                "x-ms-lease-action": "renew", "x-ms-lease-id": lease,
            }, query="?comp=lease", allowed=(200,))
            self.held[scope] = lease
            return
        lease = str(uuid4())
        try:
            self.request("PUT", self.blob_name(scope), headers={
                "x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1", "x-ms-proposed-lease-id": lease,
            }, query="?comp=lease", allowed=(201,))
        except BaseException as error:
            # A lost response may still have acquired the infinite lease.
            if not isinstance(error, Blocked) or not error.code.startswith("remote-request-failed-4"):
                self.held[scope] = lease
            raise
        self.held[scope] = lease

    def assert_held(self):
        if self.cohort_guard is not None:
            self.cohort_guard()
            return
        require(self.held, "distributed-locks-not-held")
        for scope, lease in self.held.items():
            self.request("PUT", self.blob_name(scope), headers={
                "x-ms-lease-action": "renew", "x-ms-lease-id": lease,
            }, query="?comp=lease", allowed=(200,))

    def claim_run(self):
        validate_manifest(self.document)
        self.verify_enrollment()
        self.assert_held()
        require(set(self.held) == {scope.lower() for scope in
                self.settings["scopes"] + self.settings["common_dependencies"]},
                "execution-claim-locks-incomplete")
        validate_manifest(self.document)
        proof = {"schema": 1, "claim_id": str(uuid4()), "run_id": self.document["run_id"],
                 "manifest_hash": self.document["manifest_hash"], "source": self.document["source"],
                 "accepted_at": utc_now(), "lease_context_hash": digest(self.held)}
        self.request("PUT", "runs/" + self.document["run_id"] + ".json",
                     data={"schema": 1, "run_id": self.document["run_id"], "state": "claimed",
                           "manifest_hash": self.document["manifest_hash"], "execution_claim": proof},
                     headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, allowed=(201,))
        self.request("PUT", "runs/" + self.document["run_id"] + ".claim.json", data=proof,
                     headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, allowed=(201,))
        validate_manifest(self.document)
        self.execution_claim = _ExecutionClaim(self.document, proof)
        self.authorize(self.document)

    def read_claim(self):
        return self.request("GET", "runs/" + self.document["run_id"] + ".claim.json")[2]

    def authorize(self, document):
        if self.execution_claim is None:
            # Direct low-level callers get no post-expiry privilege.
            return validate_manifest(document)
        require(type(self.execution_claim) is _ExecutionClaim, "verified-execution-claim-required")
        self.execution_claim.verify(document, self)
        return document

    def store_receipt(self, receipt):
        if self.execution_claim is not None:
            receipt["execution_claim"] = json.loads(self.execution_claim.proof)
        self.request("PUT", "runs/" + self.document["run_id"] + ".json", data=receipt,
                     headers={"x-ms-blob-type": "BlockBlob", "If-Match": "*"}, allowed=(201,))

    def release(self):
        failures = []
        for scope, lease in list(self.held.items())[::-1]:
            if scope in self.inherited:
                continue
            try:
                self.request("PUT", self.blob_name(scope), headers={
                    "x-ms-lease-action": "release", "x-ms-lease-id": lease,
                }, query="?comp=lease", allowed=(200,))
                del self.held[scope]
            except (Blocked, OSError):
                failures.append(scope)
        require(not failures, "lock-release-reconciliation-required")


def verify_source(cloud, root, source):
    return _verify_source(cloud, root, source, published=True)


def _verify_source(cloud, root, source, *, published):
    root = clean_path(root)
    require(root.is_dir(), "version-source-unavailable")
    require(clean_path(cloud.command(["git", "rev-parse", "--show-toplevel"], cwd=str(root))) == root,
            "version-source-repository-root-required")
    require(cloud.command(["git", "rev-parse", "HEAD"], cwd=str(root)) == source["commit"],
            "version-source-commit-mismatch")
    require(not cloud.command(["git", "status", "--porcelain", "--untracked-files=no"], cwd=str(root)),
            "version-source-dirty")
    origin = cloud.command(["git", "remote", "get-url", "origin"], cwd=str(root)).removesuffix(".git")
    require(origin == SOURCE_ORIGIN, "untrusted-version-source")
    if published:
        remote = cloud.command(["git", "ls-remote", "--exit-code", "origin",
                                source["ref"], source["ref"] + "^{}"], cwd=str(root)).splitlines()
        refs = {}
        for line in remote:
            fields = line.split()
            require(len(fields) == 2, "invalid-published-version-response")
            refs[fields[1]] = fields[0]
        require(refs.get(source["ref"] + "^{}", refs.get(source["ref"])) == source["commit"],
                "version-no-longer-published-at-reviewed-commit")
    published_helper = cloud.command(["git", "show", source["commit"] + ":bootstrap/lib/factory_lifecycle.py"], cwd=str(root))
    require(published_helper == Path(__file__).read_text(encoding="utf-8").strip(),
            "published-lifecycle-adapter-mismatch")
    return root


def verify_ownership(body, owner):
    tags = {key.lower(): str(value) for key, value in (body.get("tags") or {}).items()}
    require(all(tags.get(TAG_KEYS[key]) == value for key, value in owner.items() if key in TAG_KEYS),
            "live-resource-ownership-mismatch")


def verify_fingerprint(item, body, headers):
    require(isinstance(body, dict) and str(body.get("id", "")).lower() == item["id"].lower(),
            "live-resource-identity-mismatch")
    etag = body.get("etag") or next((value for key, value in headers.items() if key.lower() == "etag"), None)
    require(etag == item.get("etag") and digest(body) == item["body_hash"], "inventory-changed-since-prepare")


def verify_inventory(cloud, document, remaining=None):
    data = document["deletion"]
    resources = data["resources"] if remaining is None else remaining
    for group in data["resource_groups"]:
        scope = group["id"].lower()
        _, headers, body = cloud.arm("GET", group["id"], RG_API)
        verify_fingerprint(group, body, headers)
        cloud.assert_no_active_deployments(scope)
        actual = cloud.list_resources(scope)
        expected_ids = {item["id"].lower() for item in resources if arm_scope(item["id"]) == scope}
        require(all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in actual),
                "incomplete-live-inventory")
        require(len(actual) == len(expected_ids) and {row["id"].lower() for row in actual} == expected_ids,
                "live-inventory-not-exact-allowlist")
    for item in resources:
        _, headers, body = cloud.arm("GET", item["id"], item["api_version"])
        verify_fingerprint(item, body, headers)
        verify_ownership(body, item["owner"])


def delete_resources(cloud, locks, document, receipt, persist, sleep=time.sleep):
    locks.authorize(document)
    verify_inventory(cloud, document)
    remaining = list(document["deletion"]["resources"])
    for item in deletion_order(remaining):
        locks.authorize(document)
        locks.assert_held()
        cloud.verify_identity()
        cloud.assert_no_active_runs(locks.enrollment)
        verify_inventory(cloud, document, remaining)
        locks.authorize(document)
        locks.assert_held()
        receipt["mutation_started"] = True
        receipt["pending_resource"] = item["id"]
        persist()
        # If-Match is defense in depth; leases and the complete re-read are the
        # concurrency boundary because not every ARM provider implements it.
        cloud.arm("DELETE", item["id"], item["api_version"], allowed=(200, 202, 204),
                  headers={"If-Match": item["etag"]} if item.get("etag") else None)
        wait_absent(cloud, locks, item["id"], item["api_version"], sleep)
        receipt["deleted_resources"].append(item["id"])
        receipt.pop("pending_resource", None)
        remaining = [row for row in remaining if row["id"].lower() != item["id"].lower()]
        persist()
    locks.assert_held()
    cloud.verify_identity()
    cloud.assert_no_active_runs(locks.enrollment)
    verify_inventory(cloud, document, remaining)


def wait_absent(cloud, locks, resource_id, api_version, sleep):
    # Whole resource groups routinely outlast the ten-minute leaf budget.
    for _ in range(1440 if RG_ID.fullmatch(resource_id) else 120):
        locks.assert_held()
        status, _, _ = cloud.arm("GET", resource_id, api_version, allowed=(200, 404))
        if status == 404:
            return
        sleep(5)
    raise Blocked("delete-completion-unverified")


def ado_project(cloud, locks, document, source_root, receipt, persist, sleep=time.sleep):
    """Use installed reviewed ADO templates, exact self.version and per-run secret."""
    route, target = document["route"], document["target"]
    organization, project, _, repository = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
    api = "https://dev.azure.com/" + quote(organization, safe="") + "/" + quote(project, safe="") + "/_apis"
    audience = "https://app.vssps.visualstudio.com/"
    organization_tenant = document["config"].get("dev", {}).get("azureDevOpsTenantId", "")
    require(not organization_tenant or organization_tenant.lower() == target["tenant_id"].lower(),
            "cross-tenant-ado-route-unsupported")

    def request(method, endpoint, data=None):
        return cloud.request(method, api + endpoint, audience, data=data, allowed=(200, 201))[2]

    _, _, submodule = cloud.request("GET", api + "/git/repositories/" + quote(repository, safe="")
                                   + "/items?path=%2Fazure-enterprise-scale-ml"
                                   + "&versionDescriptor.version=" + route["commit"]
                                   + "&versionDescriptor.versionType=commit&api-version=7.1", audience)
    require(isinstance(submodule, dict) and submodule.get("gitObjectType") == "commit"
            and submodule.get("objectId") == document["source"]["commit"], "consumer-version-source-mismatch")
    for remote, relative in ADO_FILES.items():
        _, _, item = cloud.request("GET", api + "/git/repositories/" + quote(repository, safe="")
                                  + "/items?path=" + quote("/" + remote, safe="")
                                  + "&versionDescriptor.version=" + route["commit"]
                                  + "&versionDescriptor.versionType=commit&includeContent=true&api-version=7.1",
                                  audience)
        content = item.get("content") if isinstance(item, dict) else None
        expected = cloud.command(["git", "show", document["source"]["commit"] + ":" + relative], cwd=str(source_root))
        require(isinstance(content, str) and content.strip() == expected
                and "AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1" in content, "published-project-template-mismatch")
    _, headers, response = cloud.request("GET", api + "/build/definitions?includeAllProperties=true&api-version=7.1&%24top=1000",
                                        audience)
    require(not any(key.lower() == "x-ms-continuationtoken" and value for key, value in headers.items()),
            "incomplete-pipeline-inventory")
    rows = response.get("value", [])
    require(isinstance(rows, list) and len(rows) < 1000, "ambiguous-pipeline-inventory")
    matches = [row for row in rows if row.get("repository", {}).get("name") == repository
               and row.get("process", {}).get("yamlFilename", "").lstrip("/") == ADO_PIPELINE
               and row.get("queueStatus", "enabled") == "enabled"]
    require(len(matches) == 1 and type(matches[0].get("id")) is int, "exact-ado-pipeline-required")
    pipeline = matches[0]["id"]
    request_body = project_run_request(document)
    locks.assert_held()
    cloud.verify_identity()
    locks.authorize(document)
    cloud.assert_no_active_runs(locks.enrollment)
    receipt["mutation_started"] = True
    receipt["pending_dispatch"] = {"kind": "ado", "pipeline_id": pipeline}
    persist()
    run = request("POST", f"/pipelines/{pipeline}/runs?api-version=7.1", request_body)
    require(type(run.get("id")) is int and run["id"] > 0, "dispatch-correlation-unverified")
    receipt["remote_run"] = {"kind": "ado", "pipeline_id": pipeline, "run_id": run["id"]}
    receipt.pop("pending_dispatch", None)
    persist()
    for _ in range(1440):
        locks.assert_held()
        result = request("GET", f"/pipelines/{pipeline}/runs/{run['id']}?api-version=7.1")
        version = (result.get("resources", {}).get("repositories", {}).get("self", {}).get("version"))
        require(version == route["commit"], "remote-run-commit-mismatch")
        if result.get("state") == "completed":
            receipt["remote_terminal"] = True
            require(result.get("result") == "succeeded", "project-run-failed-or-cancelled")
            return
        require(result.get("state") in ("inProgress", "canceling"), "remote-run-state-unverified")
        sleep(15)
    raise Blocked("project-completion-unverified")


def project_run_request(document):
    target, route = document["target"], document["route"]
    config = canonical(document["config"]).decode("utf-8")
    values = document["config"]["dev" if target["environment"] == "dev" else "stage_prod"]
    settings = {key: str(values.get(key, default)).lower() if isinstance(default, bool)
                else str(values.get(key, default)) for key, default in {
                    "runNetworkingVar": True, "BYO_subnets": False, "useSelfHostedBuildAgent": False,
                    "adminVMBuildAgentPool": "", "adminVMBuildAgentName": "",
                    "admin_locationSuffix": "", "admin_commonResourceSuffix": "",
                }.items()}
    return {
        "resources": {"repositories": {"self": {"refName": route["ref"], "version": route["commit"]}}},
        "templateParameters": {
            "configFile": "aifactory/.reviewed-project-config.json", "useJsonConfigOverride": True,
            "runnerSelection": "from-config", "deploymentTarget": target["environment"],
            "deploymentProjectNumber": target["project_ids"][0],
            "deploymentConfigHash": hashlib.sha256(config.encode("utf-8")).hexdigest(),
            "deploymentSettings": settings,
        },
        "variables": {
            "AIFACTORY_CONFIG_JSON": {"value": config, "isSecret": True},
            "AIFACTORY_LIFECYCLE_RUN_ID": {"value": document["run_id"]},
        },
        "stagesToSkip": [stage for environment, stage in (
            ("dev", "Dev_GenAI_Project"), ("stage", "Stage_GenAI_Project"), ("prod", "Prod_GenAI_Project"),
        ) if environment != target["environment"]],
    }


def arm_changes(body):
    require(isinstance(body, dict) and body.get("status") in (None, "Succeeded") and not body.get("error"),
            "arm-what-if-failed-or-incomplete")
    properties = body.get("properties", body)
    require(isinstance(properties, dict) and not properties.get("error")
            and isinstance(properties.get("changes"), list), "complete-arm-what-if-required")
    result = []
    for change in properties["changes"]:
        require(change.get("changeType") in ("Create", "Modify", "NoChange"), "unresolved-or-destructive-arm-what-if")
        require(isinstance(change.get("resourceId"), str), "invalid-arm-what-if-resource")
        result.append({"resource_id": change["resourceId"].lower(), "change_type": change["changeType"],
                       "before_hash": digest(change["before"]) if change.get("before") is not None else None,
                       "after_hash": digest(change["after"]) if change.get("after") is not None else None})
    require(len({row["resource_id"] for row in result}) == len(result), "duplicate-arm-what-if-resource")
    return sorted(result, key=lambda row: row["resource_id"])


def deployment_endpoint(document, step):
    scope = ("/subscriptions/" + document["target"]["subscription_id"] if step["scope"] == "subscription"
             else step["resource_group"])
    # Keep the whole run identity and a stable phase digest within ARM's 64-character limit.
    name = "aif-" + document["run_id"].replace("-", "") + "-" + hashlib.sha256(step["id"].encode("utf-8")).hexdigest()[:24]
    return ARM + scope + "/providers/Microsoft.Resources/deployments/" + name


def compiled_plan_step(cloud, document, step, source_root):
    template = cloud.compile_template(source_root, step["template"])
    require(digest(template) == step["template_hash"], "compiled-template-hash-mismatch")
    require(set(template["parameters"]) == set(step["parameters"]), "parameters-not-fully-resolved")
    schema = template.get("$schema", "").lower()
    require(("subscriptiondeploymenttemplate" in schema) == (step["scope"] == "subscription"),
            "compiled-template-scope-mismatch")
    return {"location": document["target"]["region"],
            "properties": {"mode": "Incremental", "template": template,
                           "parameters": {key: {"value": value} for key, value in step["parameters"].items()}}}


def resolve_template_parameters(compiled_template, selected_values, parameter_sources):
    """Pure preparation helper; expose every unused setting instead of dropping it."""
    require(isinstance(compiled_template.get("parameters"), dict) and isinstance(selected_values, dict)
            and isinstance(parameter_sources, dict), "invalid-parameter-preparation-input")
    definitions = compiled_template["parameters"]
    require(set(parameter_sources) <= set(definitions), "unknown-parameter-source-binding")
    resolved, consumed, defaults = {}, set(), []
    identity_keys = {"env", "location", "tenantId", "projectNumber", "commonRGNamePrefix", "aifactorySuffixRG", "tags", "tagsProject"}
    for key, definition in definitions.items():
        source = parameter_sources.get(key, key)
        require(isinstance(source, str), "invalid-parameter-source-binding")
        kind = definition.get("type", "").lower()
        if source in selected_values:
            value = selected_values[source]
            consumed.add(source)
        else:
            require(key not in parameter_sources and key not in identity_keys and kind not in ("securestring", "secureobject")
                    and "defaultValue" in definition, "explicit-parameter-value-required")
            value = definition["defaultValue"]
            require(not isinstance(value, str) or not value.startswith("["), "default-expression-must-be-resolved")
            defaults.append(key)
        if kind == "bool" and isinstance(value, str):
            require(value.lower() in ("true", "false"), "invalid-boolean-parameter")
            value = value.lower() == "true"
        elif kind == "int" and isinstance(value, str):
            require(re.fullmatch(r"-?[0-9]+", value), "invalid-integer-parameter")
            value = int(value)
        elif kind in ("array", "object", "secureobject") and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise Blocked("invalid-structured-parameter") from None
        expected_type = {"string": str, "securestring": str, "int": int, "bool": bool,
                         "array": list, "object": dict, "secureobject": dict}.get(kind)
        require(expected_type is not None and type(value) is expected_type, "parameter-type-mismatch")
        require("allowedValues" not in definition or value in definition["allowedValues"], "parameter-value-not-allowed")
        resolved[key] = value
    return {"parameters": resolved, "consumed_configuration_keys": sorted(consumed),
            "unused_configuration_keys": sorted(set(selected_values) - consumed), "published_defaults": sorted(defaults)}


def evaluate_what_if(cloud, document, step, payload, sleep=time.sleep):
    endpoint = deployment_endpoint(document, step)
    body = json.loads(canonical(payload))
    body["properties"]["whatIfSettings"] = {"resultFormat": "FullResourcePayloads"}
    status, headers, response = cloud.request("POST", endpoint + "/whatIf?api-version=2022-09-01",
                                             ARM, data=body, allowed=(200, 202))
    if status == 202:
        location = next((value for key, value in headers.items() if key.lower() == "location"), "")
        require(location.startswith(ARM + "/subscriptions/" + document["target"]["subscription_id"] + "/"),
                "untrusted-what-if-poll-url")
        for _ in range(120):
            sleep(5)
            poll_status, _, response = cloud.request("GET", location, ARM, allowed=(200, 202))
            state = response.get("status") if isinstance(response, dict) else None
            require(state not in ("Failed", "Canceled", "Cancelled")
                    and not (isinstance(response, dict) and response.get("error")), "arm-what-if-failed")
            if poll_status == 202:
                continue
            require(isinstance(response, dict), "arm-what-if-failed-or-incomplete")
            if state in (None, "Succeeded"):
                break
        else:
            raise Blocked("arm-what-if-incomplete")
    return arm_changes(response)


def frozen_step(cloud, document, step, source_root):
    """Read-only prepare hook: caller supplies every parameter; no defaults invented.

    Invoke before sealing the manifest. ARM what-if is read-only, but this API
    intentionally is not called by capabilities/inspect.
    """
    source_root = verify_source(cloud, source_root, document["source"])
    cloud.verify_identity()
    template = cloud.compile_template(source_root, step["template"])
    require(set(template["parameters"]) == set(step["parameters"]), "parameters-not-fully-resolved")
    frozen = dict(step, template_hash=digest(template))
    payload = compiled_plan_step(cloud, document, frozen, source_root)
    frozen["changes"] = evaluate_what_if(cloud, document, frozen, payload)
    return frozen


def combined_plan_payload(cloud, document, source_root):
    """Deploy ordered phases together so preview sees their dependency graph."""
    target, steps = document["target"], document["deployment"]["steps"]
    outer = {"$schema": "https://schema.management.azure.com/schemas/2018-05-01/subscriptionDeploymentTemplate.json#",
             "contentVersion": "1.0.0.0", "parameters": {}, "resources": []}
    parameters = {}
    ids = {step["id"]: deployment_endpoint(document, step).removeprefix(ARM) for step in steps}
    for index, step in enumerate(steps):
        payload = compiled_plan_step(cloud, document, step, source_root)
        parameter_name = "step_" + str(index)
        outer["parameters"][parameter_name] = {"type": "secureObject"}
        parameters[parameter_name] = {"value": step["parameters"]}
        nested = {"type": "Microsoft.Resources/deployments", "apiVersion": "2022-09-01",
                  "name": ids[step["id"]].rsplit("/", 1)[-1], "subscriptionId": target["subscription_id"],
                  "dependsOn": [ids[value] for value in step["depends_on"]],
                  "properties": {"mode": "Incremental", "expressionEvaluationOptions": {"scope": "inner"},
                                 "template": payload["properties"]["template"],
                                 "parameters": {key: {"value": "[parameters('" + parameter_name + "')['" + key + "']]"}
                                                for key in step["parameters"]}}}
        specification = step.get("template_spec_id")
        if specification:
            require(isinstance(specification, str) and NESTED_ID.fullmatch(specification)
                    and resource_type_from_id(specification) == "microsoft.resources/templatespecs/versions"
                    and arm_scope(specification) in {scope.lower() for scope in document["locks"]["common_dependencies"]},
                    "reviewed-template-spec-scope-required")
            _, _, spec = cloud.arm("GET", specification, "2022-02-01")
            require(digest(spec.get("properties", {}).get("mainTemplate")) == step["template_hash"],
                    "published-template-spec-hash-mismatch")
            del nested["properties"]["template"]
            nested["properties"]["templateLink"] = {"id": specification}
        if step["scope"] == "subscription":
            nested["location"] = target["region"]
        else:
            nested["resourceGroup"] = RG_ID.fullmatch(step["resource_group"])[2]
        outer["resources"].append(nested)
    require(len(canonical(outer)) <= 4 * 1024 * 1024, "combined-template-too-large-use-reviewed-template-specs")
    return {"location": target["region"], "properties": {"mode": "Incremental", "template": outer, "parameters": parameters}}


def freeze_deployment_plan(cloud, document, source_root):
    """Read-only whole-plan what-if for a caller-resolved, ordered ARM plan."""
    source_root = verify_source(cloud, source_root, document["source"])
    cloud.verify_identity()
    result = json.loads(canonical(document["deployment"]))
    draft = {**document, "deployment": result}
    for step in result["steps"]:
        template = cloud.compile_template(source_root, step["template"])
        require(set(template["parameters"]) == set(step["parameters"]), "parameters-not-fully-resolved")
        step["template_hash"] = digest(template)
    payload = combined_plan_payload(cloud, draft, source_root)
    result["changes"] = evaluate_what_if(cloud, draft, {"id": "factory", "scope": "subscription"}, payload)
    result["configuration_hash"] = digest(document["config"])
    return result


def run_deployment_worker(envelope, source_root, expected_run, expected_hash, cloud=None, sleep=time.sleep):
    require(isinstance(envelope, dict), "invalid-worker-envelope")
    envelope = json.loads(canonical(envelope))
    document = _validate_manifest(envelope.get("manifest"))
    require(document["run_id"] == expected_run and document["manifest_hash"] == expected_hash
            and "deployment" in document, "worker-run-binding-mismatch")
    context = envelope.get("lease_context")
    scopes = {scope.lower() for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]}
    require(isinstance(context, dict) and set(context) == scopes and all(guid(value) for value in context.values()),
            "worker-lease-context-required")
    if cloud is None:
        require(sys.platform.startswith("linux"), "linux-scoped-worker-required")
    cloud = cloud or Cloud(document, expected_object_id=document["identity"]["deployment_object_id"])
    cloud.verify_identity(require_default=True)
    locks = BlobLocks(cloud, document)
    locks.held = dict(context)
    locks.verify_enrollment()
    locks.assert_held()
    locks.execution_claim = _ExecutionClaim(document, locks.read_claim())
    locks.authorize(document)
    # Publication was checked before the parent's durable claim. A moving ref
    # cannot replace the accepted checkout or invalidate its exact commit.
    source_root = _verify_source(cloud, source_root, document["source"], published=False)
    receipt = {"schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
               "source_commit": document["source"]["commit"], "target": document["target"],
               "status": "running", "deployments": [], "ownership": [], "resource_groups": [], "mutation_started": False}
    blob = "runs/" + document["run_id"] + ".worker.json"
    locks.request("PUT", blob, data=receipt,
                  headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"}, allowed=(201,))

    def persist():
        receipt["updated_at"] = utc_now()
        locks.request("PUT", blob, data=receipt, headers={"x-ms-blob-type": "BlockBlob", "If-Match": "*"}, allowed=(201,))

    try:
        before_ids = set()
        previous_owners, previous_receipts = {}, {}
        modified_ids = {row["resource_id"].lower() for row in document["deployment"]["changes"]
                        if row["change_type"] != "NoChange"}
        existing_scopes = []
        for scope in document["locks"]["scopes"]:
            status, _, group = cloud.arm("GET", scope, RG_API, allowed=(200, 404))
            if status == 200:
                existing_scopes.append(scope)
        if existing_scopes:
            closure, current_bodies = collect_resource_closure(cloud, existing_scopes)
            for scope in existing_scopes:
                verify_group_ownership(current_bodies[scope.lower()],
                                       {key: document["target"][key] for key in ("factory_id", "scaleset_id")}, current_bodies)
            before_ids.update(closure["resources"])
            for key, metadata in closure["resources"].items():
                tags = current_bodies[key].get("tags") or {}
                owner = {field: tags[TAG_KEYS[field]] for field in TAG_KEYS if TAG_KEYS[field] in tags}
                if all(field in owner for field in ("factory_id", "scaleset_id")):
                    previous_owners[key] = owner
                else:
                    evidence = document["deployment"].get("known_ownership", {}).get(key, {})
                    previous_owners[key] = verified_receipt_owner(locks, evidence, key, metadata["body_hash"], previous_receipts)
                require(all(previous_owners[key].get(field) == document["target"][field]
                            for field in ("factory_id", "scaleset_id")), "existing-resource-owner-mismatch")
                require(key not in modified_ids or not previous_owners[key].get("project_id")
                        or previous_owners[key]["project_id"] in document["target"]["project_ids"],
                        "existing-other-project-resource-write-forbidden")
        locks.assert_held()
        cloud.verify_identity(require_default=True)
        payload = combined_plan_payload(cloud, document, source_root)
        root_step = {"id": "factory", "scope": "subscription"}
        reviewed = sorted(({**row, "resource_id": row["resource_id"].lower()}
                           for row in document["deployment"]["changes"]), key=lambda row: row["resource_id"])
        require(evaluate_what_if(cloud, document, root_step, payload, sleep) == reviewed,
                "arm-what-if-changed-since-prepare")
        locks.assert_held()
        locks.authorize(document)
        endpoint = deployment_endpoint(document, root_step)
        receipt["pending_deployment"] = endpoint.removeprefix(ARM)
        receipt["mutation_started"] = True
        persist()
        cloud.request("PUT", endpoint + "?api-version=2022-09-01", ARM, data=payload, allowed=(200, 201, 202))
        for _ in range(1440):
            locks.assert_held()
            _, _, state = cloud.request("GET", endpoint + "?api-version=2022-09-01", ARM)
            provisioned = state.get("properties", {}).get("provisioningState")
            if provisioned in ("Succeeded", "Failed", "Canceled"):
                require(provisioned == "Succeeded", "arm-deployment-failed")
                break
            require(provisioned in ("Accepted", "Running", "Creating", "Updating"), "arm-deployment-state-unverified")
            sleep(5)
        else:
            raise Blocked("arm-deployment-completion-unverified")
        for step in document["deployment"]["steps"]:
            child_endpoint = deployment_endpoint(document, step)
            _, _, child = cloud.request("GET", child_endpoint + "?api-version=2022-09-01", ARM)
            require(child.get("properties", {}).get("provisioningState") == "Succeeded",
                    "scoped-child-deployment-unverified")
            receipt["deployments"].append({"step_id": step["id"], "id": child_endpoint.removeprefix(ARM), "status": "succeeded"})
        receipt.pop("pending_deployment", None)
        persist()
        closure, bodies = collect_resource_closure(cloud, document["locks"]["scopes"])
        for scope in document["locks"]["scopes"]:
            body = bodies[scope.lower()]
            verify_group_ownership(body,
                                   {key: document["target"][key] for key in ("factory_id", "scaleset_id")}, bodies)
            owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
            project = (body.get("tags") or {}).get(TAG_KEYS["project_id"])
            if project is not None:
                owner["project_id"] = project
            receipt["resource_groups"].append({
                "resource_id": scope.lower(), "owner": owner, "body_hash": digest(body),
                "etag": closure["groups"][scope.lower()].get("etag", body.get("etag")),
            })
        for resource_id, body in bodies.items():
            if resource_id in closure["groups"]:
                continue
            tags = body.get("tags") or {}
            owner = {key: tags[TAG_KEYS[key]] for key in TAG_KEYS if TAG_KEYS[key] in tags}
            if not owner and resource_id in previous_owners:
                owner = previous_owners[resource_id]
            if not owner and resource_id not in before_ids:
                owner = inherited_new_resource_owner(resource_id, bodies)
            require(owner.get("factory_id") == document["target"]["factory_id"]
                    and owner.get("scaleset_id") == document["target"]["scaleset_id"],
                    "post-deployment-resource-ownership-unverified")
            require((body.get("properties") or {}).get("provisioningState") in (None, "Succeeded"),
                    "post-deployment-resource-not-ready")
            receipt["ownership"].append({"resource_id": resource_id, "owner": owner,
                                         **closure["resources"][resource_id]})
        receipt["inventory_closure_hash"] = digest(closure)
        require(receipt["ownership"] or receipt["resource_groups"], "post-deployment-owned-inventory-empty")
        require(set(document["target"]["project_ids"]) <= {
            row["owner"].get("project_id") for row in receipt["ownership"] + receipt["resource_groups"]},
            "selected-project-inventory-incomplete")
        locks.authorize(document)
        receipt["status"] = "succeeded"
        persist()
    except BaseException as error:
        receipt["status"] = "reconciliation-required"
        receipt["error_code"] = error.code if isinstance(error, Blocked) else "unexpected-worker-failure"
        persist()
    finally:
        cloud.tokens.clear()
    return receipt


def verify_worker_receipt(locks, document):
    _, _, result = locks.request("GET", "runs/" + document["run_id"] + ".worker.json")
    require(isinstance(result, dict) and result.get("schema") == 1 and result.get("status") == "succeeded"
            and result.get("run_id") == document["run_id"] and result.get("manifest_hash") == document["manifest_hash"]
            and result.get("source_commit") == document["source"]["commit"] and result.get("target") == document["target"],
            "scoped-worker-receipt-unverified")
    expected = [step["id"] for step in document["deployment"]["steps"]]
    require([step.get("step_id") for step in result.get("deployments", [])] == expected,
            "scoped-worker-steps-incomplete")
    groups = result.get("resource_groups")
    require(isinstance(groups, list) and len(groups) == len(document["locks"]["scopes"])
            and all(isinstance(row, dict) and isinstance(row.get("resource_id"), str)
                    and RG_ID.fullmatch(row["resource_id"]) and hash_value(row.get("body_hash"))
                    and isinstance(row.get("owner"), dict) and all(
                        row["owner"].get(key) == document["target"][key] for key in ("factory_id", "scaleset_id"))
                    for row in groups)
            and {row["resource_id"].lower() for row in groups} == {scope.lower() for scope in document["locks"]["scopes"]},
            "scoped-worker-group-ownership-incomplete")
    require(all(step.get("status") == "succeeded" for step in result["deployments"])
            and isinstance(result.get("ownership"), list)
            and hash_value(result.get("inventory_closure_hash")), "scoped-worker-evidence-incomplete")
    return result


def protected_worker_envelope(document, locks):
    raw = canonical({"manifest": document, "lease_context": locks.held})
    require(len(raw) <= MAX_DOCUMENT, "protected-worker-envelope-too-large")
    return raw


def github_scoped(cloud, locks, document, source_root, receipt, persist, sleep=time.sleep):
    route = document["route"]
    repository = urlsplit(route["repository"]).path.strip("/").removesuffix(".git")

    def github(method, endpoint, body=None):
        argv = ["gh", "api", "--method", method, "repos/" + repository + endpoint, "--hostname", "github.com"]
        if body is not None:
            argv += ["--input", "-"]
        raw = cloud.command(argv, data=canonical(body).decode("utf-8") if body is not None else None)
        return json.loads(raw) if raw else {}

    actor = json.loads(cloud.command(["gh", "api", "user", "--hostname", "github.com"]))
    require(type(route.get("github_user_id")) is int and actor.get("id") == route["github_user_id"],
            "github-authenticated-identity-mismatch")
    item = github("GET", "/contents/" + SCOPED_GHA + "?ref=" + route["commit"])
    require(item.get("encoding") == "base64" and isinstance(item.get("content"), str), "scoped-github-template-missing")
    content = base64.b64decode(item["content"]).decode("utf-8")
    expected = cloud.command(["git", "show", document["source"]["commit"] + ":" + SCOPED_SOURCE + "gha.yml"],
                             cwd=str(source_root))
    require(content.strip() == expected and SCOPED_CONTRACT in content, "scoped-github-template-mismatch")
    tree = github("GET", "/git/trees/" + route["commit"])
    require(any(row.get("path") == "azure-enterprise-scale-ml" and row.get("mode") == "160000"
                and row.get("sha") == document["source"]["commit"] for row in tree.get("tree", [])),
            "consumer-version-source-mismatch")
    envelope = base64.b64encode(zlib.compress(protected_worker_envelope(document, locks))).decode("ascii")
    chunks = [envelope[index:index + 32000] for index in range(0, len(envelope), 32000)]
    require(len(chunks) <= 16, "github-protected-manifest-too-large")
    secret = "AIF_LIFECYCLE_" + document["run_id"].replace("-", "").upper()
    tag = "aifactory-runs/" + document["run_id"]
    locks.assert_held()
    cloud.assert_no_active_runs(locks.enrollment)
    locks.authorize(document)
    receipt["mutation_started"] = True
    receipt["remote_artifacts"] = {"ref": "refs/tags/" + tag, "secret_prefix": secret, "chunks": len(chunks),
                                   "auth_namespace": route["auth_namespace"]}
    persist()
    github("POST", "/git/refs", {"ref": "refs/tags/" + tag, "sha": route["commit"]})
    for index, chunk in enumerate(chunks):
        cloud.command(["gh", "secret", "set", secret + "_" + str(index), "--repo", "github.com/" + repository,
                       "--env", route["auth_namespace"]], data=chunk)
    github("POST", "/actions/workflows/factory-lifecycle.yml/dispatches", {"ref": tag, "inputs": {
        "run_id": document["run_id"], "manifest_hash": document["manifest_hash"], "expected_commit": route["commit"],
        "source_commit": document["source"]["commit"], "auth_namespace": route["auth_namespace"],
        "secret_prefix": secret, "secret_chunks": str(len(chunks)),
        "runs_on": json.dumps(route["runner"]["image"] if route["runner"]["kind"] == "hosted"
                              else route["runner"]["labels"], separators=(",", ":")),
    }})
    run_id = None
    for _ in range(60):
        runs = github("GET", "/actions/workflows/factory-lifecycle.yml/runs?event=workflow_dispatch&per_page=100")
        matches = [row for row in runs.get("workflow_runs", []) if row.get("display_title") ==
                   "factory-lifecycle [" + document["run_id"] + "]"]
        require(len(matches) <= 1, "ambiguous-scoped-github-run")
        if matches:
            require(matches[0].get("head_sha") == route["commit"] and type(matches[0].get("id")) is int,
                    "scoped-github-run-commit-mismatch")
            run_id = matches[0]["id"]
            break
        sleep(2)
    require(run_id is not None, "scoped-github-dispatch-unverified")
    receipt["remote_run"] = {"kind": "gha", "run_id": run_id}
    persist()
    for _ in range(1440):
        locks.assert_held()
        result = github("GET", "/actions/runs/" + str(run_id))
        require(result.get("head_sha") == route["commit"], "scoped-github-run-commit-mismatch")
        if result.get("status") == "completed":
            receipt["remote_terminal"] = True
            break
        require(result.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"),
                "scoped-github-run-state-unverified")
        sleep(15)
    else:
        raise Blocked("scoped-github-completion-unverified")
    for index in range(len(chunks)):
        cloud.command(["gh", "secret", "delete", secret + "_" + str(index), "--repo", "github.com/" + repository,
                       "--env", route["auth_namespace"]])
    ref = github("GET", "/git/ref/tags/" + tag)
    require(ref.get("object", {}).get("sha") == route["commit"], "run-tag-changed-reconciliation-required")
    github("DELETE", "/git/refs/tags/" + tag)
    receipt["remote_artifacts_cleaned"] = True
    persist()
    require(result.get("conclusion") == "success", "scoped-github-run-failed")
    receipt["worker_receipt"] = verify_worker_receipt(locks, document)


def ado_scoped(cloud, locks, document, source_root, receipt, persist, sleep=time.sleep):
    route = document["route"]
    organization, project, _, repository = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
    api = "https://dev.azure.com/" + quote(organization, safe="") + "/" + quote(project, safe="") + "/_apis"
    audience = "https://app.vssps.visualstudio.com/"

    def request(method, endpoint, body=None):
        return cloud.request(method, api + endpoint, audience, data=body, allowed=(200, 201))[2]

    connections = request("GET", "/serviceendpoint/endpoints?endpointNames=" + quote(route["auth_namespace"], safe="")
                          + "&api-version=7.1")
    endpoints = [row for row in connections.get("value", []) if row.get("name") == route["auth_namespace"]]
    require(len(endpoints) == 1, "exact-scoped-service-connection-required")
    authorization = endpoints[0].get("authorization", {})
    require(str(authorization.get("scheme", "")).lower() == "workloadidentityfederation"
            and str(authorization.get("parameters", {}).get("tenantid", "")).lower() == document["target"]["tenant_id"].lower()
            and str(endpoints[0].get("data", {}).get("subscriptionId", "")).lower() == document["target"]["subscription_id"].lower(),
            "scoped-workload-identity-connection-required")
    item = request("GET", "/git/repositories/" + quote(repository, safe="") + "/items?path="
                   + quote("/" + SCOPED_ADO, safe="") + "&versionDescriptor.version=" + route["commit"]
                   + "&versionDescriptor.versionType=commit&includeContent=true&api-version=7.1")
    content = item.get("content", "")
    expected = cloud.command(["git", "show", document["source"]["commit"] + ":" + SCOPED_SOURCE + "ado.yml"],
                             cwd=str(source_root))
    require(content.strip() == expected and SCOPED_CONTRACT in content, "scoped-ado-template-mismatch")
    _, headers, definitions = cloud.request("GET", api + "/build/definitions?includeAllProperties=true&%24top=1000&api-version=7.1",
                                            audience)
    require(not any(key.lower() == "x-ms-continuationtoken" and value for key, value in headers.items())
            and len(definitions.get("value", [])) < 1000, "incomplete-scoped-pipeline-inventory")
    matches = [row for row in definitions.get("value", []) if row.get("repository", {}).get("name") == repository
               and row.get("process", {}).get("yamlFilename", "").lstrip("/") == SCOPED_ADO
               and row.get("queueStatus", "enabled") == "enabled"]
    require(len(matches) == 1 and type(matches[0].get("id")) is int, "exact-scoped-ado-pipeline-required")
    pipeline = matches[0]["id"]
    payload = {"resources": {"repositories": {"self": {"refName": route["ref"], "version": route["commit"]}}},
               "templateParameters": {"runId": document["run_id"], "manifestHash": document["manifest_hash"],
                                      "expectedCommit": route["commit"], "sourceCommit": document["source"]["commit"],
                                      "serviceConnection": route["auth_namespace"],
                                      "runnerKind": route["runner"]["kind"],
                                      "vmImage": route["runner"].get("image", ""),
                                      "agentPool": route["runner"].get("pool", ""),
                                      "agentName": route["runner"].get("agent_name", "")},
               "variables": {"AIFACTORY_ENVELOPE_JSON": {
                   "isSecret": True, "value": protected_worker_envelope(document, locks).decode("utf-8")}}}
    locks.assert_held()
    cloud.assert_no_active_runs(locks.enrollment)
    locks.authorize(document)
    receipt["mutation_started"] = True
    receipt["pending_dispatch"] = {"kind": "ado", "pipeline_id": pipeline}
    persist()
    run = request("POST", f"/pipelines/{pipeline}/runs?api-version=7.1", payload)
    require(type(run.get("id")) is int and run["id"] > 0, "scoped-ado-dispatch-unverified")
    receipt["remote_run"] = {"kind": "ado", "pipeline_id": pipeline, "run_id": run["id"]}
    receipt.pop("pending_dispatch", None)
    persist()
    for _ in range(1440):
        locks.assert_held()
        result = request("GET", f"/pipelines/{pipeline}/runs/{run['id']}?api-version=7.1")
        require(result.get("resources", {}).get("repositories", {}).get("self", {}).get("version") == route["commit"],
                "scoped-ado-run-commit-mismatch")
        if result.get("state") == "completed":
            receipt["remote_terminal"] = True
            require(result.get("result") == "succeeded", "scoped-ado-run-failed")
            receipt["worker_receipt"] = verify_worker_receipt(locks, document)
            return
        require(result.get("state") in ("inProgress", "canceling"), "scoped-ado-state-unverified")
        sleep(15)
    raise Blocked("scoped-ado-completion-unverified")


def write_receipt(path, receipt):
    path = clean_path(path)
    require(path.parent.is_dir(), "receipt-parent-unavailable")
    staged = path.with_name(path.name + ".writing")
    require(not staged.exists(), "receipt-staging-path-exists")
    with staged.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, path)


class _CohortLeases:
    def __init__(self, members):
        self.members = members
        self.frozen = [canonical(locks.document) for locks in members]
        self.owners, self.held = {}, {}
        for locks in members:
            require(not locks.inherited, "cohort-must-own-full-lease-union")
            for scope in locks.settings["scopes"] + locks.settings["common_dependencies"]:
                scope = scope.lower()
                previous = self.owners.get(scope)
                if previous is not None:
                    require(all(previous.settings[key] == locks.settings[key] for key in (
                        "account_url", "container", "coordination_blob", "coordination_hash", "revision")),
                        "cohort-shared-scope-authority-mismatch")
                    require(previous.document["target"]["tenant_id"].lower() ==
                            locks.document["target"]["tenant_id"].lower(),
                            "cohort-shared-scope-cross-tenant-auth-unsupported")
                else:
                    self.owners[scope] = locks

    def verify_documents(self):
        for locks, frozen in zip(self.members, self.frozen):
            require(canonical(locks.document) == frozen, "claimed-manifest-changed")

    def acquire(self):
        for locks in self.members:
            locks.verify_enrollment()
        for scope, locks in sorted(self.owners.items()):
            try:
                locks.acquire_scope(scope)
            finally:
                if scope in locks.held:
                    self.held[scope] = locks.held[scope]
        for locks in self.members:
            scopes = {scope.lower() for scope in locks.settings["scopes"] + locks.settings["common_dependencies"]}
            locks.held = {scope: self.held[scope] for scope in sorted(scopes)}
            locks.cohort_guard = self.assert_held
        self.assert_held()

    def assert_held(self):
        self.verify_documents()
        require(set(self.held) == set(self.owners), "cohort-lock-union-incomplete")
        for locks in self.members:
            locks.verify_enrollment()
            require(all(self.held.get(scope) == lease for scope, lease in locks.held.items()),
                    "cohort-lease-context-changed")
        for scope, lease in sorted(self.held.items()):
            self.owners[scope].request("PUT", BlobLocks.blob_name(scope), headers={
                "x-ms-lease-action": "renew", "x-ms-lease-id": lease,
            }, query="?comp=lease", allowed=(200,))

    def release(self):
        failures = []
        for scope, lease in sorted(self.held.items(), reverse=True):
            try:
                self.owners[scope].request("PUT", BlobLocks.blob_name(scope), headers={
                    "x-ms-lease-action": "release", "x-ms-lease-id": lease,
                }, query="?comp=lease", allowed=(200,))
                del self.held[scope]
                for locks in self.members:
                    locks.held.pop(scope, None)
            except (Blocked, OSError):
                failures.append(scope)
        require(not failures, "lock-release-reconciliation-required")


def _cohort_order(documents):
    targets = {}
    for document in documents:
        for scope in document["locks"]["scopes"]:
            require(scope.lower() not in targets, "cohort-duplicate-writable-scope")
            targets[scope.lower()] = document["manifest_hash"]
    plan = []
    for document in documents:
        dependencies = {scope.lower() for scope in document["locks"]["common_dependencies"]}
        dependencies.update(arm_scope(value) for row in document["deletion"]["resources"] for value in row["depends_on"])
        plan.append({"id": document["manifest_hash"], "delete": True,
                     "depends_on": sorted({targets[scope] for scope in dependencies if scope in targets
                                           and targets[scope] != document["manifest_hash"]})})
    by_hash = {document["manifest_hash"]: document for document in documents}
    return [by_hash[row["id"]] for row in deletion_order(plan)]


def execute_cohort(documents, source_root, execution_root, receipt_path, cloud_factory=Cloud, lock_factory=BlobLocks):
    """Accept all factory children under the full physical union before deleting."""
    require(isinstance(documents, list) and documents, "nonempty-delete-cohort-required")
    documents = json.loads(canonical(documents))
    for document in documents:
        validate_manifest(document)
        require(document["operation"] == "delete" and
                document["deletion"].get("inventory_mode") == "arm-provider-closure-v1"
                and all(row["delete"] for row in document["deletion"]["resource_groups"] +
                        document["deletion"]["resources"]), "cohort-whole-owned-groups-required")
    first = documents[0]
    require(all(document["target"]["factory_id"] == first["target"]["factory_id"] for document in documents),
            "cohort-factory-mismatch")
    require(all(document["source"] == first["source"] for document in documents), "cohort-source-mismatch")
    require(len({document["run_id"] for document in documents}) == len(documents)
            and len({document["manifest_hash"] for document in documents}) == len(documents),
            "cohort-duplicate-child")
    documents = _cohort_order(documents)
    source_root, execution_root, receipt_path = clean_path(source_root), clean_path(execution_root), clean_path(receipt_path)
    require(not execution_root.is_relative_to(source_root) and not source_root.is_relative_to(execution_root),
            "execution-source-isolation-required")
    require(not execution_root.exists(), "new-isolated-execution-directory-required")
    require(not receipt_path.exists() and receipt_path.parent == execution_root
            and receipt_path.name not in {document["run_id"] + ".receipt.json" for document in documents},
            "new-isolated-receipt-required")
    clouds = [cloud_factory(document) for document in documents]
    members = [lock_factory(cloud, document) for cloud, document in zip(clouds, documents)]
    union = _CohortLeases(members)
    aggregate = {"schema": 1, "operation": "delete-factory",
                 "cohort_hash": digest(sorted(document["manifest_hash"] for document in documents)),
                 "factory_id": first["target"]["factory_id"], "source_commit": first["source"]["commit"],
                 "source_ref": first["source"]["ref"], "status": "validating", "started_at": utc_now(),
                 "mutation_started": False, "lock_retained": False, "locks_retained": [], "children": []}
    for document in documents:
        aggregate["children"].append({
            "schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
            "manifest_revision": document["manifest_revision"], "operation": "delete",
            "target": document["target"], "source_commit": document["source"]["commit"],
            "source_ref": document["source"]["ref"], "cohort_hash": aggregate["cohort_hash"],
            "status": "validating", "started_at": utc_now(), "mutation_started": False,
            "deleted_resources": [], "locks_retained": [], "lock_retained": False})
    execution_root.mkdir(parents=True, mode=0o700)
    claimed, claim_attempted = set(), False

    def persist():
        aggregate["updated_at"] = utc_now()
        aggregate["mutation_started"] = any(row["mutation_started"] for row in aggregate["children"])
        aggregate["locks_retained"] = sorted(union.held)
        aggregate["lock_retained"] = bool(union.held)
        for locks, receipt in zip(members, aggregate["children"]):
            receipt["updated_at"] = aggregate["updated_at"]
            receipt["locks_retained"] = sorted(union.held)
            receipt["lock_retained"] = bool(union.held)
            if receipt["run_id"] in claimed:
                locks.store_receipt(receipt)
            write_receipt(execution_root / (receipt["run_id"] + ".receipt.json"), receipt)
        write_receipt(receipt_path, aggregate)

    try:
        persist()
        source_root = verify_source(clouds[0], source_root, first["source"])
        for cloud in clouds:
            cloud.verify_identity()
        union.acquire()
        # Every ownership/closure/enrollment check finishes before the first
        # child is claimed, and every claim finishes before any ARM DELETE.
        for cloud, locks, document in zip(clouds, members, documents):
            validate_manifest(document)
            cloud.verify_identity()
            cloud.assert_no_active_runs(locks.enrollment)
            for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]:
                cloud.assert_no_active_deployments(scope)
            verify_full_inventory(cloud, document)
        union.assert_held()
        for document in documents:
            validate_manifest(document)
        for locks, receipt in zip(members, aggregate["children"]):
            for document in documents:
                validate_manifest(document)
            claim_attempted = True
            locks.claim_run()
            claimed.add(receipt["run_id"])
            receipt["status"] = "running"
        for document in documents:
            validate_manifest(document)
        aggregate["status"] = "running"
        persist()
        for locks, document in zip(members, documents):
            locks.authorize(document)
        for cloud, locks, document, receipt in zip(clouds, members, documents, aggregate["children"]):
            delete_owned_groups(cloud, locks, document, receipt, persist)
            receipt["status"] = "succeeded"
            receipt["finished_at"] = utc_now()
            persist()
        union.assert_held()
        aggregate["status"] = "succeeded"
        aggregate["finished_at"] = utc_now()
        persist()
        union.release()
        persist()
    except BaseException as error:
        aggregate["status"] = "reconciliation-required" if claim_attempted else "blocked"
        aggregate["error_code"] = error.code if isinstance(error, Blocked) else "unexpected-runtime-failure"
        if not claim_attempted:
            try:
                union.release()
            except (Blocked, OSError):
                aggregate["status"] = "reconciliation-required"
                aggregate["error_code"] = "lock-release-reconciliation-required"
        for receipt in aggregate["children"]:
            if receipt["status"] != "succeeded":
                receipt["status"] = aggregate["status"]
                receipt["error_code"] = aggregate["error_code"]
        aggregate["finished_at"] = utc_now()
        try:
            persist()
        except BaseException:
            # Local evidence still names every held scope if durable storage is
            # unavailable; the catalog must retain the entire factory authority.
            aggregate["locks_retained"] = sorted(union.held)
            aggregate["lock_retained"] = bool(union.held)
            for receipt in aggregate["children"]:
                receipt["locks_retained"] = sorted(union.held)
                receipt["lock_retained"] = bool(union.held)
                write_receipt(execution_root / (receipt["run_id"] + ".receipt.json"), receipt)
            write_receipt(receipt_path, aggregate)
    finally:
        for cloud in clouds:
            cloud.tokens.clear()
    return aggregate


def execute(document, source_root, execution_root, receipt_path, cloud=None, lock_factory=BlobLocks):
    document = json.loads(canonical(document))
    validate_manifest(document)
    reasons = operation_blockers(document)
    require(not reasons, reasons[0] if reasons else "unsupported-operation")
    source_root, execution_root, receipt_path = clean_path(source_root), clean_path(execution_root), clean_path(receipt_path)
    require(not execution_root.is_relative_to(source_root) and not source_root.is_relative_to(execution_root),
            "execution-source-isolation-required")
    require(not execution_root.exists(), "new-isolated-execution-directory-required")
    require(not receipt_path.exists() and receipt_path.parent == execution_root,
            "new-isolated-receipt-required")
    cloud = cloud or Cloud(document)
    source_root = verify_source(cloud, source_root, document["source"])
    cloud.verify_identity()
    execution_root.mkdir(parents=True, mode=0o700)
    receipt = {"schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
               "manifest_revision": document["manifest_revision"], "operation": document["operation"],
               "target": document["target"], "source_commit": document["source"]["commit"],
               "status": "validating", "started_at": utc_now(), "mutation_started": False,
               "deleted_resources": [], "locks_retained": []}
    locks = lock_factory(cloud, document)
    claimed = False

    def persist():
        receipt["updated_at"] = utc_now()
        write_receipt(receipt_path, receipt)
        if claimed:
            locks.store_receipt(receipt)

    try:
        persist()
        locks.acquire()
        locks.claim_run()
        claimed = True
        receipt["status"] = "running"
        persist()
        for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]:
            if document["operation"] in ("create-factory", "create-scaleset"):
                status, _, _ = cloud.arm("GET", scope, RG_API, allowed=(200, 404))
                if status == 404:
                    require(scope in document["locks"]["scopes"], "common-dependency-does-not-exist")
                    continue
            cloud.assert_no_active_deployments(scope)
        cloud.assert_no_active_runs(locks.enrollment)
        if document["operation"] == "delete":
            if document["deletion"].get("inventory_mode") == "arm-provider-closure-v1":
                delete_owned_groups(cloud, locks, document, receipt, persist)
            else:
                delete_resources(cloud, locks, document, receipt, persist)
        elif "deployment" in document:
            if document["route"]["kind"] == "gha":
                github_scoped(cloud, locks, document, source_root, receipt, persist)
            else:
                ado_scoped(cloud, locks, document, source_root, receipt, persist)
        elif document["operation"] == "deploy-project":
            ado_project(cloud, locks, document, source_root, receipt, persist)
        else:
            raise Blocked("published-scoped-creation-contract-required")
        locks.authorize(document)
        receipt["status"] = "succeeded"
        persist()
        locks.release()
        receipt["parent_locks_retained"] = sorted(locks.held)
        persist()
        return receipt
    except BaseException as error:
        receipt["status"] = "reconciliation-required" if receipt["mutation_started"] else "blocked"
        receipt["error_code"] = error.code if isinstance(error, Blocked) else "unexpected-runtime-failure"
        if not receipt["mutation_started"]:
            try:
                locks.release()
            except Blocked:
                receipt["error_code"] = "lock-release-reconciliation-required"
        receipt["locks_retained"] = sorted(locks.held)
        try:
            persist()
        except BaseException:
            write_receipt(receipt_path, receipt)
        return receipt
    finally:
        # Clear cached bearer tokens and never materialize plaintext run config.
        cloud.tokens.clear()


def unprotect(raw):
    require(sys.platform == "win32", "windows-current-user-dpapi-required")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    crypt, kernel = ctypes.WinDLL("crypt32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    buffer = ctypes.create_string_buffer(raw)
    source, result = Blob(len(raw), ctypes.cast(buffer, ctypes.c_void_p)), Blob()
    require(crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)),
            "prepared-manifest-decryption-failed")
    try:
        require(result.size <= MAX_DOCUMENT, "manifest-too-large")
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(result.data, 0, result.size)
        kernel.LocalFree(result.data)


def read_manifest(args):
    if args.stdin_manifest:
        require(not sys.stdin.isatty(), "protected-pipe-required")
        raw = sys.stdin.buffer.read(MAX_DOCUMENT + 1)
    else:
        path = clean_path(args.protected_manifest)
        require(path.suffix.lower() == ".dpapi" and path.is_file() and path.stat().st_size <= MAX_DOCUMENT,
                "bounded-dpapi-manifest-required")
        raw = unprotect(path.read_bytes())
    require(len(raw) <= MAX_DOCUMENT, "manifest-too-large")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate-json-key")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Blocked("nonfinite-json-value")))
    except (UnicodeError, ValueError):
        raise Blocked("invalid-manifest-json") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("capabilities")
    worker = subparsers.add_parser("worker")
    worker.add_argument("--source-root", required=True)
    worker.add_argument("--expected-run", required=True)
    worker.add_argument("--expected-manifest-hash", required=True)
    for name in ("inspect", "execute"):
        subparser = subparsers.add_parser(name)
        inputs = subparser.add_mutually_exclusive_group(required=True)
        inputs.add_argument("--stdin-manifest", action="store_true")
        inputs.add_argument("--protected-manifest")
        subparser.add_argument("--expected-orchestrator", choices=("ado", "gha"),
                               help="Require the reviewed manifest to use this orchestrator; never rewrite its route.")
        if name == "execute":
            subparser.add_argument("--source-root", required=True)
            subparser.add_argument("--execution-root", required=True)
            subparser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "capabilities":
            output = capabilities()
        elif args.command == "worker":
            args.stdin_manifest, args.protected_manifest = True, None
            output = run_deployment_worker(read_manifest(args), clean_path(args.source_root),
                                           args.expected_run, args.expected_manifest_hash)
        else:
            document = validate_manifest(read_manifest(args))
            if args.expected_orchestrator:
                require(document["route"]["kind"] == args.expected_orchestrator, "orchestrator-mismatch")
            if args.command == "inspect":
                blockers = operation_blockers(document)
                output = {"contract": CONTRACT, "run_id": document["run_id"], "manifest_valid": True,
                          "execution_supported": not blockers, "blockers": blockers,
                          "requires_live_checks": ["published-source", "authenticated-identity", "lock-enrollment",
                                                   "exclusive-physical-locks", "fresh-exact-inventory"]}
            else:
                output = execute(document, args.source_root, args.execution_root, args.receipt)
                if output.get("status") == "succeeded" and args.protected_manifest:
                    clean_path(args.protected_manifest).unlink()
        print(json.dumps(output, sort_keys=True, separators=(",", ":")))
        return 0 if output.get("status") not in ("blocked", "reconciliation-required") else 2
    except (Blocked, OSError, KeyError, TypeError, ValueError):
        error = sys.exc_info()[1]
        print(json.dumps({"status": "blocked", "error_code": error.code if isinstance(error, Blocked)
                          else "invalid-runtime-input"}, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
