#!/usr/bin/env python3
"""AIFACTORY_LIFECYCLE_CONTRACT=1: frozen, scoped, fail-closed execution.

See factory_lifecycle_contract.txt beside this module for the wire format and
operator-provisioned coordination prerequisite (Blob by default; explicit
single-writer private repository state is also supported). Import, --help,
capabilities and inspect never authenticate, deploy, or modify a repository.
"""

from __future__ import annotations

import argparse
import base64
import copy
import ctypes
import errno
import fnmatch
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import types
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPSConnection, IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from urllib.response import addinfourl
from uuid import uuid4


CONTRACT = 1
SELECTIVE_PROJECT_DELETE = "selective-project-resources-v1"
PROJECT_NETWORK_TYPES = {"microsoft.network/networksecuritygroups", "microsoft.network/routetables"}
# ARM back-references name a dependent (deleted first), never a dependency of this resource.
REVERSE_LINKS = {
    "microsoft.network/networkinterfaces": ("virtualMachine", "privateEndpoint", "privateLinkService"),
    "microsoft.network/publicipaddresses": ("ipConfiguration",),
    "microsoft.compute/disks": ("managedBy", "managedByExtended"),
    "microsoft.network/networksecuritygroups": ("networkInterfaces", "subnets"),
    "microsoft.network/virtualnetworks/subnets": ("ipConfigurations", "ipConfigurationProfiles", "privateEndpoints",
                                                  "serviceAssociationLinks", "resourceNavigationLinks",
                                                  "applicationGatewayIPConfigurations"),
}
MAX_DOCUMENT = 8 * 1024 * 1024
RECEIPT_REPLACE_ATTEMPTS = 20
RECEIPT_REPLACE_RETRY_SECONDS = 0.25
READ_TRANSPORT_ATTEMPTS = 3
READ_TRANSPORT_RETRY_DELAYS = (0.25, 0.5)
# Windows getaddrinfo "no data record": a resolver hiccup for an ARM host that always resolves.
WSANO_DATA = 11004
# A retry-admission budget, not cancellation of an in-flight socket operation.
READ_TRANSPORT_RETRY_WINDOW_SECONDS = 180
REMOTE_SOCKET_TIMEOUT_SECONDS = 60
# Read-ahead threads for one resource-closure walk, so also its most ARM reads in flight at once.
RESOURCE_CLOSURE_READ_WORKERS = 8
# How a pooled connection the server already closed while idle fails on its next request.
STALE_CONNECTION_ERRORS = (RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)
ARM = "https://management.azure.com"
SOURCE_ORIGIN = "https://github.com/jostrm/azure-enterprise-scale-ml"
GUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
RG_ID = re.compile(r"/subscriptions/(" + GUID + r")/resourceGroups/([A-Za-z0-9_.()-]{1,90})", re.I)
RESOURCE_ID = re.compile(RG_ID.pattern + r"/providers/([A-Za-z0-9.]+)/([A-Za-z0-9]+)/([A-Za-z0-9_.()-]{1,128})", re.I)
ARM_SEGMENT = r"(?!\.{1,2}(?:/|$))[A-Za-z0-9_.()-]+"
ARM_RESOURCE_PATH = r"/providers/[A-Za-z0-9.]+(?:/" + ARM_SEGMENT + "/" + ARM_SEGMENT + r")+"
# DNS apex/wildcard names are literal ARM names, not URL syntax or arbitrary child types.
DNS_ZONE_NAME = r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*"
DNS_WILDCARD_NAME = r"\*(?:\.[A-Za-z0-9_-]+)*"
DNS_SPECIAL_NAME = r"(?:@|" + DNS_WILDCARD_NAME + ")"
# CNAME cannot coexist with the SOA at the apex; NS and SOA cannot be wildcards.
DNS_RECORD_PATH = (r"/providers/Microsoft.Network/(?:privateDnsZones/" + DNS_ZONE_NAME
                   + r"/(?:SOA/@|CNAME/" + DNS_WILDCARD_NAME
                   + r"|(?:A|AAAA|MX|PTR|SRV|TXT)/" + DNS_SPECIAL_NAME + r")"
                   + r"|dnsZones/" + DNS_ZONE_NAME
                   + r"/(?:(?:SOA|NS)/@|CNAME/" + DNS_WILDCARD_NAME
                   + r"|(?:A|AAAA|CAA|MX|PTR|SRV|TXT)/" + DNS_SPECIAL_NAME + r"))"
                   + r"(?:" + ARM_RESOURCE_PATH + r")*")
NESTED_ID = re.compile(RG_ID.pattern + r"(?:" + ARM_RESOURCE_PATH + "|" + DNS_RECORD_PATH + ")", re.I)
SUBSCRIPTION_RESOURCE_ID = re.compile(r"/subscriptions/(" + GUID
    + r")/providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9_.()%-]+/[A-Za-z0-9_.()%-]+)+", re.I)
EXACT_BOOTSTRAP_CONTRACT = "exact-bootstrap-resources-v2"
PRESERVATION_PERMIT_CONTRACT = "reviewed-bootstrap-preservation-v1"
DNS_SOA_PERMIT_CONTRACT = "reviewed-bootstrap-dns-soa-preservation-v1"
DNS_SOA_ZONE_ID = re.compile(RG_ID.pattern + r"/providers/Microsoft.Network/privateDnsZones/" + DNS_ZONE_NAME, re.I)
DNS_RECORD_TYPES = ("a", "aaaa", "cname", "mx", "ptr", "soa", "srv", "txt")
NON_RESOURCE_METADATA = {"microsoft.compute/virtualmachines/metricdefinitions"}
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


def safe_instance_diagnostic(code, value):
    if (code not in ("bootstrap-resource-instance-changed", "scoped-github-run-failed", "scoped-ado-run-failed")
            or type(value) is not dict
            or set(value) != {"resource_id", "failed_comparisons"}):
        return None
    identifier, fields = value["resource_id"], value["failed_comparisons"]
    if (type(identifier) is not str or not 1 <= len(identifier) <= 2048
            or type(fields) is not list or not 1 <= len(fields) <= 2
            or any(type(field) is not str or field not in ("body_hash", "etag") for field in fields)
            or len(set(fields)) != len(fields)):
        return None
    pattern = (r"/subscriptions/" + GUID + r"/resourcegroups/[A-Za-z0-9_.()-]{1,90}"
               r"(?:/providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9_.()-]+/[A-Za-z0-9_.()@-]+)+)?")
    if not re.fullmatch(pattern, identifier, re.I | re.A) or any(part in (".", "..") for part in identifier.split("/")):
        return None
    return {"resource_id": identifier,
            "failed_comparisons": [field for field in ("body_hash", "etag") if field in fields]}


class Blocked(ValueError):
    """A stable, non-secret error code suitable for a persistent receipt."""

    def __init__(self, code, *, error_diagnostic=None):
        self.code = code
        self.error_diagnostic = safe_instance_diagnostic(code, error_diagnostic)
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Blocked(code)


def require_bootstrap_instance(identifier, **comparisons):
    failed = [field for field, matches in comparisons.items() if not matches]
    if failed:
        raise Blocked("bootstrap-resource-instance-changed", error_diagnostic={
            "resource_id": identifier, "failed_comparisons": failed})


def failure_fields(error, fallback):
    code = error.code if isinstance(error, Blocked) else fallback
    result = {"error_code": code}
    detail = safe_instance_diagnostic(code, getattr(error, "error_diagnostic", None))
    if detail is not None:
        result["error_diagnostic"] = detail
    return result


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


def single_writer(document):
    return document.get("locks", {}).get("coordination_mode") == "single-writer"


def repository_state_module():
    spec = importlib.util.spec_from_file_location("provider_repository_state", Path(__file__).with_name("provider_repository_state.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def factory_deletion_module():
    spec = importlib.util.spec_from_file_location(
        "factory_deletion_pipeline", Path(__file__).with_name("factory_deletion_pipeline.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.fl = types.SimpleNamespace(**globals())
    return module


def freeze_factory_deletion_pipeline(cloud, document, ownership_records, registered_projects):
    return factory_deletion_module().freeze(cloud, document, ownership_records, registered_projects)


def execute_factory_deletion_cohort(documents, source_root, execution_root, receipt_path,
                                    cloud_factory=None, lock_factory=None):
    return factory_deletion_module().execute_cohort(
        documents, source_root, execution_root, receipt_path, cloud_factory or Cloud, lock_factory)


def freeze_bootstrap_teardown(cloud, document):
    return factory_deletion_module().freeze_teardown(cloud, document)


def validate_bootstrap_teardown(document, require_unexpired=False):
    return factory_deletion_module().validate_teardown(document, require_unexpired=require_unexpired)


def teardown_digest(document):
    return factory_deletion_module().teardown_digest(document)


def execute_bootstrap_teardown(document, receipt_path, cloud=None, sleep=time.sleep):
    return factory_deletion_module().execute_teardown(document, receipt_path, cloud, sleep)


def scoped_template(document):
    return SCOPED_SOURCE + ("single-writer-" if single_writer(document) else "") + document["route"]["kind"] + ".yml"


def coordination(cloud, document):
    return RepositoryCoordination(cloud, document) if single_writer(document) else BlobLocks(cloud, document)


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
    if single_writer(document):
        require(all(locks.get(k) == v for k, v in repository_state_module().coordinates(repository).items())
                and set(locks) <= {"provider", "coordination_mode", "repository", "state_ref", "coordination_hash",
                                   "revision", "scopes", "common_dependencies"}, "invalid-single-writer-coordinates")
        if document["operation"] == "delete":
            require("deployment" not in document and "deletion_scope" not in document
                    and document.get("deletion", {}).get("inventory_mode") == "arm-provider-closure-v1",
                    "single-writer-whole-owned-groups-required")
        else:
            require("deployment" in document, "single-writer-scoped-deployment-required")
    else:
        require(locks.get("provider") == "azure-blob-lease"
                and locks.get("coordination_mode", "blob") == "blob", "distributed-lock-provider-required")
        validate_blob_coordinates(locks)
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


def validate_blob_coordinates(locks):
    require(isinstance(locks.get("account_url"), str) and re.fullmatch(
        r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net", locks["account_url"]), "unsupported-lock-endpoint")
    require(isinstance(locks.get("container"), str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]",
                                                                 locks["container"]), "invalid-lock-container")
    require(isinstance(locks.get("coordination_blob"), str)
            and re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,255}", locks["coordination_blob"])
            and ".." not in locks["coordination_blob"], "invalid-enrollment-blob")


def validate_project(document):
    target, config = document["target"], document["config"]
    section = "dev" if target["environment"] == "dev" else "stage_prod"
    exact = "test" if target["environment"] == "stage" else target["environment"]
    require(isinstance(config.get(section, config.get(exact)), dict), "exact-config-environment-required")
    values = persona_helper(Path(__file__).resolve().parents[2]).selected_config(config, target["environment"])
    identity_values = {**config.get(section, {}), **config.get(exact, {})}
    subscription_key = {"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}[target["environment"]]
    expected = {"tenantId": target["tenant_id"], subscription_key: target["subscription_id"],
                "project_number_000": target["project_ids"][0], "admin_location": target["region"],
                "admin_aifactoryPrefixRG": target["prefix"], "admin_aifactorySuffixRG": "-" + target["suffix"]}
    for key, value in expected.items():
        actual = str(identity_values.get(key, ""))
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
        exact = "test" if target["environment"] == "stage" else target["environment"]
        require(isinstance(config.get(section, config.get(exact)), dict), "exact-config-environment-required")
        values = persona_helper(Path(__file__).resolve().parents[2]).selected_config(config, target["environment"])
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
    if plan.get("bootstrap_foundation", {}).get("contract") == EXACT_BOOTSTRAP_CONTRACT:
        validate_exact_bootstrap(document)
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
        if parameters.get("commonNetworkProfile") == "preserve-v1" or "network_preservation" in step:
            proof = step.get("network_preservation")
            require(template == COMMON_TEMPLATES["12-networkCommon"] and isinstance(proof, dict)
                    and proof.get("contract") == "preserve-v1-runtime-proof"
                    and hash_value(proof.get("source_payload_sha256")),
                    "runtime-network-preservation-proof-required")
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
    validate_foundry_lifecycle(document)


def protect_coordination_storage(document):
    """Never destroy the account/RG that holds this operation's live leases."""
    if single_writer(document):
        return
    account = urlsplit(document["locks"]["account_url"]).hostname.split(".")[0].lower()
    suffix = "/providers/microsoft.storage/storageaccounts/" + account
    data = document["deletion"]
    protected_groups = set()
    for item in data["resources"]:
        identifier = str(item.get("id", "")).lower()
        if suffix not in identifier:
            continue
        tail = identifier.split(suffix, 1)[1]
        if tail and not tail.startswith("/"):
            continue
        protected_groups.add(arm_scope(identifier))
        require(item.get("delete") is not True, "coordination-storage-delete-forbidden")
    require(not any(item.get("delete") is True and str(item.get("id", "")).lower() in protected_groups
                    for item in data["resource_groups"]), "coordination-resource-group-delete-forbidden")


def validate_deletion(document):
    if document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
        return factory_deletion_module().validate(document)
    if "deletion_scope" in document:
        return validate_project_deletion(document)
    data = document.get("deletion")
    require(isinstance(data, dict) and data.get("inventory_complete") is True, "complete-inventory-required")
    require(data.get("revision") == document["manifest_revision"], "inventory-revision-mismatch")
    resources, groups = data.get("resources"), data.get("resource_groups")
    require(isinstance(resources, list) and isinstance(groups, list) and groups, "inventory-resources-required")
    require(all(isinstance(item, dict) for item in groups + resources), "invalid-inventory-entry")
    protect_coordination_storage(document)
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
        "coordination_modes": ["blob", "single-writer"],
        "single_writer": "provider-repository-cas-v1",
        "single_writer_operations": ["create-factory", "create-scaleset", "deploy-project", "delete"],
        "single_writer_deletion": "provider-repository-cas-cohort-v1",
        "project_routes": ["ado", "gha"],
        "project_environments": ["dev", "stage", "prod"],
        "persona_access": "persona-groups-v1",
        "persona_manifest_source": "reviewed-consumer-commit-frozen-in-protected-plan",
        "scoped_worker_os": ["linux"], "scoped_runners": ["hosted", "self-hosted"],
        "scoped_group_ownership_receipt": "resource-group-ownership-v1",
        "network_preservation": "preserve-v1-runtime-proof",
        "bootstrap_ownership": "created-group-ownership-v1",
        "bootstrap_resource_ownership": EXACT_BOOTSTRAP_CONTRACT,
        "bootstrap_preservation_permit": PRESERVATION_PERMIT_CONTRACT,
        "bootstrap_dns_soa_preservation_permit": DNS_SOA_PERMIT_CONTRACT,
        "resource_closure": "arm-resource-only-closure-v2",
        "delete_leaf_types": sorted(LEAF_TYPES), "delete_empty_owned_resource_groups": True,
        "delete_owned_resource_groups": "arm-provider-closure-v1",
        "factory_deletion_dependencies": "search-shared-private-links-first-v1",
        "factory_deletion_pipeline": "ordered-project-pipelines-v1",
        "factory_deletion_group_protection": "case-insensitive-name-globs-v1",
        "factory_deletion_connectivity_retention": "whole-connectivity-resource-groups-v1",
        "factory_deletion_pipeline_coordination_modes": ["blob"],
        "factory_deletion_access_hub": "factory-owned-access-hub-v1",
        "factory_deletion_shared_hub_links": "shared-hub-spoke-links-v1",
        "bootstrap_operator_teardown": "bootstrap-operator-teardown-v1",
        "factory_deletion_coordination_modes": ["blob", "single-writer"],
        "selective_project_deletion": SELECTIVE_PROJECT_DELETE,
        "factory_cohort": "physical-lease-cohort-v1",
        "creation": "frozen-arm-deployment-plan-v1", "shared_remote_namespaced_auth": True,
        "native_foundry": "identity-receipt-account-uami-instance-closure-project-v4",
        "native_foundry_identity_producer": "source-projected-project-uami-instance-v2",
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


class KeepAliveHTTPSHandler(HTTPSHandler):
    """Pooled keep-alive HTTPS for GET/HEAD (Object Pool); every other request is unchanged.

    urllib opens a TCP connection and TLS session per request and sends `Connection: close`,
    which cost minutes across a closure's thousands of reads. A read here borrows an idle
    connection to its host (one per concurrent reader), drains the body up to `max_body`,
    and returns the connection only when the response was complete and the server keeps it
    open. Writes and proxy-tunnelled requests keep urllib's own path, and HTTP errors still
    flow through the opener's processors (HTTPError, NoRedirect).
    """

    def __init__(self, context=None, connection_factory=HTTPSConnection, max_body=MAX_DOCUMENT + 1, max_idle=16):
        super().__init__(context=context)
        self._factory, self._max_body, self._max_idle = connection_factory, max_body, max_idle
        self._idle, self._lock = {}, threading.Lock()

    def https_open(self, request):
        method = request.get_method()
        if method not in ("GET", "HEAD") or request.data is not None or request._tunnel_host:
            return super().https_open(request)
        # The same headers urllib's do_open sends, without its `Connection: close`.
        headers = dict(request.unredirected_hdrs)
        headers.update({name: value for name, value in request.headers.items() if name not in headers})
        headers = {name.title(): value for name, value in headers.items()}
        timeout = socket.getdefaulttimeout() if request.timeout is socket._GLOBAL_DEFAULT_TIMEOUT else request.timeout
        for attempt in (1, 2):
            connection, reused = self._borrow(request.host, timeout, fresh=attempt > 1)
            answered = False
            try:
                try:
                    connection.request(method, request.selector, headers=headers)
                except OSError as error:
                    raise URLError(error)
                response = connection.getresponse()
                answered = True
                body = response.read(self._max_body)
                reusable = response.isclosed() and not response.will_close
                response.close()
            except BaseException as error:
                connection.close()
                reason = error.reason if isinstance(error, URLError) else error
                if reused and not answered and isinstance(reason, STALE_CONNECTION_ERRORS):
                    continue  # the server closed this idle connection; a read is safe to send again
                raise
            self._give_back(request.host, connection, reusable)
            result = addinfourl(io.BytesIO(body), response.headers, request.full_url, response.status)
            result.msg = response.reason
            return result

    def _borrow(self, host, timeout, fresh=False):
        with self._lock:
            idle = self._idle.get(host)
            connection = idle.pop() if idle and not fresh else None
        if connection is None:
            return self._factory(host, timeout=timeout, context=self._context), False
        connection.timeout = timeout
        if connection.sock is not None:
            connection.sock.settimeout(timeout)
        return connection, True

    def _give_back(self, host, connection, reusable):
        if reusable:
            with self._lock:
                idle = self._idle.setdefault(host, [])
                if len(idle) < self._max_idle:
                    idle.append(connection)
                    return
        connection.close()


class Cloud:
    """No shell expansion, CLI output passthrough, interactive auth or write retries."""

    closure_read_workers = RESOURCE_CLOSURE_READ_WORKERS

    def __init__(self, document, command_runner=None, opener=None, expected_object_id=None):
        self.document = document
        self.runner = command_runner or subprocess.run
        self.opener = opener or build_opener(NoRedirect, KeepAliveHTTPSHandler())
        self.tokens = {}
        self.token_expiries = {}
        # Closure reads run on worker threads: one refresh per audience, never a torn cache.
        self.token_lock = threading.RLock()
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
        with self.token_lock:
            return self._token(audience)

    def _token(self, audience):
        require(not single_writer(self.document) or audience.rstrip("/") != "https://storage.azure.com",
                "single-writer-storage-access-forbidden")
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
        with self.token_lock:
            self.tokens.clear()
            self.token_expiries.clear()
            self.token(ARM)

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        parsed = urlsplit(url)
        deleting = (self.document.get("operation") == "delete"
                    or self.document.get("contract") == "bootstrap-operator-teardown-v1")
        require(not (deleting and (parsed.hostname or "").lower() in ("graph.microsoft.com", "graph.windows.net")),
                "factory-deletion-entra-mutations-forbidden")
        allowed_hosts = {urlsplit(ARM).netloc, "dev.azure.com"}
        # An operator teardown has no lease store, so no storage endpoint is trusted.
        if self.document.get("locks") and not single_writer(self.document):
            allowed_hosts.add(urlsplit(self.document["locks"]["account_url"]).netloc)
        require(parsed.scheme == "https" and parsed.netloc in allowed_hosts and not parsed.username
                and not parsed.password and not parsed.fragment, "untrusted-service-endpoint")
        body = canonical(data) if data is not None else None
        readonly = method in ("GET", "HEAD")
        attempts = READ_TRANSPORT_ATTEMPTS if readonly else 1
        started = time.monotonic()
        deadline = started + READ_TRANSPORT_RETRY_WINDOW_SECONDS
        for attempt in range(1, attempts + 1):
            # Revalidate/refresh the identity token after any backoff.
            request_headers = {"Authorization": "Bearer " + self.token(audience), "Content-Type": "application/json"}
            request_headers.update(headers or {})
            request = Request(url, method=method, data=body, headers=request_headers)
            remaining = deadline - time.monotonic()
            require(not readonly or remaining > 0, "remote-request-unverified")
            timeout = min(REMOTE_SOCKET_TIMEOUT_SECONDS, remaining) if readonly else REMOTE_SOCKET_TIMEOUT_SECONDS
            try:
                try:
                    response = self.opener.open(request, timeout=timeout)
                except HTTPError as error:
                    if error.code not in allowed:
                        try:
                            error.close()
                        finally:
                            raise Blocked("remote-request-failed-" + str(error.code)) from None
                    response = error
                with response:
                    status, response_headers = response.code, dict(response.headers)
                    raw = response.read(MAX_DOCUMENT + 1)
                break
            except (URLError, OSError, IncompleteRead) as error:
                reason = error.reason if isinstance(error, URLError) else error
                if isinstance(reason, (ssl.SSLError, PermissionError)):
                    transient = False
                elif isinstance(reason, socket.gaierror):
                    transient = reason.errno in (socket.EAI_AGAIN, WSANO_DATA)
                else:
                    transient = isinstance(reason, (TimeoutError, ConnectionResetError, ConnectionAbortedError,
                                                     ConnectionRefusedError, BrokenPipeError, IncompleteRead)) or (
                        isinstance(reason, OSError) and reason.errno in (
                            errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNABORTED, errno.ECONNREFUSED,
                            errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.EPIPE))
                delay = READ_TRANSPORT_RETRY_DELAYS[attempt - 1] if attempt < attempts else 0
                retry = readonly and transient and attempt < attempts and time.monotonic() + delay < deadline
                api = parse_qs(parsed.query).get("api-version", [])
                api = api[0] if len(api) == 1 and re.fullmatch(
                    r"(?:\d{4}-\d{2}-\d{2}(?:-preview)?|\d+\.\d+(?:-preview(?:\.\d+)?)?)", api[0]) else None
                print(json.dumps({
                    "event": "remote-request-transport-failure", "method": method, "host": parsed.hostname,
                    "path": parsed.path, "api_version": api, "attempt": attempt,
                    "exception_type": type(error).__name__, "reason_type": type(reason).__name__,
                    "errno": reason.errno if isinstance(reason, OSError) and type(reason.errno) is int else None,
                    "elapsed_seconds": round(time.monotonic() - started, 3), "retrying": retry,
                }, sort_keys=True), file=sys.stderr, flush=True)
                if not retry:
                    raise Blocked("remote-request-unverified") from None
                time.sleep(delay)
        require(status in allowed, "unexpected-remote-status")
        require(len(raw) <= MAX_DOCUMENT, "remote-response-too-large")
        if not raw:
            return status, response_headers, None
        try:
            return status, response_headers, json.loads(raw)
        except ValueError:
            raise Blocked("invalid-remote-json") from None

    def state_request(self, kind, method, endpoint, body, allowed):
        require(single_writer(self.document), "single-writer-not-selected")
        if kind == "gha":
            url = "https://api.github.com/" + endpoint
            token = (os.environ.get("GH_TOKEN", "") if self.pipeline_identity else
                     self.command(["gh", "auth", "token", "--hostname", "github.com"]))
        else:
            url = endpoint
            token = (os.environ.get("AIFACTORY_STATE_TOKEN", "") if self.pipeline_identity else
                     self.token("499b84ac-1321-427f-aa17-267ca6975798"))
        require(token and urlsplit(url).hostname == ("api.github.com" if kind == "gha" else "dev.azure.com"),
                "single-writer-provider-auth-required")
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                   "Accept": "application/vnd.github+json" if kind == "gha" else "application/json"}
        try:
            response = self.opener.open(Request(url, method=method, data=canonical(body) if body is not None else None,
                                                headers=headers), timeout=60)
        except HTTPError as error:
            response = error
        except (URLError, OSError, TimeoutError):
            raise Blocked("single-writer-provider-write-or-read-uncertain") from None
        with response:
            status = response.code
            raw, incoming = response.read(MAX_DOCUMENT + 1), dict(response.headers)
        require(status in allowed, "single-writer-provider-request-failed-" + str(status))
        require(len(raw) <= MAX_DOCUMENT, "single-writer-provider-response-too-large")
        try:
            return status, incoming, json.loads(raw) if raw else None
        except (ValueError, UnicodeError):
            raise Blocked("single-writer-provider-response-invalid") from None

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

    def provider_operations(self, namespace):
        _, _, body = self.request("GET", ARM + "/providers/Microsoft.Authorization/providerOperations/"
                                  + quote(namespace, safe=".")
                                  + "?api-version=2022-04-01&%24expand=resourceTypes", ARM)
        require(isinstance(body, dict) and isinstance(body.get("operations"), list)
                and isinstance(body.get("resourceTypes"), list), "incomplete-provider-operations")
        operations = list(body["operations"])
        for row in body["resourceTypes"]:
            require(isinstance(row, dict) and isinstance(row.get("operations"), list),
                    "incomplete-provider-operations")
            operations.extend(row["operations"])
        require(all(isinstance(row, dict) and isinstance(row.get("name"), str) for row in operations),
                "incomplete-provider-operations")
        return sorted({row["name"].lower() for row in operations if row.get("isDataAction") is not True})

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
                error = body.get("error") if isinstance(body, dict) else None
                # Diagnostic Settings documents a top-level ErrorResponse, unlike ARM's error envelope.
                if (isinstance(body, dict) and "error" not in body
                        and path.lower().endswith("/providers/microsoft.insights/diagnosticsettings")):
                    error = body
                code = error.get("code") if isinstance(error, dict) else None
                require(extension and isinstance(code, str) and code in UNSUPPORTED_COLLECTION_CODES
                        and not ("error" in body and "code" in body), "unsupported-child-inventory-endpoint")
                return [], code
            # This Key Vault ARM collection returns a JSON-encoded array,
            # rather than the normal ARM ListResult envelope.
            if (path.lower().endswith("/eventgridfilters") and isinstance(body, str)
                    and resource_type_from_id(path + "/entry") == "microsoft.keyvault/vaults/eventgridfilters"):
                try:
                    decoded = json.loads(body)
                except ValueError:
                    raise Blocked("incomplete-child-inventory") from None
                require(isinstance(decoded, list), "incomplete-child-inventory")
                body = {"value": decoded}
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


def resource_references(body):
    """Resource IDs are dependencies, including provider-owned external links."""
    result = set()

    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.lower().startswith("/subscriptions/"):
            require("%" not in value and not any(part in (".", "..") for part in value.split("/")),
                    "invalid-resource-reference")
            require(RG_ID.fullmatch(value) or NESTED_ID.fullmatch(value)
                    or SUBSCRIPTION_RESOURCE_ID.fullmatch(value)
                    or re.fullmatch(r"/subscriptions/" + GUID, value, re.I),
                    "invalid-resource-reference")
            result.add(value.lower())

    visit(body)
    return result


class ClosureReads:
    """Read-ahead for one resource-closure walk (Proxy over the cloud's read calls).

    The walk still makes and consumes every read in its serial order. A read may only start
    earlier, on at most `workers` threads, and each started read is consumed at most once;
    its outcome (a value, Blocked or any other error) surfaces where the serial walk makes
    that call. So the closure, its digests, its insertion order and its failure codes are
    those of a serial walk over the same responses. With one worker every read runs inline.
    """

    def __init__(self, cloud, workers):
        self.cloud, self.started, self.consumed = cloud, {}, set()
        self.pool = (ThreadPoolExecutor(max_workers=workers, thread_name_prefix="aifactory-closure-read")
                     if workers > 1 else None)

    def run(self, read):
        name, args, options = read
        return getattr(self.cloud, name)(*args, **dict(options))

    def prefetch(self, read):
        if self.pool is not None and read not in self.started and read not in self.consumed:
            self.started[read] = self.pool.submit(self.run, read)

    def get(self, read):
        if self.pool is None:
            return self.run(read)
        future = self.started.pop(read, None) or self.pool.submit(self.run, read)
        self.consumed.add(read)
        return future.result()

    def close(self):
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)


def collect_resource_closure(cloud, scopes, resource_versions=None):
    """Complete registered child-resource closure, including scoped extensions.

    Unsupported list endpoints fail closed. Known inline ARM child operations
    are covered by the full parent body fingerprint, not invented resources.
    Reads run ahead on the cloud's bounded `closure_read_workers` pool (ClosureReads);
    a cloud without one reads serially.
    """
    workers = getattr(cloud, "closure_read_workers", 1)
    reader = ClosureReads(cloud, workers if type(workers) is int else 1)
    try:
        return _collect_resource_closure(reader, scopes, resource_versions or {})
    finally:
        reader.close()


def _collect_resource_closure(reader, scopes, resource_versions):
    schemas, operations, resource_capabilities, versions, bodies = {}, {}, {}, {}, {}
    closure = {"providers": {}, "collections": {}, "resources": {}, "groups": {}, "references": {}, "inline": {}}
    scope_ids = {scope.lower() for scope in scopes}
    singleton = {
        "microsoft.storage/storageaccounts/blobservices": "default",
        "microsoft.storage/storageaccounts/fileservices": "default",
        "microsoft.storage/storageaccounts/queueservices": "default",
        "microsoft.storage/storageaccounts/tableservices": "default",
        "microsoft.storage/storageaccounts/managementpolicies": "default",
    }
    # Audited ARM embedded collections, not independently addressable resources.
    # VirtualNetworkGatewayPropertiesFormat owns VirtualNetworkGatewayIPConfiguration.
    inline = {
        "microsoft.keyvault/vaults/accesspolicies": ("properties", "accessPolicies"),
        "microsoft.network/virtualnetworks/subnets/delegations": ("properties", "delegations"),
        "microsoft.network/virtualnetworkgateways/ipconfigurations": ("properties", "ipConfigurations"),
    }
    terminal_extensions = {kind.lower() for kind, _ in EXTENSION_COLLECTIONS}
    ahead = reader.pool is not None
    planned = set()  # queued resources whose child reads were already started

    def arm_read(path, api, allowed=None):
        return "arm", ("GET", path, api), () if allowed is None else (("allowed", allowed),)

    def collection_read(path, api, extension=False, single=None):
        if single:
            return arm_read(path + "/" + single, api, (200, 404))
        return "collection", (path, api), (("extension", extension),)

    def provider_reads(namespace):
        return ("provider_schema", (namespace,), ()), ("provider_operations", (namespace,), ())

    def provider(namespace):
        key = namespace.lower()
        if key not in schemas:
            schema_read, operations_read = provider_reads(namespace)
            reader.prefetch(operations_read)
            body = reader.get(schema_read)
            entries = {}
            for row in body["resourceTypes"]:
                require(isinstance(row, dict) and isinstance(row.get("resourceType"), str)
                        and isinstance(row.get("apiVersions"), list), "incomplete-provider-schema")
                entries[row["resourceType"].lower()] = row["apiVersions"]
                resource_capabilities[key + "/" + row["resourceType"].lower()] = {
                    value.strip().lower() for value in str(row.get("capabilities", "")).split(",")}
            schemas[key] = entries
            operations[key] = set(reader.get(operations_read))
            require(operations[key] and all(isinstance(name, str) and name.startswith(key + "/")
                                            for name in operations[key]), "incomplete-provider-operations")
            closure["providers"][key] = digest({"schema": body, "operations": sorted(operations[key])})
        return schemas[key]

    def resource_kind(kind):
        if kind in NON_RESOURCE_METADATA:
            return "metadata"
        namespace, relative = kind.split("/", 1)
        provider(namespace)
        names = operations[namespace.lower()]
        reads = kind.lower() + "/read" in names
        writes = any(kind.lower() + "/" + action in names for action in ("write", "delete"))
        if reads and writes:
            return "resource"
        if not any(name.startswith(kind.lower() + "/") for name in names):
            require("supportstags" in resource_capabilities.get(kind.lower(), set()),
                    "provider-resource-kind-unclassified")
            return "resource"
        require(reads or not writes and kind.lower() + "/action" in names,
                "provider-resource-kind-unclassified")
        return "readonly" if reads else "operation"

    def version(kind, parent_api=None):
        namespace, relative = kind.split("/", 1)
        available = provider(namespace).get(relative.lower(), [])
        stable = sorted((value for value in available if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)), reverse=True)
        fallback = sorted((value for value in available if re.fullmatch(r"\d{4}-\d{2}-\d{2}-preview", value)), reverse=True)
        if not stable and not fallback and parent_api and resource_kind(kind) != "operation":
            return parent_api
        require(stable or fallback, "resource-api-version-not-discoverable")
        return (stable or fallback)[0]

    def child_steps(resource_id, kind):
        """The walk's child-inventory steps for one resource, planned lazily in serial order."""
        namespace, relative = kind.split("/", 1)
        key = resource_id.lower()
        if kind == "microsoft.search/services":
            # This documented ARM child must be inventoried even when omitted
            # from provider discovery; a failed list never means an empty list.
            yield "collection", resource_id + "/sharedPrivateLinkResources", "2025-05-01", None
        for child in sorted(provider(namespace)):
            tail = child.removeprefix(relative + "/")
            if not child.startswith(relative + "/") or "/" in tail:
                continue
            full_type = namespace + "/" + child
            if full_type == "microsoft.search/services/sharedprivatelinkresources":
                continue
            if full_type in inline:
                yield "inline", key + "/" + tail, None, None
            elif resource_kind(full_type) != "resource":
                yield "metadata", key + "/" + tail, full_type, None
            else:
                yield "collection", resource_id + "/" + tail, version(full_type), singleton.get(full_type)

    def extension_steps(scope):
        for kind, api in EXTENSION_COLLECTIONS:
            yield (scope + "/providers/" + kind, api,
                   not (RG_ID.fullmatch(scope) and kind == "Microsoft.Insights/diagnosticSettings"))

    def read_children_ahead(resource_id, kind):
        # Planning is pure only once the provider is loaded; until then start the provider reads.
        if not ahead or resource_id.lower() in planned:
            return
        namespace = kind.split("/", 1)[0]
        if namespace not in closure["providers"]:
            for read in provider_reads(namespace):
                reader.prefetch(read)
            return
        planned.add(resource_id.lower())
        try:
            for step, path, api, single in child_steps(resource_id, kind):
                if step == "collection":
                    reader.prefetch(collection_read(path, api, single=single))
        except Exception:  # the serial walk raises it at its own position
            pass

    def read_extensions_ahead(scope):
        for path, api, applicable in extension_steps(scope):
            if applicable:
                reader.prefetch(collection_read(path, api, extension=True))

    queue = []

    def enqueue(resource_id):
        queue.append(resource_id)
        if ahead:
            kind = resource_type_from_id(resource_id)
            reader.prefetch(arm_read(resource_id, versions[resource_id.lower()]))
            if kind not in terminal_extensions and kind != "microsoft.search/searchservices":
                read_children_ahead(resource_id, kind)
                read_extensions_ahead(resource_id)

    def add_collection(path, api, extension=False, single=None):
        if single:
            status, headers, body = reader.get(collection_read(path, api, single=single))
            rows, unsupported = ([] if status == 404 else [body]), None
        else:
            rows, unsupported = reader.get(collection_read(path, api, extension))
        entry = {"api_version": api, "ids": sorted(row["id"].lower() for row in rows),
                 "items": rows,
                 "body_hash": digest(rows), "unsupported": unsupported}
        closure["collections"][path.lower()] = entry
        for row in rows:
            resource_id = row["id"].lower()
            if resource_id not in versions:
                versions[resource_id] = resource_versions.get(resource_id, api)
                enqueue(row["id"])

    def extensions(scope):
        for path, api, applicable in extension_steps(scope):
            if not applicable:
                closure["collections"][path.lower()] = {
                    "not_applicable": "resource-group-activity-logs-are-subscription-scoped"}
                continue
            add_collection(path, api, extension=True)

    for scope in sorted(scopes, key=str.lower) if ahead else ():
        reader.prefetch(arm_read(scope, RG_API))
        reader.prefetch(("list_resources", (scope,), ()))
        read_extensions_ahead(scope)
    for scope in sorted(scopes, key=str.lower):
        _, headers, body = reader.get(arm_read(scope, RG_API))
        bodies[scope.lower()] = body
        closure["groups"][scope.lower()] = {"body_hash": digest(body), "etag": body.get("etag") or
                                            next((v for k, v in headers.items() if k.lower() == "etag"), None)}
        roots = reader.get(("list_resources", (scope,), ()))
        closure["collections"][scope.lower() + "/resources"] = {
            "api_version": RG_API, "ids": sorted(row["id"].lower() for row in roots),
            "items": sorted(roots, key=lambda row: row["id"].lower()),
            "body_hash": digest(sorted(roots, key=lambda row: row["id"].lower())), "unsupported": None}
        for row in roots if ahead else ():
            # Each root's provider loads now or when the root is walked: start them together.
            kind = resource_type_from_id(row["id"])
            namespace = kind.split("/", 1)[0]
            if kind not in terminal_extensions and namespace not in closure["providers"]:
                for read in provider_reads(namespace):
                    reader.prefetch(read)
        for row in roots:
            resource_id = row["id"]
            require(arm_scope(resource_id) == scope.lower(), "inventory-escaped-resource-group")
            api = resource_versions.get(resource_id.lower()) or version(resource_type_from_id(resource_id))
            if resource_id.lower() not in versions:
                versions[resource_id.lower()] = api
                enqueue(resource_id)
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
        _, headers, body = reader.get(arm_read(resource_id, api))
        require(isinstance(body, dict) and body.get("id", "").lower() == key, "resource-closure-identity-mismatch")
        bodies[key] = body
        require(not body.get("type") or body["type"].lower() == kind, "resource-closure-type-mismatch")
        closure["resources"][key] = {"type": kind, "api_version": api, "body_hash": digest(body),
                                    "etag": body.get("etag") or next((v for k, v in headers.items() if k.lower() == "etag"), None)}
        references = resource_references(body)
        closure["references"][key] = sorted(references - {key})
        for reference in sorted(references):
            match = RG_ID.match(reference)
            if (reference == key or reference in versions or not match
                    or match.group().lower() not in scope_ids or RG_ID.fullmatch(reference)):
                continue
            referenced_kind = resource_type_from_id(reference)
            if referenced_kind in inline:
                parent = reference.rsplit("/", 2)[0]
                closure["inline"][reference] = {"parent_id": parent}
                if parent in versions:
                    continue
                reference, referenced_kind = parent, resource_type_from_id(parent)
            require(resource_kind(referenced_kind) in ("resource", "readonly"), "resource-reference-is-operation")
            parent_api = api if referenced_kind.split("/")[0] == kind.split("/")[0] else None
            versions[reference] = resource_versions.get(reference) or version(referenced_kind, parent_api)
            enqueue(reference)
        if kind in terminal_extensions:
            continue
        if kind == "microsoft.search/searchservices":
            # Search's ARM resource type is services, never searchServices.
            raise Blocked("invalid-search-service-arm-resource-type")
        for step, path, value, single in child_steps(resource_id, kind):
            read_children_ahead(resource_id, kind)
            if step == "inline":
                closure["collections"][path] = {"inline_parent_hash": digest(body)}
            elif step == "metadata":
                closure["collections"][path] = {"non_resource_metadata": value}
            else:
                add_collection(path, value, single=single)
        extensions(resource_id)
    for reference, metadata in closure["inline"].items():
        parent = metadata["parent_id"]
        entries = bodies.get(parent)
        for field in inline[resource_type_from_id(reference)]:
            entries = entries.get(field) if isinstance(entries, dict) else None
        require(isinstance(entries, list) and sum(
                    isinstance(row, dict) and isinstance(row.get("id"), str)
                    and row["id"].lower() == reference for row in entries) == 1,
                "inline-resource-parent-unverified")
        metadata["parent_body_hash"] = digest(bodies[parent])
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


def protected_resource_group_patterns(document):
    patterns = document.get("protected_resource_group_patterns", [])
    require(isinstance(patterns, list) and len(patterns) <= 100
            and all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.()*?-]{1,90}", value)
                    for value in patterns), "invalid-protected-resource-group-patterns")
    return patterns


def assert_deletion_group_allowed(document, identifier, body=None):
    patterns = protected_resource_group_patterns(document)
    groups = {arm_scope(identifier)}
    if body is not None:
        groups.update(managed_group_cascades(body, document["target"]["subscription_id"]))
    require(not any(fnmatch.fnmatchcase(RG_ID.fullmatch(group).group(2).lower(), pattern.lower())
                    for group in groups for pattern in patterns), "protected-resource-group-deletion-forbidden")


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
    reader = coordination(cloud, document)
    reader.verify_enrollment()
    if single_writer(document):
        require(reader.state()[1]["active"] is None, "single-writer-repository-active-claim")
    scopes = document["locks"]["scopes"]
    closure, bodies = collect_resource_closure(cloud, scopes)
    verify_deletion_identity(document, bodies)
    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    groups, resources = [], []
    for scope in scopes:
        require(not project_resource_shared(bodies[scope.lower()]), "shared-resource-group-delete-forbidden")
        manager = verify_group_ownership(bodies[scope.lower()], owner, bodies)
        entry = {"id": scope, **closure["groups"][scope.lower()], "delete": True, "owner": owner}
        if manager:
            entry.update(ownership_source="managed-parent", managed_parent_id=manager)
        groups.append(entry)
    for resource_id, metadata in closure["resources"].items():
        body = bodies[resource_id]
        require(not project_resource_shared(body), "shared-resource-delete-forbidden")
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


def verify_deletion_identity(document, bodies):
    principal = str(document["identity"]["object_id"]).lower()
    for body in bodies.values():
        properties = body.get("properties") or {}
        identity = body.get("identity") or {}
        identifiers = [properties.get("principalId"), identity.get("principalId")]
        identifiers.extend(value.get("principalId") for value in
                           (identity.get("userAssignedIdentities") or {}).values()
                           if isinstance(value, dict))
        require(principal not in {str(value).lower() for value in identifiers if value},
                "executing-identity-in-deletion-scope")


def project_deletion_policy(document):
    scope = document.get("deletion_scope")
    require(isinstance(scope, dict) and set(scope) == {
        "kind", "contract", "project_id", "project_number", "options", "registered_resource_ids"}
        and scope.get("kind") == "project" and scope.get("contract") == SELECTIVE_PROJECT_DELETE
        and guid(scope.get("project_id"))
        and document["target"]["project_ids"] == [scope.get("project_number")],
        "exact-project-deletion-scope-required")
    options = scope.get("options")
    require(isinstance(options, dict) and set(options) == {
        "environments", "include_project_subnets", "include_keyvault_and_resource_group"}
        and type(options.get("include_project_subnets")) is bool
        and type(options.get("include_keyvault_and_resource_group")) is bool,
        "explicit-project-deletion-options-required")
    envs = options.get("environments")
    require(isinstance(envs, list) and envs and all(env in ("dev", "stage", "prod") for env in envs)
            and len(set(envs)) == len(envs) and document["target"]["environment"] in envs,
            "explicit-project-environments-required")
    registered = scope.get("registered_resource_ids")
    require(isinstance(registered, list) and registered and all(isinstance(item, str)
            and (RG_ID.fullmatch(item) or NESTED_ID.fullmatch(item)) for item in registered)
            and len(set(item.lower() for item in registered)) == len(registered),
            "registered-project-ownership-required")
    review = document.get("reviewed_scope")
    require(isinstance(review, dict) and review.get("factory_id") == document["target"]["factory_id"]
            and review.get("project_id") == scope["project_id"] and review.get("deletion_options") == options
            and hash_value(review.get("expected_revision")), "project-reviewed-scope-mismatch")
    return options


def project_delete_roots(data):
    entries = [*data["resource_groups"], *data["resources"]]
    deleted = {item["id"].lower(): item for item in entries if item["delete"]}
    roots = {key: item for key, item in deleted.items()
             if not any(key.startswith(parent + "/") for parent in deleted if parent != key)}
    plan = []
    for key, item in roots.items():
        references = {ref.lower() for child in entries if child["id"].lower() == key
                      or child["id"].lower().startswith(key + "/") for ref in child.get("depends_on", [])}
        dependencies = [other for other in roots if other != key
                        and any(ref == other or ref.startswith(other + "/") for ref in references)]
        plan.append({**item, "depends_on": dependencies})
    return deletion_order(plan)


def project_resource_shared(body):
    require(isinstance(body.get("tags") or {}, dict), "malformed-project-ownership-tags")
    return any(key.lower() == "aifactory.shared" and str(value).lower() == "true"
               for key, value in (body.get("tags") or {}).items())


def project_resource_dependencies(body):
    key = body["id"].lower()
    references = resource_references(body)
    if str(body.get("type", "")).lower() in PROJECT_NETWORK_TYPES | {"microsoft.network/virtualnetworks"}:
        # Subnets are reverse links or separately inventoried child bodies.
        references -= resource_references((body.get("properties") or {}).get("subnets", []))
    for field in REVERSE_LINKS.get(str(body.get("type", "")).lower(), ()):
        references -= resource_references([body.get(field), (body.get("properties") or {}).get(field)])
    return sorted(ref for ref in references if RG_ID.match(ref) and ref != key and not ref.startswith(key + "/"))


def validate_project_deletion(document):
    options = project_deletion_policy(document)
    data, target = document.get("deletion"), document["target"]
    require(isinstance(data, dict) and data.get("inventory_mode") == SELECTIVE_PROJECT_DELETE
            and data.get("inventory_complete") is True and data.get("revision") == document["manifest_revision"],
            "complete-project-inventory-required")
    groups, resources = data.get("resource_groups"), data.get("resources")
    require(isinstance(groups, list) and groups and isinstance(resources, list)
            and all(isinstance(item, dict) for item in groups + resources), "invalid-project-inventory")
    require(data.get("inventory_hash") == digest(resources)
            and isinstance(data.get("closure"), dict) and data.get("closure_hash") == digest(data["closure"]),
            "project-inventory-hash-mismatch")
    bodies = data.get("bodies")
    require(isinstance(bodies, dict), "project-retention-proof-required")
    writable = {value.lower() for value in document["locks"]["scopes"]}
    scopes = writable | {value.lower() for value in document["locks"]["common_dependencies"]}
    group_ids = {str(item.get("id", "")).lower() for item in groups}
    require(group_ids == scopes, "project-inventory-scope-mismatch")
    project_group = str(data.get("project_resource_group", "")).lower()
    registered = {item.lower() for item in document["deletion_scope"]["registered_resource_ids"]}
    require(project_group in writable & registered and RG_ID.fullmatch(project_group),
            "registered-exact-project-group-required")
    owner = {key: target[key] for key in ("factory_id", "scaleset_id")}
    owner["project_id"] = document["deletion_scope"]["project_number"]
    entries = {str(item.get("id", "")).lower(): item for item in groups + resources}
    require(len(entries) == len(groups + resources) and set(bodies) == set(entries),
            "duplicate-or-incomplete-project-inventory")
    require(any(item.get("delete") is True for item in entries.values()), "nonempty-delete-allowlist-required")
    for identifier, item in entries.items():
        is_group = identifier in group_ids
        require((RG_ID if is_group else NESTED_ID).fullmatch(identifier)
                and arm_scope(identifier) in scopes and type(item.get("delete")) is bool
                and hash_value(item.get("body_hash")) and item["body_hash"] == digest(bodies[identifier]),
                "invalid-project-resource-proof")
        require(item.get("etag") is None or isinstance(item["etag"], str), "invalid-project-resource-etag")
        if not is_group:
            require(item.get("type") == resource_type_from_id(identifier)
                    and isinstance(item.get("api_version"), str)
                    and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", item["api_version"]),
                    "invalid-project-resource-type")
        require(isinstance(item.get("depends_on"), list)
                and item["depends_on"] == project_resource_dependencies(bodies[identifier]),
                "explicit-project-dependencies-required")
        if identifier == project_group:
            require(item.get("owner") == owner and item["delete"] == options["include_keyvault_and_resource_group"],
                    "project-resource-group-policy-mismatch")
        if not item["delete"]:
            continue
        require(arm_scope(identifier) in writable and item.get("owner") == owner
                and not project_resource_shared(bodies[identifier]),
                "shared-or-foreign-project-delete-forbidden")
        if is_group:
            require(identifier == project_group, "common-or-other-resource-group-delete-forbidden")
        else:
            kind = item["type"]
            subnet = kind == "microsoft.network/virtualnetworks/subnets"
            require(kind != "microsoft.network/virtualnetworks", "project-vnet-delete-forbidden")
            network = any((identifier == entry or identifier.startswith(entry + "/"))
                          and resource_type_from_id(entry) in PROJECT_NETWORK_TYPES for entry in registered)
            require(arm_scope(identifier) == project_group or subnet and identifier in registered or network,
                    "outside-project-service-delete-forbidden")
            require(not network or options["include_project_subnets"], "retained-project-network-delete-forbidden")
            require(not subnet or options["include_project_subnets"], "retained-subnet-delete-forbidden")
            require(not kind.startswith("microsoft.keyvault/vaults")
                    or options["include_keyvault_and_resource_group"], "retained-keyvault-delete-forbidden")
        require(all(child["delete"] for key, child in entries.items() if key.startswith(identifier + "/")),
                "retained-child-cascade-forbidden")
        cascades = managed_group_cascades(bodies[identifier], target["subscription_id"])
        require(cascades <= ({project_group} if options["include_keyvault_and_resource_group"] else set()),
                "implicit-managed-group-not-authorized")
    deleted = {key for key, item in entries.items() if item["delete"]}
    for key, item in entries.items():
        require(item["delete"] or not any(ref.lower() in deleted for ref in item["depends_on"]),
                "retained-project-dependency-delete-forbidden")
    protect_coordination_storage(document)
    project_delete_roots(data)


def project_owner(cloud, document, body, records, cache):
    require(isinstance(body.get("tags") or {}, dict), "malformed-project-ownership-tags")
    tags = {key.lower(): str(value) for key, value in (body.get("tags") or {}).items()}
    owner = {key: tags[tag] for key, tag in TAG_KEYS.items() if tag in tags}
    logical = tags.get("aifactory.logical_project_id")
    if logical and owner.get("project_id") == document["deletion_scope"]["project_number"]:
        require(logical == document["deletion_scope"]["project_id"], "logical-project-owner-mismatch")
    if owner:
        return {"owner": owner, "ownership_source": "tags"}
    key = body["id"].lower()
    record = records.get(key, {})
    if record.get("ownership_source") == "deployment-receipt":
        evidence = record.get("ownership_evidence")
        verified = verified_receipt_owner(BlobLocks(cloud, document), evidence, key, digest(body), cache)
        require(verified == record.get("owner"), "project-receipt-owner-mismatch")
        return {"owner": verified, "ownership_source": "deployment-receipt", "ownership_evidence": evidence}
    return {"owner": {}, "ownership_source": "retained-unowned"}


def verify_project_permissions(cloud, data):
    for item in project_delete_roots(data):
        _, _, body = cloud.request("GET", ARM + quote(item["id"], safe="/().-_")
                                   + "/providers/Microsoft.Authorization/permissions?api-version=2022-04-01", ARM)
        require(isinstance(body, dict) and isinstance(body.get("value"), list) and not body.get("nextLink"),
                "complete-project-delete-permissions-required")
        action = ("microsoft.resources/subscriptions/resourcegroups/delete" if RG_ID.fullmatch(item["id"])
                  else item["type"] + "/delete")
        allowed = False
        for row in body["value"]:
            require(isinstance(row, dict) and isinstance(row.get("actions"), list)
                    and isinstance(row.get("notActions"), list)
                    and all(isinstance(value, str) for value in row["actions"] + row["notActions"]),
                    "malformed-project-delete-permissions")
            allowed |= (any(fnmatch.fnmatchcase(action, value.lower()) for value in row["actions"])
                        and not any(fnmatch.fnmatchcase(action, value.lower()) for value in row["notActions"]))
        require(allowed, "project-delete-permission-required")


def freeze_project_deletion(cloud, document, ownership_records):
    options = project_deletion_policy(document)
    cloud.verify_identity()
    BlobLocks(cloud, document).verify_enrollment()
    scopes = sorted(set(document["locks"]["scopes"] + document["locks"]["common_dependencies"]), key=str.lower)
    closure, bodies = collect_resource_closure(cloud, scopes)

    records = {key.lower(): value for key, value in ownership_records.items()}
    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    owner["project_id"] = document["deletion_scope"]["project_number"]
    registered = {item.lower() for item in document["deletion_scope"]["registered_resource_ids"]}
    entries, cache = {}, {}
    for key, body in bodies.items():
        group = key in closure["groups"]
        metadata = closure["groups"][key] if group else closure["resources"][key]
        proof = project_owner(cloud, document, body, records, cache)
        entries[key] = {"id": body["id"], **metadata, **proof, "delete": False,
                        "depends_on": project_resource_dependencies(body)}
    matches = [key for key in closure["groups"] if entries[key]["owner"] == owner and key in registered]
    require(len(matches) == 1, "one-exact-owned-project-resource-group-required")
    project_group = matches[0]
    writable = {item.lower() for item in document["locks"]["scopes"]}
    for key, item in entries.items():
        body, kind = bodies[key], item.get("type", "")
        in_project = arm_scope(key) == project_group
        shared = project_resource_shared(body)
        if options["include_project_subnets"] and kind == "microsoft.network/virtualnetworks/subnets":
            require(key not in registered or bool(item["owner"]) or shared,
                    "registered-subnet-ownership-unverified")
            if item["owner"] == owner and not shared:
                require((in_project or key in registered) and arm_scope(key) in writable,
                        "registered-writable-project-subnet-required")
        if in_project:
            require(item["owner"] == owner and not shared, "project-group-ownership-incomplete-or-shared")
        if item["owner"] != owner or shared or arm_scope(key) not in writable:
            continue
        if key in closure["groups"]:
            item["delete"] = key == project_group and options["include_keyvault_and_resource_group"]
        elif kind == "microsoft.network/virtualnetworks/subnets":
            item["delete"] = options["include_project_subnets"] and (in_project or key in registered)
        elif kind == "microsoft.network/virtualnetworks":
            item["delete"] = False
        elif any((key == entry or key.startswith(entry + "/"))
                 and resource_type_from_id(entry) in PROJECT_NETWORK_TYPES for entry in registered):
            item["delete"] = options["include_project_subnets"]
        elif kind.startswith("microsoft.keyvault/vaults"):
            item["delete"] = in_project and options["include_keyvault_and_resource_group"]
        else:
            item["delete"] = in_project
    # Preserve necessary dependencies and every ancestor of a retained resource.
    # Never silently widen deletion to make a dependency graph executable.
    changed = True
    while changed:
        changed = False
        for key, item in entries.items():
            if item["delete"]:
                continue
            for candidate, other in entries.items():
                if other["delete"] and (key.startswith(candidate + "/")
                                       or candidate in item["depends_on"]
                                       or candidate.startswith(key + "/") and item.get("type")
                                       not in (None, "microsoft.network/virtualnetworks")):
                    other["delete"] = False
                    changed = True
    if options["include_project_subnets"]:
        require(all(item["delete"] for key, item in entries.items()
                    if item.get("type") == "microsoft.network/virtualnetworks/subnets"
                    and item["owner"] == owner and not project_resource_shared(bodies[key])),
                "project-subnet-retained-dependency-conflict")
        for key in registered & set(entries):
            if entries[key].get("type") in PROJECT_NETWORK_TYPES and entries[key]["owner"] == owner:
                require(all(child["owner"] == owner and not project_resource_shared(bodies[identifier])
                            for identifier, child in entries.items() if identifier == key or identifier.startswith(key + "/")),
                        "project-network-child-ownership-unverified")
    result = {"inventory_mode": SELECTIVE_PROJECT_DELETE, "inventory_complete": True,
              "revision": document["manifest_revision"], "project_resource_group": bodies[project_group]["id"],
              "resource_groups": [entries[key] for key in sorted(closure["groups"])],
              "resources": [entries[key] for key in sorted(closure["resources"])],
              "closure": closure, "closure_hash": digest(closure), "bodies": bodies}
    result["inventory_hash"] = digest(result["resources"])
    validate_project_deletion({**document, "deletion": result})
    for scope in scopes:
        cloud.assert_no_active_deployments(scope)
    require(not any(item.get("type") in ("microsoft.authorization/locks", "microsoft.authorization/denyassignments")
                    for item in result["resources"]), "project-delete-lock-or-deny-assignment-present")
    verify_project_permissions(cloud, result)
    return result


def _without_deleted_children(body, removed):
    if isinstance(body, list):
        return [_without_deleted_children(item, removed) for item in body
                if not isinstance(item, dict) or str(item.get("id", "")).lower() not in removed]
    if isinstance(body, dict):
        return {key: _without_deleted_children(value, removed) for key, value in body.items() if key.lower() != "etag"}
    return body


def _without_removed_backlinks(body, removed):
    """ARM drops a back-reference once its dependent is deleted; nothing else may change."""
    def gone(value):
        references = resource_references([value])
        return bool(references) and all(any(ref == item or ref.startswith(item + "/") for item in removed)
                                        for ref in references)

    result = copy.deepcopy(body)
    for field in REVERSE_LINKS.get(str(body.get("type", "")).lower(), ()):
        for holder in (result, result.get("properties") if isinstance(result.get("properties"), dict) else {}):
            value = holder.get(field)
            if isinstance(value, list):
                # A list of dependents loses exactly the entries whose dependent was deleted.
                kept = [entry for entry in value if not gone(entry)]
                if kept:
                    holder[field] = kept
                else:
                    holder.pop(field)
            elif gone(value):
                holder.pop(field)
    return result


def verify_project_inventory(cloud, document, removed=()):
    data = document["deletion"]
    removed = {item.lower() for item in removed}
    scopes = [row["id"] for row in data["resource_groups"] if row["id"].lower() not in removed]
    closure, bodies = collect_resource_closure(cloud, scopes)
    expected = data["closure"]
    if not removed:
        require(closure == expected, "project-complete-inventory-changed")
    for namespace, value in closure["providers"].items():
        require(expected["providers"].get(namespace) == value, "project-provider-schema-changed")
    require(set(bodies) == set(data["bodies"]) - removed, "project-resource-closure-changed")
    for key, body in bodies.items():
        before = data["bodies"][key]
        backlinks = (str(before.get("type", "")).lower() in PROJECT_NETWORK_TYPES
                     and bool(resource_references((before.get("properties") or {}).get("subnets", [])) & removed))
        stripped = _without_removed_backlinks(before, removed)
        if any(identifier.startswith(key + "/") for identifier in removed) or backlinks or stripped != before:
            require(_without_deleted_children(_without_removed_backlinks(body, removed), removed)
                    == _without_deleted_children(stripped, removed), "project-retained-parent-changed")
        else:
            require(digest(body) == digest(before), "project-resource-instance-changed")
    expected_collections = {key: value for key, value in expected["collections"].items()
                            if not any(key == item or key.startswith(item + "/") for item in removed)}
    require(set(closure["collections"]) == set(expected_collections), "project-child-collections-changed")
    for key, value in closure["collections"].items():
        old = expected_collections[key]
        for field in ("api_version", "unsupported", "not_applicable", "non_resource_metadata"):
            require(value.get(field) == old.get(field), "project-child-collection-contract-changed")
        require(value.get("ids") == ([item for item in old["ids"] if item not in removed] if "ids" in old else None),
                "project-child-inventory-changed")
    cache = {}
    for item in data["resource_groups"] + data["resources"]:
        key = item["id"].lower()
        if key in removed:
            continue
        if item.get("ownership_source") == "tags":
            verify_ownership(bodies[key], item["owner"])
        elif item.get("ownership_source") == "deployment-receipt":
            require(verified_receipt_owner(BlobLocks(cloud, document), item["ownership_evidence"], key,
                    item["body_hash"], cache) == item["owner"], "project-ownership-receipt-changed")
    for scope in scopes:
        cloud.assert_no_active_deployments(scope)
    return bodies


def delete_project_resources(cloud, locks, document, receipt, persist, sleep=time.sleep):
    validate_project_deletion(document)
    locks.authorize(document)
    verify_project_inventory(cloud, document)
    verify_project_permissions(cloud, document["deletion"])
    removed = set()
    entries = document["deletion"]["resource_groups"] + document["deletion"]["resources"]
    for item in project_delete_roots(document["deletion"]):
        locks.authorize(document)
        locks.assert_held()
        cloud.verify_identity()
        cloud.assert_no_active_runs(locks.enrollment)
        verify_project_inventory(cloud, document, removed)
        locks.authorize(document)
        receipt.update(mutation_started=True, pending_resource=item["id"])
        persist()
        api = RG_API if RG_ID.fullmatch(item["id"]) else item["api_version"]
        cloud.arm("DELETE", item["id"], api, allowed=(200, 202, 204),
                  headers={"If-Match": item["etag"]} if item.get("etag") else None)
        wait_absent(cloud, locks, item["id"], api, sleep)
        affected = [row for row in entries if row["id"].lower() == item["id"].lower()
                    or row["id"].lower().startswith(item["id"].lower() + "/")]
        for row in affected:
            wait_absent(cloud, locks, row["id"], RG_API if RG_ID.fullmatch(row["id"]) else row["api_version"], sleep)
            removed.add(row["id"].lower())
            receipt["deleted_resources"].append(row["id"])
        receipt.pop("pending_resource", None)
        persist()
    locks.assert_held()
    cloud.verify_identity()
    verify_project_inventory(cloud, document, removed)
    receipt["deletion_scope"] = document["deletion_scope"]
    receipt["retained_resources"] = sorted(row["id"] for row in entries if not row["delete"])
    persist()


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
    records = receipt.get("resource_groups", []) if RG_ID.fullmatch(resource_id) else receipt.get("ownership", [])
    matches = [row for row in records if row.get("resource_id", "").lower() == resource_id.lower()]
    require(len(matches) == 1 and matches[0].get("body_hash") == body_hash, "child-instance-ownership-unverified")
    owner = matches[0].get("owner")
    require(isinstance(owner, dict) and all(receipt.get("target", {}).get(key) == owner.get(key)
                                          for key in ("factory_id", "scaleset_id")),
            "child-receipt-target-mismatch")
    return owner


def verify_full_inventory(cloud, document, removed_groups=(), removed_resources=()):
    data = document["deletion"]
    removed = {scope.lower() for scope in removed_groups}
    removed_children = {identifier.lower() for identifier in removed_resources}
    require(removed_children <= {row["id"].lower() for row in data["resources"] if row["delete"]},
            "unreviewed-removed-child")
    groups = [group for group in data["resource_groups"] if group["id"].lower() not in removed]
    scopes = [group["id"] for group in groups]
    if not scopes:
        return {}
    cascades = {}
    closure, bodies = collect_resource_closure(cloud, scopes)
    verify_deletion_identity(document, bodies)
    expected = data["closure"]
    # Provider schemas are global to the subscription; retain only those still
    # required after an earlier approved resource group has been removed.
    for namespace, fingerprint in closure["providers"].items():
        require(expected["providers"].get(namespace) == fingerprint, "provider-schema-changed")
    for section in ("groups", "resources", "collections"):
        retained = {}
        for key, value in expected[section].items():
            if arm_scope(key) in removed or key in removed_children or any(
                    key.startswith(child + "/") for child in removed_children):
                continue
            value = copy.deepcopy(value)
            if section == "collections" and set(value.get("ids", [])) & removed_children:
                require(isinstance(value.get("items"), list), "frozen-child-collection-items-required")
                value["items"] = [row for row in value["items"] if row["id"].lower() not in removed_children]
                value["ids"] = [identifier for identifier in value["ids"] if identifier not in removed_children]
                value["body_hash"] = digest(value["items"])
            retained[key] = value
        require(closure[section] == retained, "complete-resource-closure-changed")
    expected_ids = {item["id"].lower() for item in data["resources"]
                    if arm_scope(item["id"]) not in removed and item["id"].lower() not in removed_children}
    require(set(closure["resources"]) == expected_ids, "unlisted-child-or-extension-resource")
    for group in groups:
        require(not project_resource_shared(bodies[group["id"].lower()]), "shared-resource-group-delete-forbidden")
        manager = verify_group_ownership(bodies[group["id"].lower()], group["owner"], bodies)
        require(not manager or group.get("ownership_source") == "managed-parent"
                and group.get("managed_parent_id") == manager, "managed-group-ownership-not-reviewed")
        cloud.assert_no_active_deployments(group["id"])
    resources = {item["id"].lower(): item for item in data["resources"]}
    receipt_cache = {}
    evidence_reader = coordination(cloud, document)
    for key in expected_ids:
        item = resources[key]
        require(not project_resource_shared(bodies[key]), "shared-resource-delete-forbidden")
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
    protect_coordination_storage(document)
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
    removed_children = set()
    # Only independently proven entries in the immutable manifest are eligible.
    # Leave private endpoint connections to the reviewed RG cascade: deleting
    # them individually changes embedded parent bodies before the next guard.
    links = [item for item in resources if resource_type_from_id(item["id"]) ==
             "microsoft.search/services/sharedprivatelinkresources"]
    for item in deletion_order(links):
        locks.authorize(document)
        locks.assert_held()
        cloud.verify_identity()
        cloud.assert_no_active_runs(locks.enrollment)
        verify_full_inventory(cloud, document, removed, removed_children)
        locks.authorize(document)
        locks.assert_held()
        receipt.update(mutation_started=True, pending_resource=item["id"])
        persist()
        cloud.arm("DELETE", item["id"], item["api_version"], allowed=(200, 202, 204),
                  headers={"If-Match": item["etag"]} if item.get("etag") else None)
        wait_absent(cloud, locks, item["id"], item["api_version"], sleep)
        removed_children.add(item["id"].lower())
        receipt["deleted_resources"].append(item["id"])
        receipt.pop("pending_resource", None)
        persist()
    for group in deletion_order(list(planned.values())):
        if group["id"].lower() in {scope.lower() for scope in removed}:
            continue
        locks.authorize(document)
        locks.assert_held()
        cloud.verify_identity()
        cloud.assert_no_active_runs(locks.enrollment)
        cascades = verify_full_inventory(cloud, document, removed, removed_children)
        locks.authorize(document)
        locks.assert_held()
        receipt["mutation_started"] = True
        receipt["pending_resource_group"] = group["id"]
        persist()
        approved = next(row for row in groups if row["id"].lower() == group["id"].lower())
        cloud.arm("DELETE", group["id"], RG_API, allowed=(200, 202, 204),
                  headers={"If-Match": approved["etag"]} if approved.get("etag") else None)
        wait_absent(cloud, locks, group["id"], RG_API, sleep)
        for item in resources:
            if arm_scope(item["id"]) == group["id"].lower() and item["id"].lower() not in removed_children:
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
        # Match the clock used by claim_run; time.time() can lag UTC on Windows.
        require(timestamp(document["prepared_at"]) <= accepted < timestamp(document["expires_at"])
                and accepted <= timestamp(utc_now()),
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
        self.verify_enrollment_document(enrollment)

    def verify_enrollment_document(self, enrollment, protocol="aifactory-physical-lock-v1",
                                   enforcement="all-writers-exclusive"):
        require(digest(enrollment) == self.settings["coordination_hash"], "lock-enrollment-changed")
        require(isinstance(enrollment, dict) and enrollment.get("schema") == 1
                and enrollment.get("protocol") == protocol
                and enrollment.get("enforcement") == enforcement
                and enrollment.get("revision") == self.settings["revision"], "invalid-lock-enrollment")
        route = self.document["route"]
        writers = enrollment.get("writers", {})
        require(isinstance(writers, dict) and route["writer_id"] in writers, "writer-not-enrolled")
        writer = writers[route["writer_id"]]
        require(all(writer.get(key) == route[key] for key in ("kind", "repository", "shared_remote")),
                "writer-binding-changed")
        if ("deployment" in self.document or
                self.document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1"):
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


class RepositoryCoordination:
    """Repository-wide durable claim and receipts, not an Azure Blob lease."""

    def __init__(self, cloud, document):
        self.cloud, self.document, self.settings = cloud, document, document["locks"]
        self.store = repository_state_module().ProviderState(cloud, document["route"], Blocked)
        self.held, self.inherited = {}, set()
        self.enrollment, self.execution_claim = None, None
        self.closed = False

    def state(self):
        head, value = self.store.read()
        require(head and value and value["enrollment"], "single-writer-enrollment-state-missing")
        BlobLocks.verify_enrollment_document(self, value["enrollment"], "aifactory-single-writer-v1",
                                            "repository-exclusive-writer")
        require(set(self.enrollment["writers"]) == {self.document["route"]["writer_id"]},
                "single-writer-repository-writer-conflict")
        return head, value

    def verify_enrollment(self):
        self.state()

    def _active(self, value):
        active = value["active"]
        require(self.held and isinstance(active, dict) and active.get("kind") == "run"
                and active.get("run_id") == self.document["run_id"]
                and active.get("manifest_hash") == self.document["manifest_hash"]
                and active.get("context") == self.held, "single-writer-active-claim-changed")

    def acquire(self):
        validate_manifest(self.document)
        head, value = self.state()
        require(value["active"] is None, "single-writer-repository-active-claim")
        require(not any(key.startswith("runs/" + self.document["run_id"] + ".") for key in value["records"]),
                "single-writer-run-already-submitted")
        identifier = str(uuid4())
        context = {scope.lower(): identifier for scope in self.settings["scopes"] + self.settings["common_dependencies"]}
        active = {"kind": "run", "run_id": self.document["run_id"],
                  "manifest_hash": self.document["manifest_hash"], "context": context}
        self.store.update(head, value, active=active)
        self.held = context

    def assert_held(self):
        require(not self.store.write_failed, "single-writer-write-reconciliation-required")
        _, value = self.state()
        self._active(value)

    def claim_run(self):
        validate_manifest(self.document)
        head, value = self.state()
        self._active(value)
        proof = {"schema": 1, "claim_id": str(uuid4()), "run_id": self.document["run_id"],
                 "manifest_hash": self.document["manifest_hash"], "source": self.document["source"],
                 "accepted_at": utc_now(), "lease_context_hash": digest(self.held)}
        name = "runs/" + self.document["run_id"]
        require(name + ".json" not in value["records"] and name + ".claim.json" not in value["records"],
                "single-writer-run-already-submitted")
        value["records"][name + ".json"] = {"schema": 1, "run_id": self.document["run_id"], "state": "claimed",
                                            "manifest_hash": self.document["manifest_hash"], "execution_claim": proof}
        value["records"][name + ".claim.json"] = proof
        self.store.replace(head, value)
        self.execution_claim = _ExecutionClaim(self.document, proof)
        self.authorize(self.document)

    def request(self, method, name, data=None, headers=None, allowed=(200,), query=""):
        require(not query and re.fullmatch(r"runs/[a-fA-F0-9-]{36}\.(?:claim\.|worker\.)?json", name),
                "single-writer-record-path-invalid")
        head, value = self.state()
        records = value["records"]
        if method == "GET":
            if name not in records:
                require(404 in allowed, "single-writer-run-state-missing")
                return 404, {}, None
            return 200, {}, records[name]
        require(method == "PUT" and name.startswith("runs/" + self.document["run_id"] + ".")
                and not name.endswith(".claim.json"), "single-writer-record-write-forbidden")
        self._active(value)
        conditions = headers or {}
        require((conditions.get("If-None-Match") == "*" and name not in records)
                or (conditions.get("If-Match") == "*" and name in records),
                "single-writer-record-precondition-failed")
        if name in records:
            require(records[name].get("status") not in ("succeeded", "reconciliation-required", "blocked"),
                    "single-writer-terminal-record-immutable")
        require(isinstance(data, dict) and data.get("run_id") == self.document["run_id"]
                and data.get("manifest_hash") == self.document["manifest_hash"],
                "single-writer-record-binding-mismatch")
        value["records"][name] = json.loads(canonical(data))
        self.store.replace(head, value)
        return 201, {}, None

    def read_claim(self):
        return self.request("GET", "runs/" + self.document["run_id"] + ".claim.json")[2]

    def authorize(self, document):
        return BlobLocks.authorize(self, document)

    def store_receipt(self, receipt):
        if self.execution_claim is not None:
            receipt["execution_claim"] = json.loads(self.execution_claim.proof)
        if self.closed:
            # The successful receipt is already durable; do not rewrite it after
            # releasing the claim or overwrite another run's active state.
            require(receipt["status"] == "succeeded", "single-writer-terminal-record-immutable")
            return
        self.request("PUT", "runs/" + self.document["run_id"] + ".json", data=receipt,
                     headers={"If-Match": "*"}, allowed=(201,))

    def release(self):
        if not self.held:
            return
        head, value = self.state()
        self._active(value)
        receipt = value["records"].get("runs/" + self.document["run_id"] + ".json", {})
        worker = value["records"].get("runs/" + self.document["run_id"] + ".worker.json", {})
        require(receipt.get("status") == "succeeded" and worker.get("status") == "succeeded",
                "single-writer-claim-retained-reconciliation-required")
        self.store.update(head, value, active=None)
        self.held.clear()
        self.closed = True


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
        tip = refs.get(source["ref"] + "^{}", refs.get(source["ref"]))
        if tip != source["commit"]:
            # The reviewed commit stays published while the published ref still contains it,
            # so later pushes to the branch do not strand a factory bound to that commit.
            require(tip is not None, "version-no-longer-published-at-reviewed-commit")
            # Objects only: no hooks, maintenance, FETCH_HEAD or remote-tracking ref updates.
            cloud.command(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "maintenance.auto=false", "-c", "gc.auto=0",
                           "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--refmap=", "origin", source["ref"]],
                          cwd=str(root))
            try:
                base = cloud.command(["git", "merge-base", source["commit"], tip], cwd=str(root))
            except Blocked:
                base = None
            require(base == source["commit"], "version-no-longer-published-at-reviewed-commit")
    published_helper = cloud.command(["git", "show", source["commit"] + ":bootstrap/lib/factory_lifecycle.py"], cwd=str(root))
    require(published_helper == Path(__file__).read_text(encoding="utf-8").strip(),
            "published-lifecycle-adapter-mismatch")
    if single_writer(getattr(cloud, "document", {})):
        published_state = cloud.command(["git", "show", source["commit"] + ":bootstrap/lib/provider_repository_state.py"], cwd=str(root))
        require(published_state == Path(__file__).with_name("provider_repository_state.py").read_text(encoding="utf-8").strip(),
                "published-single-writer-adapter-mismatch")
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
    protect_coordination_storage(document)
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
    values = persona_helper(Path(__file__).resolve().parents[2]).selected_config(document["config"], target["environment"])
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


def arm_changes(body, unchanged_resources=None):
    require(isinstance(body, dict) and body.get("status") in (None, "Succeeded") and not body.get("error"),
            "arm-what-if-failed-or-incomplete")
    properties = body.get("properties", body)
    require(isinstance(properties, dict) and not properties.get("error")
            and isinstance(properties.get("changes"), list), "complete-arm-what-if-required")
    result = []
    for change in properties["changes"]:
        if change.get("changeType") == "Ignore":
            identifier = change.get("resourceId", "").lower()
            proof = (unchanged_resources or {}).get(identifier)
            require(isinstance(proof, dict) and hash_value(proof.get("body_hash"))
                    and (change.get("after") is None or change.get("before") == change.get("after"))
                    and not change.get("delta")
                    and not change.get("error") and not change.get("unsupportedReason"),
                    "ignored-resource-requires-exact-instance-proof")
            result.append({"resource_id": identifier, "change_type": "NoChange",
                           "before_hash": proof["body_hash"], "after_hash": proof["body_hash"]})
            continue
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


def _network_preservation_helper(source_root):
    path = clean_path(source_root / "bootstrap" / "lib" / "common_network_preservation.py")
    require(path.is_relative_to(source_root) and path.is_file(), "published-network-preservation-helper-required")
    module = types.ModuleType("published_common_network_preservation")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def verify_preserved_network(cloud, document, step, source_root, *, template=None, freeze=False):
    """Revalidate only the zero-write template footprint; never authorize allocation."""
    if step["parameters"].get("commonNetworkProfile") != "preserve-v1" and "network_preservation" not in step:
        return
    proof = step.get("network_preservation")
    require(step["template"] == COMMON_TEMPLATES["12-networkCommon"] and isinstance(proof, dict)
            and proof.get("contract") == "preserve-v1-runtime-proof",
            "runtime-network-preservation-proof-required")
    helper = _network_preservation_helper(source_root)
    try:
        require(helper.digest(helper._source_files(source_root)) == proof["source_payload_sha256"],
                "runtime-network-preservation-source-changed")
        template = template if template is not None else cloud.compile_template(source_root, step["template"])
        require(digest(template) == step["template_hash"], "compiled-template-hash-mismatch")
        helper.validate_compiled_capability(template)
        desired = json.loads(canonical(proof["desired"]))
        network_scope = arm_scope(desired["vnet_id"])
        require(desired["factory_id"] == document["target"]["factory_id"]
                and network_scope in {scope.lower() for scope in document["locks"]["scopes"]}
                and network_scope in {scope.lower() for scope in step["resource_groups"]}
                and (step["scope"] == "subscription"
                     or network_scope == str(step.get("resource_group", "")).lower()),
                "runtime-network-preservation-target-mismatch")
        parameters = step["parameters"]
        replay = parameters.get("preservationPlan", {})
        require(parameters.get("commonNetworkProfile") == "preserve-v1"
                and replay.get("createVnet") is False and replay.get("createSubnets") == []
                and replay.get("createNetworkSecurityGroups") == [],
                "runtime-network-replay-must-be-exactly-zero-write")
        expected_parameters = {**desired["parameters"], "commonNetworkProfile": "preserve-v1",
                               "preservationPlan": replay}
        require(expected_parameters == parameters, "runtime-network-preservation-parameters-changed")
        desired["parameters"] = parameters
        _, vnet_id, subnets, _ = helper._canonical(desired)
        identifiers = set(helper.required_resource_ids(desired))
        required = set(proof["expected_resource_ids"])
        require({vnet_id, *[vnet_id + "/subnets/" + item["name"].lower() for item in subnets]} <= required
                and required <= identifiers, "runtime-network-preservation-footprint-incomplete")
        inventory = {}
        for identifier in sorted(identifiers):
            status, _, body = cloud.arm("GET", identifier, helper.API_VERSION, allowed=(200, 404))
            require(status in (200, 404), "runtime-network-preservation-read-unverified")
            inventory[identifier] = body if status == 200 else None
            if identifier in required:
                helper._validate_existing(inventory[identifier], identifier)
        parent = inventory[vnet_id]["properties"]
        require(isinstance(parent.get("subnets"), list) and isinstance(parent.get("virtualNetworkPeerings"), list)
                and sorted(parent["addressSpace"]["addressPrefixes"]) == sorted(desired["approved_address_prefixes"]),
                "runtime-network-preservation-address-space-changed")
        for subnet in subnets:
            require(helper._prefixes(inventory[vnet_id + "/subnets/" + subnet["name"].lower()])
                    == [subnet["properties"]["addressPrefix"]], "runtime-network-preservation-subnet-changed")
        fingerprint = helper.digest(inventory)
        if freeze:
            proof["snapshot_sha256"] = fingerprint
        else:
            require(proof.get("snapshot_sha256") == fingerprint, "network-inventory-changed-since-prepare")
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, Blocked):
            raise
        raise Blocked("runtime-network-preservation-unverified") from None


def compiled_plan_step(cloud, document, step, source_root):
    template = cloud.compile_template(source_root, step["template"])
    require(digest(template) == step["template_hash"], "compiled-template-hash-mismatch")
    require(set(template["parameters"]) == set(step["parameters"]), "parameters-not-fully-resolved")
    schema = template.get("$schema", "").lower()
    require(("subscriptiondeploymenttemplate" in schema) == (step["scope"] == "subscription"),
            "compiled-template-scope-mismatch")
    verify_preserved_network(cloud, document, step, source_root, template=template)
    template = bind_foundry_identity_template(cloud, document, step, source_root, template)
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


def evaluate_what_if(cloud, document, step, payload, sleep=time.sleep, unchanged_resources=None,
                     resource_payloads=None, source_changes=None, phase_receipt=None):
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
    foundation = document.get("deployment", {}).get("bootstrap_foundation", {})
    resources = (foundation["resources"] if foundation.get("contract") == EXACT_BOOTSTRAP_CONTRACT else {})
    if unchanged_resources:
        if phase_receipt is not None:
            verify_foundry_observation_context(cloud, document, phase_receipt, unchanged_resources)
        require(all(key not in resources or resources[key]["body_hash"] == value["body_hash"]
                    or phase_receipt is not None and foundry_owned_phase_write(document, phase_receipt, key)
                    for key, value in unchanged_resources.items()), "what-if-instance-proof-conflict")
        resources = {**resources, **unchanged_resources}
    identity = document.get("deployment", {}).get("foundry_identity_continuation", {}).get("proof")
    if identity:
        require(identity.get("binding_hash") == foundry_identity_context(document)
                and hash_value(identity.get("body_hash")), "native-foundry-identity-proof-invalid")
        resources = {**resources, identity["resource_id"]: {"body_hash": identity["body_hash"]}}
    changes = arm_changes(response, resources)
    raw_changes = response.get("properties", response)["changes"]
    if source_changes is not None:
        # Preservation-normalized Ignore is not evidence of a source declaration.
        source_changes.clear()
        source_changes.update({row["resourceId"].lower(): row["changeType"] for row in raw_changes})
    if resource_payloads is not None:
        for row in raw_changes:
            identifier = str(row.get("resourceId", "")).lower()
            if (isinstance(row.get("after"), dict) and resource_type_from_id(identifier) in (
                    "microsoft.cognitiveservices/accounts", "microsoft.managedidentity/userassignedidentities",
                    "microsoft.authorization/roleassignments")):
                resource_payloads[identifier] = copy.deepcopy(row["after"])
    return changes


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


def combined_plan_payload(cloud, document, source_root, step_ids=None):
    """Deploy ordered phases together so preview sees their dependency graph."""
    target, steps = document["target"], document["deployment"]["steps"]
    if step_ids is not None:
        steps = [step for step in steps if step["id"] in step_ids]
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
                  "dependsOn": [ids[value] for value in step["depends_on"] if value in ids],
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


FOUNDRY_TEMPLATE = "environment_setup/aifactory/bicep/esml-genai-1/09-ai-foundry-2025-v4.bicep"
FOUNDRY_CONTRACT = "identity-receipt-account-uami-instance-closure-project-v4"
FOUNDRY_API = "2025-04-01-preview"
FOUNDRY_MI_API = "2024-11-30"
FOUNDRY_NETWORK_ROLE = "4d97b98b-1d4f-4787-a291-c67834d212e7"
FOUNDRY_FOUNDATION = "environment_setup/aifactory/bicep/esml-genai-1/01-foundation.bicep"
FOUNDRY_NETWORK_RBAC = "environment_setup/aifactory/bicep/esml-genai-1/08b-rbac-common-rg.bicep"
FOUNDRY_IDENTITY_CONTRACT = "source-projected-project-uami-instance-v2"
FOUNDRY_MI_TEMPLATE = "environment_setup/aifactory/bicep/modules/mi.bicep"
FOUNDRY_NAMING_TEMPLATE = "environment_setup/aifactory/bicep/modules/common/CmnAIfactoryNaming.bicep"
FOUNDRY_LOOKUP_TEMPLATE = "environment_setup/aifactory/bicep/modules/get-managed-identity-info.bicep"
FOUNDRY_ARRAY_TEMPLATE = "environment_setup/aifactory/bicep/modules/spAndMiArray.bicep"


def foundry_identity_context(document):
    """The second review may change run/time/ownership evidence, not the requested source or configuration."""
    return digest({**{key: document[key] for key in ("source", "config", "target", "identity", "route", "locks")},
                   "steps": [{key: value for key, value in step.items() if key != "changes"}
                             for step in document["deployment"]["steps"]]})


def foundry_identity_request_context(document):
    return digest({key: document[key] for key in ("source", "config", "target", "identity", "route", "locks")})


def foundry_identity_preparation(cloud, document, known_ownership):
    """Recover generated run inputs only; complete source/step binding is checked after rebuilding the plan."""
    matches = []
    for identifier, evidence in known_ownership.items():
        if resource_type_from_id(identifier) != "microsoft.managedidentity/userassignedidentities":
            continue
        require(isinstance(evidence, dict) and guid(evidence.get("run_id")) and hash_value(evidence.get("receipt_hash")),
                "native-foundry-identity-producer-receipt-required")
        _, _, receipt = coordination(cloud, document).request("GET", "runs/" + evidence["run_id"] + ".worker.json")
        require(isinstance(receipt, dict) and digest(receipt) == evidence["receipt_hash"],
                "native-foundry-identity-receipt-hash-mismatch")
        proof = receipt.get("foundry_identity_receipt")
        if not isinstance(proof, dict) or proof.get("request_hash") != foundry_identity_request_context(document):
            continue
        require(receipt.get("schema") == 1 and receipt.get("status") == "succeeded"
                and receipt.get("completion") == "identity-only" and receipt.get("continuation_required") is True
                and receipt.get("target") == document["target"] and receipt.get("source_commit") == document["source"]["commit"]
                and receipt.get("run_id") == evidence["run_id"] == proof.get("producer_run_id")
                and receipt.get("manifest_hash") == proof.get("producer_manifest_hash")
                and hash_value(receipt.get("manifest_hash")) and hash_value(proof.get("binding_hash"))
                and proof.get("contract") == FOUNDRY_IDENTITY_CONTRACT
                and proof.get("resource_id") == identifier == identifier.lower()
                and NESTED_ID.fullmatch(identifier) and proof.get("resource_group") == arm_scope(identifier)
                and arm_scope(identifier) in {scope.lower() for scope in document["locks"]["scopes"]}
                and proof.get("role_writes") == [] and proof.get("full_project_executed") is False,
                "native-foundry-identity-preparation-receipt-invalid")
        require(receipt["run_id"] != document["run_id"]
                and timestamp(proof.get("producer_prepared_at")) <= timestamp(proof.get("observed_at"))
                and 0 <= timestamp(document["prepared_at"]) - timestamp(proof.get("observed_at")) <= 3600,
                "native-foundry-identity-receipt-stale-or-replayed")
        status, _, body = cloud.arm("GET", identifier, FOUNDRY_MI_API, allowed=(200, 404))
        require(status == 200 and str(body.get("id", "")).lower() == identifier
                and foundry_uami_metadata(document, body) == proof.get("identity")
                and digest(body) == proof.get("body_hash"), "native-foundry-identity-receipt-instance-changed")
        matches.append({"run_id": receipt["run_id"], "prepared_at": proof["producer_prepared_at"]})
    require(len(matches) <= 1, "native-foundry-identity-preparation-ambiguous")
    return matches[0] if matches else None


def foundry_identity_projection(cloud, document, source_root):
    data = document["deployment"]["foundry_lifecycle"]
    binding = data["agent_identity_binding"]
    require(binding is not None, "native-foundry-identity-producer-not-selected")
    step = next(step for step in document["deployment"]["steps"] if step["id"] == binding["producer_step"])
    require(step["parameters"].get("miPrjExists") is False and "template_spec_id" not in step,
            "native-foundry-identity-source-producer-required")
    require(not any("template_spec_id" in row for row in document["deployment"]["steps"]),
            "native-foundry-identity-template-spec-unsupported")
    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    owner["project_id"] = document["target"]["project_ids"][0]
    verify_ownership({"tags": step["parameters"].get("tagsProject")}, owner)
    template = copy.deepcopy(cloud.compile_template(source_root, step["template"]))
    require(digest(template) == step["template_hash"], "compiled-template-hash-mismatch")
    resources = template.get("resources")
    require(template.get("languageVersion") == "2.0" and isinstance(resources, dict)
            and {"projectResourceGroup", "namingConvention", "miForPrj"} <= set(resources),
            "native-foundry-identity-source-selectors-required")
    producer, naming, group = (resources[key] for key in ("miForPrj", "namingConvention", "projectResourceGroup"))
    mi = cloud.compile_template(source_root, FOUNDRY_MI_TEMPLATE)
    names = cloud.compile_template(source_root, FOUNDRY_NAMING_TEMPLATE)
    require(producer.get("type") == naming.get("type") == "Microsoft.Resources/deployments"
            and producer.get("properties", {}).get("template") == mi
            and naming.get("properties", {}).get("template") == names
            and (not names.get("resources") or names["resources"] == {"commonResourceGroupRef": {
                "existing": True, "type": "Microsoft.Resources/resourceGroups", "apiVersion": "2024-07-01",
                "subscriptionId": "[parameters('subscriptionIdDevTestProd')]",
                "name": "[parameters('commonResourceGroupName')]"}})
            and producer.get("condition") == "[not(variables('resourceExists').miPrj)]"
            and producer.get("properties", {}).get("parameters") == {
                "name": {"value": "[reference('namingConvention').outputs.namingConvention.value.miPrjName]"},
                "location": {"value": "[parameters('location')]"}, "tags": {"value": "[parameters('tagsProject')]"}}
            and producer.get("resourceGroup") == naming.get("resourceGroup") == "[variables('targetResourceGroup')]"
            and producer.get("subscriptionId") == naming.get("subscriptionId") == "[variables('subscriptionIdDevTestProd')]"
            and group.get("type") == "Microsoft.Resources/resourceGroups"
            and group.get("name") == "[variables('targetResourceGroup')]"
            and group.get("location") == "[parameters('location')]"
            and group.get("tags") == "[parameters('tagsProject')]"
            and set(group) <= {"type", "apiVersion", "name", "location", "tags"},
            "native-foundry-identity-source-selector-mismatch")
    leaves = mi.get("resources")
    require(isinstance(leaves, list) and len(leaves) == 2
            and [row.get("type") for row in leaves] == [
                "Microsoft.ManagedIdentity/userAssignedIdentities", "Microsoft.Authorization/roleAssignments"]
            and set(leaves[0]) == {"type", "apiVersion", "name", "location", "tags"}
            and leaves[0]["apiVersion"] == FOUNDRY_MI_API
            and leaves[0]["name"] == "[parameters('name')]"
            and leaves[0]["location"] == "[parameters('location')]",
            "native-foundry-identity-minimal-source-required")
    producer["properties"]["template"]["resources"] = [copy.deepcopy(leaves[0])]
    producer["properties"]["template"]["outputs"] = {
        key: value for key, value in mi.get("outputs", {}).items() if key in ("managedIdentityName", "managedIdentityId")}
    template["resources"] = {key: resources[key] for key in ("projectResourceGroup", "namingConvention", "miForPrj")}
    for row in template["resources"].values():
        require(set(row.get("dependsOn", [])) <= set(template["resources"]),
                "native-foundry-identity-source-dependency-outside-projection")
    outputs = template.get("outputs", {}).get("foundationOutputs", {}).get("value", {})
    require(outputs.get("miProjectName") == producer["properties"]["parameters"]["name"]["value"]
            and outputs.get("projectResourceGroupName") == group["name"],
            "native-foundry-identity-source-output-mismatch")
    template["outputs"] = {"foundationOutputs": {"type": "object", "value": {
        key: outputs[key] for key in ("miProjectName", "projectResourceGroupName")}}}
    return {"location": document["target"]["region"], "properties": {
        "mode": "Incremental", "template": template,
        "parameters": {key: {"value": value} for key, value in step["parameters"].items()}}}


def validate_foundry_identity_stage(document):
    stage = document["deployment"].get("foundry_identity_stage")
    require(isinstance(stage, dict) and stage.get("contract") == FOUNDRY_IDENTITY_CONTRACT
            and stage.get("binding_hash") == foundry_identity_context(document)
            and hash_value(stage.get("payload_hash")) and stage.get("approval_purpose") == "identity-only"
            and stage.get("continuation_requires_new_approval") is True,
            "native-foundry-identity-stage-binding-mismatch")
    identifier, group = stage.get("resource_id", ""), stage.get("resource_group", "")
    require(NESTED_ID.fullmatch(identifier) and identifier == identifier.lower()
            and resource_type_from_id(identifier) == "microsoft.managedidentity/userassignedidentities"
            and group == arm_scope(identifier)
            and group in {scope.lower() for scope in document["locks"]["scopes"]},
            "native-foundry-identity-stage-scope-mismatch")
    changes = stage.get("changes")
    require(isinstance(changes, list) and len(changes) == 2
            and {row.get("resource_id") for row in changes} == {identifier, group}
            and all(row.get("change_type") in ("Create", "NoChange") and hash_value(row.get("after_hash"))
                    for row in changes)
            and next(row for row in changes if row["resource_id"] == identifier)["change_type"] == "Create"
            and stage.get("source_changes") == {row["resource_id"]: row["change_type"] for row in changes}
            and document["deployment"]["changes"] == changes
            and "account_resource_id" not in document["deployment"]["foundry_lifecycle"]
            and "foundry_identity_continuation" not in document["deployment"],
            "native-foundry-identity-stage-footprint-invalid")


def foundry_identity_snapshot(cloud, group):
    status, _, body = cloud.arm("GET", group, RG_API, allowed=(200, 404))
    if status == 404:
        return {"group": None, "resources": {}}
    closure, bodies = collect_resource_closure(cloud, [group])
    require(group in bodies and digest(bodies[group]) == digest(body), "native-foundry-identity-group-drift")
    return {"group": digest(body), "resources": {key: digest(value) for key, value in bodies.items() if key != group}}


def freeze_foundry_identity_stage(cloud, document, source_root, *, sleep=time.sleep):
    """Return before dependent previews on a cold run; never materialize an identity while preparing."""
    plan = document["deployment"]
    data = plan.get("foundry_lifecycle")
    if not data or not data["agent_identity_binding"]:
        return False
    payload = foundry_identity_projection(cloud, document, source_root)
    captured, provenance = {}, {}
    changes = evaluate_what_if(cloud, document, {"id": "foundry-identity-producer", "scope": "subscription"},
                               payload, sleep, resource_payloads=captured, source_changes=provenance)
    identities = [row["resource_id"] for row in changes
                  if resource_type_from_id(row["resource_id"]) == "microsoft.managedidentity/userassignedidentities"]
    require(len(identities) == 1 and NESTED_ID.fullmatch(identities[0]),
            "native-foundry-identity-source-preview-incomplete")
    identifier = identities[0]
    group = arm_scope(identifier)
    require(group in {scope.lower() for scope in document["locks"]["scopes"]}
            and {row["resource_id"] for row in changes} == {group, identifier}
            and all(provenance.get(row["resource_id"]) in ("Create", "NoChange") for row in changes),
            "native-foundry-identity-preview-footprint-invalid")
    status, _, body = cloud.arm("GET", identifier, FOUNDRY_MI_API, allowed=(200, 404))
    if status == 200:
        require("foundry_identity_stage" not in plan, "native-foundry-identity-stage-already-materialized")
        evidence = plan.get("known_ownership", {}).get(identifier)
        require(isinstance(evidence, dict) and guid(evidence.get("run_id")) and hash_value(evidence.get("receipt_hash")),
                "native-foundry-identity-producer-receipt-required")
        _, _, receipt = coordination(cloud, document).request("GET", "runs/" + evidence["run_id"] + ".worker.json")
        require(digest(receipt) == evidence["receipt_hash"], "native-foundry-identity-receipt-hash-mismatch")
        verify_foundry_identity_receipt(document, receipt, continuation=True)
        proof = receipt["foundry_identity_receipt"]
        require(proof["payload_hash"] == digest(payload) and proof["resource_id"] == identifier
                and proof["identity"] == foundry_uami_metadata(document, body)
                and proof["body_hash"] == digest(body),
                "native-foundry-identity-receipt-instance-changed")
        bound = {"run_id": receipt["run_id"], "receipt_hash": digest(receipt),
                 "proof": copy.deepcopy(proof)}
        require("foundry_identity_continuation" not in plan or plan["foundry_identity_continuation"] == bound,
                "native-foundry-identity-continuation-changed")
        plan["foundry_identity_continuation"] = bound
        validate_foundry_identity_continuation(document)
        return False
    require("foundry_identity_continuation" not in plan, "native-foundry-identity-continuation-missing-instance")
    status, _, group_body = cloud.arm("GET", group, RG_API, allowed=(200, 404))
    if status == 200:
        verify_ownership(group_body, {**{key: document["target"][key] for key in ("factory_id", "scaleset_id")},
                                      "project_id": document["target"]["project_ids"][0]})
    stage = {"contract": FOUNDRY_IDENTITY_CONTRACT, "approval_purpose": "identity-only",
             "continuation_requires_new_approval": True, "binding_hash": foundry_identity_context(document),
             "payload_hash": digest(payload), "resource_id": identifier, "resource_group": group,
             "changes": changes, "source_changes": provenance,
             "before": foundry_identity_snapshot(cloud, group)}
    require("foundry_identity_stage" not in plan or plan["foundry_identity_stage"] == stage,
            "native-foundry-identity-stage-changed")
    plan["foundry_identity_stage"] = stage
    plan["changes"] = changes
    validate_foundry_identity_stage(document)
    verify_bootstrap_preservation(document, changes)
    return True


def verify_foundry_identity_receipt_effects(document, receipt):
    """Check the minimal receipt footprint; context, provenance and freshness require separate verification."""
    require(isinstance(receipt, dict) and isinstance(receipt.get("foundry_identity_receipt"), dict)
            and set(receipt) <= {
                "schema", "run_id", "manifest_hash", "source_commit", "target", "status", "deployments",
                "ownership", "resource_groups", "mutation_started", "updated_at", "completion",
                "continuation_required", "inventory_closure_hash", "foundry_identity_receipt",
                "foundry_identity_final_closure"},
            "native-foundry-identity-receipt-invalid")
    proof = receipt.get("foundry_identity_receipt", {})
    require(receipt.get("schema") == 1 and receipt.get("status") == "succeeded"
            and receipt.get("completion") == "identity-only" and receipt.get("continuation_required") is True
            and receipt.get("source_commit") == document["source"]["commit"]
            and receipt.get("target") == document["target"]
            and guid(receipt.get("run_id")) and hash_value(receipt.get("manifest_hash"))
            and proof.get("contract") == FOUNDRY_IDENTITY_CONTRACT
            and hash_value(proof.get("binding_hash")) and hash_value(proof.get("request_hash"))
            and proof.get("producer_run_id") == receipt["run_id"]
            and proof.get("producer_manifest_hash") == receipt["manifest_hash"]
            and hash_value(proof.get("payload_hash")) and hash_value(proof.get("body_hash"))
            and proof.get("role_writes") == [] and proof.get("full_project_executed") is False
            and isinstance(document["target"].get("project_ids"), list)
            and len(document["target"]["project_ids"]) == 1,
            "native-foundry-identity-receipt-invalid")
    observed = proof.get("identity", {})
    require(all(foundry_identity_guid(observed.get(key)) for key in ("principal_id", "client_id", "tenant_id"))
            and observed["principal_id"] != observed["client_id"]
            and observed["tenant_id"] == document["target"]["tenant_id"].lower(),
            "native-foundry-identity-receipt-guid-invalid")
    identifier, group = proof.get("resource_id", ""), proof.get("resource_group", "")
    require(NESTED_ID.fullmatch(identifier) and identifier == identifier.lower()
            and resource_type_from_id(identifier) == "microsoft.managedidentity/userassignedidentities"
            and group == arm_scope(identifier) and group in {scope.lower() for scope in document["locks"]["scopes"]}
            and receipt.get("deployments") == [{"step_id": "foundry-identity-producer",
                "id": deployment_endpoint({**document, "run_id": receipt["run_id"]},
                    {"id": "foundry-identity-producer", "scope": "subscription"}).removeprefix(ARM), "status": "succeeded"}],
            "native-foundry-identity-receipt-scope-invalid")
    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    owner["project_id"] = document["target"]["project_ids"][0]
    require(isinstance(receipt.get("ownership"), list) and len(receipt["ownership"]) == 1
            and receipt["ownership"][0].get("resource_id") == identifier
            and receipt["ownership"][0].get("body_hash") == proof["body_hash"]
            and receipt["ownership"][0].get("owner") == owner
            and isinstance(receipt.get("resource_groups"), list) and len(receipt["resource_groups"]) == 1
            and receipt["resource_groups"][0].get("resource_id") == group
            and receipt["resource_groups"][0].get("owner") == owner
            and hash_value(receipt["resource_groups"][0].get("body_hash"))
            and hash_value(receipt.get("inventory_closure_hash")),
            "native-foundry-identity-receipt-ownership-incomplete")
    closure = receipt.get("foundry_identity_final_closure")
    observations = foundry_inventory_observations(document, closure)
    before = proof.get("before")
    require(isinstance(before, dict) and set(before) == {"group", "resources"}
            and isinstance(before["resources"], dict)
            and identifier not in before["resources"] and group not in before["resources"]
            and all(hash_value(value) for value in before["resources"].values())
            and (before["group"] is None or hash_value(before["group"]))
            and set(closure["groups"]) == {group}
            and set(closure["resources"]) == {identifier, *before["resources"]}
            and digest(closure) == receipt["inventory_closure_hash"]
            and all(observations[key]["body_hash"] == value for key, value in before["resources"].items())
            and (before["group"] is None or observations[group]["body_hash"] == before["group"])
            and observations[identifier]["body_hash"] == proof["body_hash"]
            and receipt["resource_groups"][0]["body_hash"] == observations[group]["body_hash"]
            and all(receipt["ownership"][0].get(key) == closure["resources"][identifier].get(key)
                    for key in ("body_hash", "type", "api_version", "etag")),
            "native-foundry-identity-final-instance-evidence-changed")
    at = timestamp(proof.get("observed_at"))
    require(timestamp(proof.get("producer_prepared_at")) <= at, "native-foundry-identity-receipt-time-invalid")


def verify_foundry_identity_receipt(document, receipt, *, continuation=False):
    verify_foundry_identity_receipt_effects(document, receipt)
    proof = receipt["foundry_identity_receipt"]
    require(proof["binding_hash"] == foundry_identity_context(document)
            and proof["request_hash"] == foundry_identity_request_context(document),
            "native-foundry-identity-receipt-invalid")
    at = timestamp(proof["observed_at"])
    if continuation:
        require(receipt["run_id"] != document["run_id"]
                and 0 <= timestamp(document["prepared_at"]) - at <= 3600,
                "native-foundry-identity-receipt-stale-or-replayed")
    else:
        validate_foundry_identity_stage(document)
        stage = document["deployment"]["foundry_identity_stage"]
        require(receipt["run_id"] == document["run_id"] and receipt["manifest_hash"] == document["manifest_hash"]
                and proof["producer_prepared_at"] == document["prepared_at"]
                and proof["payload_hash"] == stage["payload_hash"] and proof["resource_id"] == stage["resource_id"]
                and proof["before"] == stage["before"]
                and at >= timestamp(document["prepared_at"]), "native-foundry-identity-receipt-run-mismatch")


def run_foundry_identity_stage(cloud, locks, document, source_root, receipt, persist, sleep):
    stage = document["deployment"]["foundry_identity_stage"]
    validate_foundry_identity_stage(document)
    refreshed = copy.deepcopy(document)
    require(freeze_foundry_identity_stage(cloud, refreshed, source_root, sleep=sleep),
            "native-foundry-identity-stage-required")
    payload = foundry_identity_projection(cloud, document, source_root)
    locks.assert_held()
    locks.authorize(document)
    require(foundry_identity_snapshot(cloud, stage["resource_group"]) == stage["before"],
            "native-foundry-identity-instance-changed-before-write")
    status, _, _ = cloud.arm("GET", stage["resource_id"], FOUNDRY_MI_API, allowed=(200, 404))
    require(status == 404, "native-foundry-identity-stage-already-materialized")
    locks.assert_held()
    locks.authorize(document)
    endpoint = deployment_endpoint(document, {"id": "foundry-identity-producer", "scope": "subscription"})
    receipt.update(pending_deployment=endpoint.removeprefix(ARM), mutation_started=True)
    persist()
    locks.assert_held()
    status, _, _ = cloud.arm("GET", stage["resource_id"], FOUNDRY_MI_API, allowed=(200, 404))
    require(status == 404, "native-foundry-identity-stage-already-materialized")
    require(foundry_identity_snapshot(cloud, stage["resource_group"]) == stage["before"],
            "native-foundry-identity-instance-changed-before-write")
    locks.authorize(document)
    cloud.request("PUT", endpoint + "?api-version=2022-09-01", ARM, data=payload, allowed=(200, 201, 202))
    result = wait_foundry_resource(cloud, locks, endpoint.removeprefix(ARM),
        lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded", sleep, attempts=1440,
        read=lambda: cloud.request("GET", endpoint + "?api-version=2022-09-01", ARM), document=document)
    outputs = result.get("properties", {}).get("outputs", {}).get("foundationOutputs", {}).get("value", {})
    require(isinstance(outputs.get("miProjectName"), str) and isinstance(outputs.get("projectResourceGroupName"), str)
            and ("/subscriptions/" + document["target"]["subscription_id"] + "/resourceGroups/"
                 + outputs["projectResourceGroupName"] + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
                 + outputs["miProjectName"]).lower() == stage["resource_id"],
            "native-foundry-identity-output-mismatch")
    def materialized(value):
        properties = value.get("properties", {})
        require(isinstance(properties, dict), "native-foundry-agent-identifiers-invalid")
        if any(properties.get(key) in (None, "") for key in ("principalId", "clientId", "tenantId")):
            return False
        return bool(foundry_uami_metadata(document, value))
    body = wait_foundry_resource(cloud, locks, stage["resource_id"], materialized, sleep,
        api_version=FOUNDRY_MI_API, document=document)
    metadata = foundry_uami_metadata(document, body)
    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    owner["project_id"] = document["target"]["project_ids"][0]
    verify_ownership(body, owner)
    closure, bodies = collect_resource_closure(cloud, [stage["resource_group"]])
    require(set(bodies) == {stage["resource_group"], stage["resource_id"], *stage["before"]["resources"]}
            and all(digest(bodies[key]) == value for key, value in stage["before"]["resources"].items())
            and (stage["before"]["group"] is None
                 or digest(bodies[stage["resource_group"]]) == stage["before"]["group"])
            and digest(bodies[stage["resource_id"]]) == digest(body),
            "native-foundry-identity-unreviewed-side-effects")
    group = bodies[stage["resource_group"]]
    verify_ownership(group, owner)
    receipt.update(completion="identity-only", continuation_required=True,
        deployments=[{"step_id": "foundry-identity-producer", "id": endpoint.removeprefix(ARM), "status": "succeeded"}],
        ownership=[{"resource_id": stage["resource_id"], "owner": owner,
                    **closure["resources"][stage["resource_id"]]}],
        resource_groups=[{"resource_id": stage["resource_group"], "owner": owner, "body_hash": digest(group),
                          "etag": group.get("etag")}], inventory_closure_hash=digest(closure),
        foundry_identity_final_closure=copy.deepcopy(closure),
        foundry_identity_receipt={"contract": FOUNDRY_IDENTITY_CONTRACT, "binding_hash": stage["binding_hash"],
            "before": copy.deepcopy(stage["before"]),
            "request_hash": foundry_identity_request_context(document), "producer_prepared_at": document["prepared_at"],
            "payload_hash": stage["payload_hash"], "producer_run_id": document["run_id"],
            "producer_manifest_hash": document["manifest_hash"], "resource_id": stage["resource_id"],
            "resource_group": stage["resource_group"], "body_hash": digest(body), "identity": metadata,
            "observed_at": utc_now(), "role_writes": [], "full_project_executed": False})
    receipt["status"] = "succeeded"
    receipt.pop("pending_deployment", None)
    verify_foundry_identity_receipt(document, receipt)
    current, current_bodies = collect_resource_closure(cloud, [stage["resource_group"]])
    require(digest(current) == digest(closure)
            and foundry_inventory_observations(document, current, current_bodies)
                == foundry_inventory_observations(document, closure, bodies),
            "native-foundry-identity-final-instance-evidence-changed")
    locks.authorize(document)
    persist()


def foundry_module_reference(symbol, resource):
    if symbol is not None:
        return "reference('" + symbol + "')"
    def expression(value):
        require(isinstance(value, str) and value.startswith("[") and value.endswith("]"),
                "native-foundry-identity-reference-unresolved")
        return value[1:-1]
    return ("reference(extensionResourceId(format('/subscriptions/{0}/resourceGroups/{1}', "
            + expression(resource.get("subscriptionId")) + ", " + expression(resource.get("resourceGroup"))
            + "), 'Microsoft.Resources/deployments', " + expression(resource.get("name"))
            + "), '2022-09-01')")


def validate_foundry_identity_continuation(document):
    bound = document["deployment"].get("foundry_identity_continuation")
    if bound is None:
        return
    require(isinstance(bound, dict) and guid(bound.get("run_id")) and hash_value(bound.get("receipt_hash"))
            and bound["run_id"] != document["run_id"] and isinstance(bound.get("proof"), dict),
            "native-foundry-identity-continuation-invalid")
    proof = bound["proof"]
    identifier = proof.get("resource_id", "")
    identity = proof.get("identity", {})
    require(proof.get("contract") == FOUNDRY_IDENTITY_CONTRACT
            and proof.get("binding_hash") == foundry_identity_context(document)
            and proof.get("request_hash") == foundry_identity_request_context(document)
            and proof.get("producer_run_id") == bound["run_id"]
            and hash_value(proof.get("producer_manifest_hash")) and hash_value(proof.get("payload_hash"))
            and hash_value(proof.get("body_hash"))
            and NESTED_ID.fullmatch(identifier) and identifier == identifier.lower()
            and resource_type_from_id(identifier) == "microsoft.managedidentity/userassignedidentities"
            and proof.get("resource_group") == arm_scope(identifier)
            and arm_scope(identifier) in {scope.lower() for scope in document["locks"]["scopes"]}
            and isinstance(identity, dict)
            and all(foundry_identity_guid(identity.get(key)) for key in ("principal_id", "client_id", "tenant_id"))
            and identity["principal_id"] != identity["client_id"]
            and identity["tenant_id"] == document["target"]["tenant_id"].lower()
            and identity.get("provisioning_state") in (None, "Succeeded")
            and proof.get("role_writes") == [] and proof.get("full_project_executed") is False
            and timestamp(proof.get("producer_prepared_at")) <= timestamp(proof.get("observed_at"))
            and 0 <= timestamp(document["prepared_at"]) - timestamp(proof.get("observed_at")) <= 3600,
            "native-foundry-identity-continuation-binding-mismatch")


def foundry_replace_outputs(template, replacements):
    """Replace only source-selected module output expressions in their owning ARM scope."""
    def literal(value):
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        require(isinstance(value, list) and all(isinstance(item, str) for item in value),
                "native-foundry-identity-literal-invalid")
        return "createArray(" + ", ".join(literal(item) for item in value) + ")"
    def visit(value):
        if isinstance(value, dict):
            return {key: child if key == "template" else visit(child) for key, child in value.items()}
        if isinstance(value, list):
            return [visit(child) for child in value]
        if not isinstance(value, str) or not value.startswith("["):
            return value
        for expression, replacement in replacements.items():
            if value == "[" + expression + "]":
                return copy.deepcopy(replacement)
            value = value.replace(expression, literal(replacement))
        return value
    return visit(template)


def bind_foundry_identity_template(cloud, document, step, source_root, template):
    continuation = document["deployment"].get("foundry_identity_continuation")
    if continuation is None:
        return template
    validate_foundry_identity_continuation(document)
    require("template_spec_id" not in step, "native-foundry-identity-template-spec-unsupported")
    proof = continuation.get("proof", {})
    require(proof.get("binding_hash") == foundry_identity_context(document),
            "native-foundry-identity-continuation-binding-mismatch")
    identity = proof.get("identity", {})
    require(all(foundry_identity_guid(identity.get(key)) for key in ("principal_id", "client_id", "tenant_id"))
            and identity["tenant_id"] == document["target"]["tenant_id"].lower(),
            "native-foundry-identity-continuation-guid-invalid")
    template = copy.deepcopy(template)
    resources = template.get("resources", {})
    items = list(resources.items()) if isinstance(resources, dict) else [(None, row) for row in resources]
    module_outputs = {"principalId": identity["principal_id"], "clientId": identity["client_id"],
                      "resourceId": proof["resource_id"], "name": proof["resource_id"].rsplit("/", 1)[-1]}
    replacements = {}
    if step["template"] == FOUNDRY_FOUNDATION:
        # Revalidate the role-free slice before modifying the full source's dependent grant.
        require(digest(foundry_identity_projection(cloud, document, source_root)) == proof["payload_hash"],
                "native-foundry-identity-projection-changed")
        mi = template["resources"]["miForPrj"]["properties"]["template"]
        role = mi["resources"][1]
        require(role.get("properties", {}).get("principalId") ==
                "[reference(resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', parameters('name')), '2024-11-30').principalId]",
                "native-foundry-identity-source-role-selector-mismatch")
        role["properties"]["principalId"] = identity["principal_id"]
        require(all(value == "[resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', parameters('name'))]"
                    for value in role.get("dependsOn", [])),
                "native-foundry-identity-source-role-dependency-mismatch")
        role.pop("dependsOn", None)
        mi["resources"] = [role]
        for key, value in {"managedIdentityPrincipalId": identity["principal_id"],
                           "managedIdentityClientId": identity["client_id"],
                           "managedIdentityName": module_outputs["name"],
                           "managedIdentityId": proof["resource_id"]}.items():
            if key in mi.get("outputs", {}):
                mi["outputs"][key]["value"] = value
                replacements["reference('miForPrj').outputs." + key + ".value"] = value
    else:
        candidates = [(symbol, resource) for symbol, resource in items
                      if "managedIdentityName" in resource.get("properties", {}).get("parameters", {})]
        lookup_source = cloud.compile_template(source_root, FOUNDRY_LOOKUP_TEMPLATE) if candidates else None
        lookups = [(symbol, resource) for symbol, resource in candidates
                   if resource.get("properties", {}).get("template") == lookup_source]
        if lookups:
            foundation = next(row for row in document["deployment"]["steps"] if row["template"] == FOUNDRY_FOUNDATION)
            naming_source = cloud.compile_template(source_root, FOUNDRY_NAMING_TEMPLATE)
            naming = [(symbol, resource) for symbol, resource in items
                      if resource.get("properties", {}).get("template") == naming_source]
            require(len(naming) == 1, "native-foundry-identity-naming-source-required")
            name_reference = foundry_module_reference(*naming[0])
            for symbol, resource in lookups:
                selector = resource.get("properties", {}).get("parameters", {}).get("managedIdentityName")
                if selector not in (
                        {"value": "[" + name_reference + ".outputs.miPrjName.value]"},
                        {"value": "[" + name_reference + ".outputs.namingConvention.value.miPrjName]"}):
                    continue
                require(resource.get("resourceGroup") == "[variables('targetResourceGroup')]"
                        and all(step["parameters"].get(key) == foundation["parameters"].get(key) for key in (
                            "projectNumber", "env", "locationSuffix", "resourceSuffix", "commonResourceSuffix",
                            "aifactorySalt10char", "randomValue", "commonRGNamePrefix", "aifactorySuffixRG",
                            "commonResourceGroup_param", "commonResourceName", "projectPrefix", "projectSuffix"))
                        and template.get("variables", {}).get("targetResourceGroup") ==
                        cloud.compile_template(source_root, FOUNDRY_FOUNDATION).get("variables", {}).get("targetResourceGroup"),
                        "native-foundry-identity-source-naming-mismatch")
                reference = foundry_module_reference(symbol, resource)
                for key, value in module_outputs.items():
                    require(key in resource["properties"]["template"].get("outputs", {}),
                            "native-foundry-identity-source-output-missing")
                    resource["properties"]["template"]["outputs"][key]["value"] = value
                    replacements[reference + ".outputs." + key + ".value"] = value
    template = foundry_replace_outputs(template, replacements)
    resources = template.get("resources", {})
    items = list(resources.items()) if isinstance(resources, dict) else [(None, row) for row in resources]
    arrays = {}
    for symbol, resource in items:
        properties = resource.get("properties", {})
        if (properties.get("parameters", {}).get("managedIdentityOID") != {"value": identity["principal_id"]}
                or properties.get("template") != cloud.compile_template(source_root, FOUNDRY_ARRAY_TEMPLATE)):
            continue
        parameters = properties["parameters"]
        secret_name = step["parameters"].get("projectServicePrincipleOID_SeedingKeyvaultName")
        require(parameters.get("includeManagedIdentity", {"value": True}) == {"value": True}
                and (parameters.get("servicePrincipleOIDFromSecret") == {"value": ""}
                     or isinstance(secret_name, str) and (
                         not secret_name or "<todo>" in secret_name.lower() or "<optional>" in secret_name.lower())),
                "native-foundry-identity-source-passwordless-array-required")
        parameters["servicePrincipleOIDFromSecret"] = {"value": ""}
        properties["template"]["outputs"]["spAndMiArray"]["value"] = [identity["principal_id"]]
        arrays[foundry_module_reference(symbol, resource) + ".outputs.spAndMiArray.value"] = [identity["principal_id"]]
    return foundry_replace_outputs(template, arrays)


def verify_foundry_identity_current(cloud, locks, document):
    bound = document["deployment"].get("foundry_identity_continuation")
    if bound is None:
        return
    validate_foundry_identity_continuation(document)
    _, _, receipt = locks.request("GET", "runs/" + bound["run_id"] + ".worker.json")
    require(digest(receipt) == bound["receipt_hash"] and receipt.get("foundry_identity_receipt") == bound["proof"],
            "native-foundry-identity-continuation-receipt-changed")
    verify_foundry_identity_receipt(document, receipt, continuation=True)
    proof = bound["proof"]
    status, _, body = cloud.arm("GET", proof["resource_id"], FOUNDRY_MI_API, allowed=(200, 404))
    require(status == 200 and str(body.get("id", "")).lower() == proof["resource_id"]
            and foundry_uami_metadata(document, body) == proof["identity"] and digest(body) == proof["body_hash"],
            "native-foundry-identity-continuation-instance-changed")
    locks.assert_held()
    locks.authorize(document)


def foundry_first_run(parameters):
    if parameters.get("enableAIFoundry") is False:
        return False
    require(parameters.get("enableAIFoundry") is True
            and type(parameters.get("aiFoundryV2Exists")) is bool
            and type(parameters.get("foundryV22AccountOnly")) is bool,
            "native-foundry-topology-unverified")
    return parameters["aiFoundryV2Exists"] is False


def plan_foundry_lifecycle(document):
    """Expand one non-CMK, non-AVM first run; no resource existence is inferred."""
    plan = document["deployment"]
    require("foundry_lifecycle" not in plan, "native-foundry-already-planned")
    candidates = [step for step in plan["steps"] if step["template"] == FOUNDRY_TEMPLATE
                  and foundry_first_run(step["parameters"])]
    if not candidates:
        return
    require(len(candidates) == 1 and document["operation"] == "deploy-project",
            "native-foundry-single-project-required")
    require(not plan.get("persona_access"), "native-foundry-persona-write-evidence-required")
    full = candidates[0]
    p = full["parameters"]
    require(document["target"]["project_ids"] == [full.get("project_id")]
            and p.get("projectNumber") == full.get("project_id"),
            "native-foundry-single-project-required")
    require(p["foundryV22AccountOnly"] is False and p.get("useAVMFoundry") is False
            and (p.get("cmk") is False or p.get("cmk") is True and p.get("cmkDisableForFoundry") is True)
            and type(p.get("disableAgentNetworkInjection")) is bool
            and isinstance(p.get("aca2SubnetId"), str)
            and p.get("aiFoundryV2ProjectExists") is False,
            "native-foundry-supported-topology-required")
    defender_resource = p.get("enableDefenderforAIResourceLevel", False)
    defender_subscription = p.get("enableDefenderforAISubLevel", False)
    require(type(defender_resource) is bool and type(defender_subscription) is bool
            and not (defender_resource and not defender_subscription),
            "native-foundry-defender-phase-order-required")
    network = []
    if p["disableAgentNetworkInjection"] is False and p["aca2SubnetId"]:
        subnet = p["aca2SubnetId"].lower()
        require(NESTED_ID.fullmatch(subnet)
                and resource_type_from_id(subnet) == "microsoft.network/virtualnetworks/subnets"
                and arm_scope(subnet) in {scope.lower() for scope in document["locks"]["scopes"]},
                "native-foundry-owned-agent-subnet-required")
        network = [subnet.rsplit("/subnets/", 1)[0], subnet]
    index = plan["steps"].index(full)
    require(index > 0, "native-foundry-prerequisite-phases-required")
    foundation_steps = [step for step in plan["steps"][:index] if step["template"] == FOUNDRY_FOUNDATION]
    rbac_steps = [step for step in plan["steps"][:index] if step["template"] == FOUNDRY_NETWORK_RBAC]
    require(not network or len(foundation_steps) == len(rbac_steps) == 1,
            "native-foundry-agent-prerequisite-source-required")
    account = copy.deepcopy(full)
    account["id"] = "foundry-account"
    require(account["id"] not in {step["id"] for step in plan["steps"]},
            "native-foundry-account-step-collision")
    account["parameters"]["foundryV22AccountOnly"] = True
    account.pop("changes", None)
    full["depends_on"] = [account["id"]]
    plan["steps"].insert(index, account)
    plan["foundry_lifecycle"] = {
        "contract": FOUNDRY_CONTRACT, "account_step": account["id"], "full_step": full["id"],
        "full_parameters_hash": digest(p), "network_scopes": network,
        "role_definition_id": "/subscriptions/" + document["target"]["subscription_id"]
                              + "/providers/Microsoft.Authorization/roleDefinitions/" + FOUNDRY_NETWORK_ROLE,
        "require_capability_host": bool(network),
        "principal_binding": {
            "contract": "foundry-account-system-identity-v1",
            "source_commit": document["source"]["commit"],
            "template": FOUNDRY_TEMPLATE,
            "module": "aiFoundry2025NoAvmV22AccountOnly", "resource": "aiAccount",
            "producer_phase": "foundry-account-phase", "producer_step": account["id"],
            "resource_id_output": ["properties", "outputs", "aiFoundryV2ResourceId", "value"],
            "resource_name_output": ["properties", "outputs", "aiFoundryV2Name", "value"],
            "resolved_resource_id_field": "deployment.foundry_lifecycle.account_resource_id",
            "principal_property": ["identity", "principalId"], "tenant_property": ["identity", "tenantId"],
            "api_version": FOUNDRY_API, "tenant_id": document["target"]["tenant_id"],
            "subscription_id": document["target"]["subscription_id"],
            "required_gates": ["account-identity"] + (
                ["configured-agent-network-ready"] if network else []),
            "before_phase": "foundry-project-phase", "before_step": full["id"],
        },
        "agent_identity_binding": ({
            "contract": "foundry-source-project-uami-v1", "source_commit": document["source"]["commit"],
            "template": FOUNDRY_TEMPLATE, "module": "getProjectMIPrincipalId",
            "module_template": "environment_setup/aifactory/bicep/modules/get-managed-identity-info.bicep",
            "module_output": "resourceId",
            "account_identity_selector": ["identity", "userAssignedIdentities"],
            "producer_phase": "foundry-prerequisites", "producer_step": foundation_steps[0]["id"],
            "producer_template": FOUNDRY_FOUNDATION,
            "name_output": ["properties", "outputs", "foundationOutputs", "value", "miProjectName"],
            "group_output": ["properties", "outputs", "foundationOutputs", "value", "projectResourceGroupName"],
            "principal_property": ["properties", "principalId"], "tenant_property": ["properties", "tenantId"],
            "client_property": ["properties", "clientId"], "api_version": FOUNDRY_MI_API,
            "tenant_id": document["target"]["tenant_id"], "subscription_id": document["target"]["subscription_id"],
            "grant_step": rbac_steps[0]["id"], "grant_template": FOUNDRY_NETWORK_RBAC,
            "grant_module": "cmnRbacVNet", "grant_resource": "networkContributorSPVnet",
            "grant_scope": network[0], "grant_role": FOUNDRY_NETWORK_ROLE,
            "required_gates": ["agent-uami-identity", "agent-network-role-observation"],
            "before_phase": "foundry-account-phase", "before_step": account["id"],
        } if network else None),
        "phases": [
            {"id": "foundry-prerequisites", "step_ids": [step["id"] for step in plan["steps"][:index]]},
            {"id": "foundry-account-phase", "step_ids": [account["id"]]},
            {"id": "foundry-project-phase", "step_ids": [step["id"] for step in plan["steps"][index + 1:]]},
        ],
    }


def validate_foundry_lifecycle(document):
    plan = document.get("deployment", {})
    steps = plan.get("steps", [])
    first = [step for step in steps if step.get("template") == FOUNDRY_TEMPLATE
             and foundry_first_run(step.get("parameters", {}))]
    data = plan.get("foundry_lifecycle")
    require(not any(key in plan for key in ("foundry_identity_stage", "foundry_identity_continuation")) or data,
            "native-foundry-identity-sequence-required")
    if not first:
        require(data is None and not any(step.get("template") == FOUNDRY_TEMPLATE
                and step.get("parameters", {}).get("foundryV22AccountOnly") is True for step in steps),
                "native-foundry-account-only-incomplete")
        return
    require(isinstance(data, dict) and data.get("contract") == FOUNDRY_CONTRACT and len(first) == 2,
            "native-foundry-sequence-required")
    account, full = first
    require(account["id"] == data.get("account_step") and full["id"] == data.get("full_step")
            and account["parameters"].get("foundryV22AccountOnly") is True
            and full["parameters"].get("foundryV22AccountOnly") is False
            and digest(full["parameters"]) == data.get("full_parameters_hash"),
            "native-foundry-phase-binding-mismatch")
    # Reconstruct the pure expansion instead of trusting caller-supplied grant scopes.
    draft = copy.deepcopy(document)
    draft["deployment"].pop("foundry_lifecycle")
    draft["deployment"]["steps"].remove(draft["deployment"]["steps"][steps.index(account)])
    restored = next(step for step in draft["deployment"]["steps"] if step["id"] == full["id"])
    restored["depends_on"] = account["depends_on"]
    plan_foundry_lifecycle(draft)
    expected = draft["deployment"]["foundry_lifecycle"]
    require(all(data.get(key) == value for key, value in expected.items() if key != "phases")
            and [{key: phase.get(key) for key in ("id", "step_ids")} for phase in data.get("phases", [])]
            == expected["phases"]
            and plan["steps"] == draft["deployment"]["steps"],
            "native-foundry-phase-binding-mismatch")
    if "foundry_identity_stage" in plan:
        validate_foundry_identity_stage(document)
    validate_foundry_identity_continuation(document)
    if "account_resource_id" in data:
        identifier = data["account_resource_id"]
        require(isinstance(identifier, str) and NESTED_ID.fullmatch(identifier)
                and resource_type_from_id(identifier) == "microsoft.cognitiveservices/accounts"
                and arm_scope(identifier) in {scope.lower() for scope in document["locks"]["scopes"]},
                "native-foundry-account-binding-invalid")
        phases = data["phases"]
        for phase in phases:
            changes = phase.get("changes")
            require(isinstance(changes, list) and all(isinstance(row, dict)
                    and isinstance(row.get("resource_id"), str)
                    and (RG_ID.fullmatch(row["resource_id"]) or NESTED_ID.fullmatch(row["resource_id"]))
                    and arm_scope(row["resource_id"]) in {scope.lower() for scope in document["locks"]["scopes"]}
                    and row.get("change_type") in ("Create", "Modify", "NoChange") for row in changes),
                    "native-foundry-frozen-phases-required")
            require(len({row["resource_id"].lower() for row in changes}) == len(changes),
                    "native-foundry-duplicate-phase-change")
            source_changes = phase.get("source_changes")
            require(isinstance(source_changes, dict)
                    and set(source_changes) == {row["resource_id"] for row in changes}
                    and all(source_changes[row["resource_id"]] == row["change_type"]
                            or source_changes[row["resource_id"]] == "Ignore"
                            and row["change_type"] == "NoChange" for row in changes),
                    "native-foundry-phase-source-provenance-required")
        prior_ids = {row["resource_id"] for row in phases[0]["changes"]}
        added = [row["resource_id"] for row in phases[1]["changes"] if row["change_type"] == "Create"
                 and row["resource_id"] not in prior_ids
                 and resource_type_from_id(row["resource_id"]) == "microsoft.cognitiveservices/accounts"]
        require(added == [identifier] and phases[-1]["changes"] == plan["changes"],
                "native-foundry-account-preview-binding-mismatch")
        if data["agent_identity_binding"]:
            validate_foundry_agent_binding(document)
        else:
            require("agent_identity" not in data, "native-foundry-unexpected-agent-identity")


def foundry_selected_uami(account):
    identity = account.get("identity", {})
    require(isinstance(identity, dict), "native-foundry-source-uami-required")
    kinds = {value.strip().lower() for value in str(identity.get("type", "")).split(",")}
    assigned = identity.get("userAssignedIdentities")
    require(kinds == {"systemassigned", "userassigned"} and isinstance(assigned, dict) and len(assigned) == 1,
            "native-foundry-source-uami-required")
    identifier = next(iter(assigned)).lower()
    require(NESTED_ID.fullmatch(identifier)
            and resource_type_from_id(identifier) == "microsoft.managedidentity/userassignedidentities",
            "native-foundry-source-uami-required")
    return identifier


def foundry_grant_scope(identifier):
    return identifier.lower().rsplit("/providers/microsoft.authorization/roleassignments/", 1)[0]


def verify_foundry_source_grants(document, source_changes):
    data = document["deployment"]["foundry_lifecycle"]
    if not data["agent_identity_binding"]:
        return
    grants = data.get("agent_identity", {}).get("candidate_grants", [])
    require(isinstance(source_changes, dict) and grants
            and all(source_changes.get(grant.get("id")) in ("Create", "Modify", "NoChange") for grant in grants),
            "native-foundry-reviewed-network-grants-required")
    bound = document["deployment"].get("foundry_identity_continuation")
    if bound:
        dependent = data.get("identity_dependent_grants", [])
        prior = {row["resource_id"]: row for row in data["phases"][0]["changes"]}
        require(isinstance(dependent, list) and dependent
                and any(foundry_grant_scope(row["id"]) == bound["proof"]["resource_group"]
                        and str(row["intent"].get("properties", {}).get("roleDefinitionId", "")).lower().endswith(
                            "/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd") for row in dependent),
                "native-foundry-dependent-cognitive-grant-required")
        for row in dependent:
            identifier, intent = row.get("id", ""), row.get("intent", {})
            change = prior.get(identifier, {})
            properties = intent.get("properties", {})
            require(NESTED_ID.fullmatch(identifier) and guid(identifier.rsplit("/", 1)[-1])
                    and source_changes.get(identifier) in ("Create", "Modify", "NoChange")
                    and str(properties.get("principalId", "")).lower() == bound["proof"]["identity"]["principal_id"]
                    and properties.get("principalType") == "ServicePrincipal"
                    and (digest(intent) == change.get("after_hash") or change.get("change_type") == "NoChange"
                         and digest(intent) == change.get("before_hash")),
                    "native-foundry-literal-dependent-grants-required")


def validate_foundry_agent_binding(document):
    data = document["deployment"]["foundry_lifecycle"]
    agent = data.get("agent_identity", {})
    account = agent.get("account_intent")
    account_change = next(row for row in data["phases"][1]["changes"]
                          if row["resource_id"] == data["account_resource_id"])
    require(isinstance(account, dict) and digest(account) == account_change["after_hash"]
            and foundry_selected_uami(account) == agent.get("resource_id")
            and arm_scope(agent["resource_id"]) in {scope.lower() for scope in document["locks"]["scopes"]}
            and agent.get("binding_hash") == digest(data["agent_identity_binding"]),
            "native-foundry-agent-binding-mismatch")
    prior = {row["resource_id"]: row for row in data["phases"][0]["changes"]}
    require(agent.get("existence") == "existing",
            "native-foundry-agent-producer-required")
    observed = agent.get("existing_identity")
    require((agent["existence"] == "planned-create" and observed is None)
            or (isinstance(observed, dict) and all(foundry_identity_guid(observed.get(key)) for key in (
                "principal_id", "client_id", "tenant_id"))
                and observed["principal_id"] != observed["client_id"]
                and observed["tenant_id"] == document["target"]["tenant_id"].lower()),
            "native-foundry-agent-identity-invalid")
    grants = agent.get("candidate_grants")
    require(isinstance(grants, list) and 0 < len(grants) <= 20
            and len({row.get("id") for row in grants}) == len(grants),
            "native-foundry-reviewed-network-grants-required")
    verify_foundry_source_grants(document, data["phases"][0].get("source_changes"))
    for grant in grants:
        identifier, intent = grant.get("id", ""), grant.get("intent")
        change = prior.get(identifier)
        properties = intent.get("properties", {}) if isinstance(intent, dict) else {}
        require(NESTED_ID.fullmatch(identifier) and identifier == identifier.lower()
                and resource_type_from_id(identifier) == "microsoft.authorization/roleassignments"
                and guid(identifier.rsplit("/", 1)[-1])
                and foundry_grant_scope(identifier) == data["network_scopes"][0]
                and str(properties.get("scope", data["network_scopes"][0])).lower() == data["network_scopes"][0]
                and properties.get("roleDefinitionId", "").lower() == data["role_definition_id"].lower()
                and properties.get("principalType") == "ServicePrincipal"
                and foundry_identity_guid(properties.get("principalId"))
                and properties["principalId"].lower() == observed["principal_id"]
                and properties.get("principalId") != "00000000-0000-0000-0000-000000000000"
                and all(properties.get(key) in (None, "") for key in (
                    "condition", "conditionVersion", "delegatedManagedIdentityResourceId"))
                and change and (digest(intent) == change.get("after_hash")
                                or change["change_type"] == "NoChange"
                                and digest(intent) == grant.get("observed_hash")),
                "native-foundry-reviewed-network-grants-required")


def freeze_foundry_agent_binding(cloud, document, payloads):
    data = document["deployment"]["foundry_lifecycle"]
    if not data["agent_identity_binding"]:
        return
    account = payloads[1].get(data["account_resource_id"])
    require(isinstance(account, dict), "native-foundry-source-account-payload-required")
    identifier = foundry_selected_uami(account)
    require(arm_scope(identifier) in {scope.lower() for scope in document["locks"]["scopes"]},
            "native-foundry-agent-identity-outside-scope")
    status, _, identity = cloud.arm("GET", identifier, FOUNDRY_MI_API, allowed=(200, 404))
    observed = foundry_uami_metadata(document, identity) if status == 200 else None
    if status == 200:
        require(str(identity.get("id", "")).lower() == identifier, "native-foundry-agent-identity-mismatch")
    agent = {"resource_id": identifier, "account_intent": account,
             "binding_hash": digest(data["agent_identity_binding"]),
             "existence": "existing" if status == 200 else "planned-create",
             "existing_identity": observed, "candidate_grants": []}
    prior = {row["resource_id"]: row for row in data["phases"][0]["changes"]}
    source_changes = data["phases"][0].get("source_changes", {})
    for resource in sorted(prior):
        if (source_changes.get(resource) not in ("Create", "Modify", "NoChange")
                or resource_type_from_id(resource) != "microsoft.authorization/roleassignments"
                or foundry_grant_scope(resource) != data["network_scopes"][0]):
            continue
        intent, observed_hash = payloads[0].get(resource), None
        if intent is None:
            require(prior[resource]["change_type"] == "NoChange",
                    "native-foundry-grant-payload-required")
            code, _, intent = cloud.arm("GET", resource, "2022-04-01", allowed=(200, 404))
            require(code == 200 and str(intent.get("id", "")).lower() == resource,
                    "native-foundry-existing-grant-unverified")
            observed_hash = digest(intent)
        properties = intent.get("properties", {})
        if (properties.get("roleDefinitionId", "").lower() != data["role_definition_id"].lower()
                or properties.get("principalType") != "ServicePrincipal"):
            continue
        principal = properties.get("principalId")
        if observed and guid(principal) and principal.lower() != observed["principal_id"]:
            continue
        agent["candidate_grants"].append({"id": resource, "intent": intent, "observed_hash": observed_hash})
    data["agent_identity"] = agent
    validate_foundry_agent_binding(document)


def freeze_foundry_lifecycle(cloud, document, source_root):
    data = document["deployment"].get("foundry_lifecycle")
    if data is None:
        return
    validate_foundry_lifecycle(document)
    cumulative, preceding, payloads = [], {}, []
    for phase in data["phases"]:
        cumulative.extend(phase["step_ids"])
        payload = combined_plan_payload(cloud, document, source_root, cumulative)
        captured, source_changes = {}, {}
        changes = evaluate_what_if(cloud, document, {"id": phase["id"], "scope": "subscription"}, payload,
                                  resource_payloads=captured, source_changes=source_changes)
        payloads.append(captured)
        verify_bootstrap_preservation(document, changes)
        require(all(RG_ID.fullmatch(row["resource_id"]) or NESTED_ID.fullmatch(row["resource_id"])
                    for row in changes), "native-foundry-unresolved-preview-resource")
        require(all(arm_scope(row["resource_id"]) in {scope.lower() for scope in document["locks"]["scopes"]}
                    for row in changes), "native-foundry-preview-outside-scope")
        phase["changes"] = changes
        phase["source_changes"] = source_changes
        if phase["id"] == "foundry-account-phase":
            added = [row["resource_id"] for row in changes if row["change_type"] == "Create"
                     and row["resource_id"] not in preceding
                     and resource_type_from_id(row["resource_id"]) == "microsoft.cognitiveservices/accounts"]
            require(len(added) == 1, "native-foundry-exact-created-account-required")
            identifier = added[0]
            status, _, _ = cloud.arm("GET", identifier, FOUNDRY_API, allowed=(200, 404))
            require(status == 404, "native-foundry-first-run-account-already-exists")
            data["account_resource_id"] = identifier
        preceding = {row["resource_id"]: row for row in changes}
    require(data["phases"][-1]["changes"] == document["deployment"]["changes"],
            "native-foundry-full-preview-changed")
    bound = document["deployment"].get("foundry_identity_continuation")
    if bound:
        dependent = []
        for row in data["phases"][0]["changes"]:
            identifier = row["resource_id"]
            if (resource_type_from_id(identifier) != "microsoft.authorization/roleassignments"
                    or data["phases"][0]["source_changes"].get(identifier) not in ("Create", "Modify", "NoChange")):
                continue
            body = payloads[0].get(identifier)
            if body is None and row["change_type"] == "NoChange":
                status, _, body = cloud.arm("GET", identifier, "2022-04-01", allowed=(200, 404))
                require(status == 200 and str(body.get("id", "")).lower() == identifier,
                        "native-foundry-dependent-grant-observation-required")
            if isinstance(body, dict) and str(body.get("properties", {}).get("principalId", "")).lower() == bound["proof"]["identity"]["principal_id"]:
                dependent.append({"id": identifier, "intent": body})
        data["identity_dependent_grants"] = dependent
    freeze_foundry_agent_binding(cloud, document, payloads)


def foundry_readiness_observations(document, receipt):
    observed = {}
    agent = receipt.get("foundry_agent_readiness")
    if agent is not None:
        verify_foundry_agent_receipt(document, receipt)
        observed[agent["resource_id"]] = {
            "body_hash": agent["identity_body_hash"], "api_version": FOUNDRY_MI_API}
        observed.update({row["id"]: {"body_hash": row["body_hash"], "api_version": row["api_version"]}
                         for row in agent["network_resources"]})
        observed.update({row["id"]: {"body_hash": row["body_hash"], "api_version": "2022-04-01"}
                         for row in agent["grants"]})
    proof = receipt.get("foundry_readiness")
    if proof is not None:
        verify_foundry_readiness_receipt(document, receipt)
        observed[proof["account_resource_id"]] = {
            "body_hash": proof["account_body_hash"], "api_version": FOUNDRY_API}
        if "capability_host" in proof:
            host = proof["capability_host"]
            observed[host["id"].lower()] = {"body_hash": host["body_hash"], "api_version": FOUNDRY_API}
    return observed


def verify_foundry_observation_context(cloud, document, receipt, observations):
    phases = document["deployment"]["foundry_lifecycle"]["phases"]
    completed = receipt.get("foundry_phases", [])
    retained = receipt.get("foundry_phase_observations", [])
    require(receipt.get("run_id") == document["run_id"]
            and receipt.get("manifest_hash") == document["manifest_hash"]
            and receipt.get("status") == "running" and not receipt.get("pending_deployment")
            and not receipt.get("pending_foundry_gate")
            and len(completed) <= 2 and len(retained) == len(completed)
            and completed == [{"id": phase["id"], "status": "succeeded", "changes_hash": digest(phase["changes"])}
                              for phase in phases[:len(completed)]]
            and (retained[-1]["resources"] if retained else receipt.get("foundry_initial_observations")) == observations,
            "native-foundry-phase-observation-context-required")
    verify_foundry_observation_history(document, receipt)
    for identifier, proof in observations.items():
        status, _, body = cloud.arm("GET", identifier, proof["api_version"], allowed=(200, 404))
        require(status == 200 and str(body.get("id", "")).lower() == identifier
                and digest(body) == proof["body_hash"], "native-foundry-phase-instance-changed")


def verify_foundry_observation_history(document, receipt):
    phases = document["deployment"]["foundry_lifecycle"]["phases"]
    retained = receipt.get("foundry_phase_observations", [])
    require(isinstance(retained, list) and len(retained) <= len(phases),
            "native-foundry-phase-observations-incomplete")
    initial = document["deployment"].get("bootstrap_foundation", {}).get("resources", {})
    previous, preceding = receipt.get("foundry_initial_observations"), {}
    verify_foundry_observation_rows(document, previous)
    before = {row["resource_id"]: row for row in phases[0]["changes"]}
    require(all((key not in before or before[key]["change_type"] != "Create")
                and (key not in before or before[key].get("before_hash") is None
                     or value["body_hash"] == before[key]["before_hash"])
                and (key not in initial or value["body_hash"] == initial[key]["body_hash"])
                for key, value in previous.items()), "native-foundry-initial-instance-changed")
    for index, record in enumerate(retained):
        phase = phases[index]
        readiness = foundry_readiness_observations(document, receipt) if index else {}
        required = {row["resource_id"] for row in phase["changes"]} | set(previous) | set(readiness)
        require(record.get("id") == phase["id"] and isinstance(record.get("resources"), dict)
                and set(record["resources"]) == required and hash_value(record.get("closure_hash"))
                and isinstance(record.get("executed_changes"), list),
                "native-foundry-phase-observations-incomplete")
        verify_foundry_observation_rows(document, record["resources"])
        verify_foundry_phase_changes(record["executed_changes"], phase["changes"], preceding, previous)
        written = {row["resource_id"] for row in record["executed_changes"]
                   if row["change_type"] in ("Create", "Modify")}
        require(all(key in written or record["resources"].get(key) == value for key, value in previous.items())
                and all(key in written or value["body_hash"] == previous.get(key, initial[key])["body_hash"]
                        for key, value in record["resources"].items() if key in initial),
                "native-foundry-phase-instance-changed")
        require(all(record["resources"][key]["body_hash"] == value["body_hash"]
                    for key, value in readiness.items()), "native-foundry-readiness-instance-changed")
        previous = record["resources"]
        preceding = {row["resource_id"]: row for row in phase["changes"]}


def foundry_owned_phase_write(document, receipt, identifier):
    foundation = document["deployment"].get("bootstrap_foundation", {})
    resources = foundation.get("resources", {})
    if resources.get(identifier, {}).get("disposition") != "owned" or any(
            row.get("disposition") == "preserve" and (identifier == key or identifier.startswith(key + "/"))
            for key, row in resources.items()):
        return False
    return any(row["resource_id"] == identifier and row["change_type"] in ("Create", "Modify")
               for phase in receipt.get("foundry_phase_observations", [])
               for row in phase.get("executed_changes", []))

def verify_foundry_observation_rows(document, observations):
    require(isinstance(observations, dict) and all(
        isinstance(key, str) and key == key.lower()
        and arm_scope(key) in {scope.lower() for scope in document["locks"]["scopes"]}
        and isinstance(row, dict) and hash_value(row.get("body_hash"))
        and re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}(?:-preview)?", str(row.get("api_version", "")))
        for key, row in observations.items()), "native-foundry-instance-evidence-required")

def foundry_inventory_observations(document, closure, bodies=None):
    require(isinstance(closure, dict) and isinstance(closure.get("groups"), dict)
            and isinstance(closure.get("resources"), dict)
            and isinstance(closure.get("providers"), dict) and isinstance(closure.get("collections"), dict),
            "native-foundry-inventory-evidence-required")
    groups, resources = closure["groups"], closure["resources"]
    require(not set(groups) & set(resources)
            and set(groups) <= {scope.lower() for scope in document["locks"]["scopes"]},
            "native-foundry-inventory-scope-changed")
    observed = {key: {"body_hash": row.get("body_hash"),
                     "api_version": RG_API if key in groups else row.get("api_version")}
                for key, row in {**groups, **resources}.items()}
    verify_foundry_observation_rows(document, observed)
    if bodies is not None:
        require(set(bodies) == set(observed)
                and all(str(bodies[key].get("id", "")).lower() == key
                        and digest(bodies[key]) == row["body_hash"] for key, row in observed.items()),
                "native-foundry-inventory-body-mismatch")
    return observed

def verify_foundry_live_inventory(cloud, locks, document, observations, *, closure_hash=None):
    locks.assert_held()
    scopes = []
    for scope in document["locks"]["scopes"]:
        status, _, body = cloud.arm("GET", scope, RG_API, allowed=(200, 404))
        proof = observations.get(scope.lower())
        require((proof is None and status == 404) or
                (proof is not None and status == 200 and digest(body) == proof["body_hash"]),
                "native-foundry-phase-instance-changed")
        if proof is not None:
            scopes.append(scope)
    closure, bodies = collect_resource_closure(cloud, scopes,
                                               bootstrap_resource_versions(document))
    current = foundry_inventory_observations(document, closure, bodies)
    require(set(current) == set(observations)
            and all(current[key]["body_hash"] == row["body_hash"] for key, row in observations.items())
            and (closure_hash is None or digest(closure) == closure_hash),
            "native-foundry-phase-instance-changed")
    if set(closure["groups"]) == {scope.lower() for scope in document["locks"]["scopes"]}:
        verify_bootstrap_final_closure(document, closure, bodies)
    return closure, bodies

def observe_foundry_phase(cloud, document, phase, execution, previous, receipt):
    readiness = foundry_readiness_observations(document, receipt)
    identifiers = {row["resource_id"] for row in phase["changes"]} | set(previous) | set(readiness)
    closure, bodies = collect_resource_closure(cloud, document["locks"]["scopes"],
                                               bootstrap_resource_versions(document))
    snapshot = foundry_inventory_observations(document, closure, bodies)
    require(identifiers == set(snapshot), "native-foundry-phase-observation-incomplete")
    verify_bootstrap_final_closure(document, closure, bodies)
    written = {row["resource_id"] for row in execution if row["change_type"] in ("Create", "Modify")}
    initial = document["deployment"].get("bootstrap_foundation", {}).get("resources", {})
    unchanged = {row["resource_id"]: {"body_hash": row.get("before_hash") or row.get("after_hash")}
                 for row in execution if row["change_type"] == "NoChange"}
    expected = {**unchanged, **initial, **readiness, **previous}
    observed = {}
    for identifier in sorted(identifiers):
        current_hash = digest(bodies[identifier])
        # Cumulative preview membership never permits rebasing a resource this phase did not write.
        require(identifier in written or current_hash == expected.get(identifier, {}).get("body_hash"),
                "native-foundry-phase-instance-changed")
        require(identifier not in readiness or current_hash == readiness[identifier]["body_hash"],
                "native-foundry-readiness-instance-changed")
        observed[identifier] = {
            "body_hash": current_hash,
            "api_version": RG_API if identifier in closure["groups"] else closure["resources"][identifier]["api_version"],
        }
    return {"id": phase["id"], "resources": observed, "executed_changes": copy.deepcopy(execution),
            "closure_hash": digest(closure)}


def verify_foundry_phase_changes(current, expected, preceding, observations=None):
    observations = observations or {}
    wanted = {row["resource_id"]: row for row in expected}
    observed = {row["resource_id"]: row for row in current}
    require(len(observed) == len(current) and set(observed) <= set(wanted), "foundry-phase-what-if-changed")
    for identifier, row in observed.items():
        before = preceding.get(identifier)
        target = wanted[identifier]
        if before is None:
            require(row == target, "foundry-phase-what-if-changed")
        elif row["change_type"] == "NoChange" and identifier in observations:
            observed_hash = observations[identifier]["body_hash"]
            require(target.get("after_hash") == before.get("after_hash")
                    and row.get("before_hash") in (None, observed_hash)
                    and row.get("after_hash") in (None, observed_hash), "foundry-phase-what-if-changed")
        else:
            require(row["change_type"] in ("Modify", "NoChange")
                    and (row["change_type"] != "Modify" or target["change_type"] != "NoChange")
                    and hash_value(observations.get(identifier, {}).get("body_hash", before.get("after_hash")))
                    and row.get("before_hash") == observations.get(identifier, {}).get("body_hash", before["after_hash"])
                    and row.get("after_hash") == target.get("after_hash"),
                    "foundry-phase-what-if-changed")
    required = {identifier for identifier, row in wanted.items()
                if row["change_type"] != "NoChange" and
                (identifier not in preceding or preceding[identifier].get("after_hash") != row.get("after_hash"))}
    require(required <= set(observed), "foundry-phase-what-if-incomplete")


def wait_foundry_resource(cloud, locks, identifier, ready, sleep, *, api_version=FOUNDRY_API,
                         attempts=180, read=None, document=None):
    for attempt in range(attempts):
        locks.assert_held()
        if document is not None:
            locks.authorize(document)
        status, _, body = (read() if read else cloud.arm("GET", identifier, api_version, allowed=(200, 404)))
        if document is not None:
            locks.authorize(document)
        if status == 200:
            require(str(body.get("id", "")).lower() == identifier.lower(), "foundry-resource-identity-mismatch")
            state = body.get("properties", {}).get("provisioningState")
            require(state not in ("Failed", "Canceled", "Cancelled"), "foundry-resource-provisioning-failed")
            if ready(body):
                return body
            require(state in (None, "Succeeded", "Accepted", "Running", "Creating", "Updating"),
                    "foundry-resource-state-unverified")
        if attempt + 1 < attempts:
            sleep(5)
    raise Blocked("foundry-readiness-timeout")


def foundry_identity_guid(value):
    return guid(value) and value != "00000000-0000-0000-0000-000000000000"


def foundry_uami_metadata(document, body):
    properties = body.get("properties", {})
    require(isinstance(properties, dict), "native-foundry-agent-identifiers-invalid")
    require(all(foundry_identity_guid(properties.get(key)) for key in ("principalId", "clientId", "tenantId"))
            and properties["principalId"].lower() != properties["clientId"].lower(),
            "native-foundry-agent-identifiers-invalid")
    require(properties["tenantId"].lower() == document["target"]["tenant_id"].lower(),
            "native-foundry-agent-tenant-mismatch")
    state = properties.get("provisioningState")
    require(state in (None, "Succeeded"), "native-foundry-agent-provisioning-unverified")
    return {"principal_id": properties["principalId"].lower(), "client_id": properties["clientId"].lower(),
            "tenant_id": properties["tenantId"].lower(), "provisioning_state": state}


def foundry_agent_readiness(cloud, locks, document, receipt, persist, observations, sleep):
    data = document["deployment"]["foundry_lifecycle"]
    binding = data["agent_identity_binding"]
    if binding is None:
        return
    receipt["pending_foundry_gate"] = "agent-before-account"
    persist()
    agent = data["agent_identity"]
    producer = next(step for step in document["deployment"]["steps"] if step["id"] == binding["producer_step"])
    endpoint = deployment_endpoint(document, producer)
    result = wait_foundry_resource(cloud, locks, endpoint.removeprefix(ARM),
        lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded", sleep, attempts=1,
        read=lambda: cloud.request("GET", endpoint + "?api-version=2022-09-01", ARM), document=document)
    output = result.get("properties", {}).get("outputs", {}).get("foundationOutputs", {}).get("value", {})
    identifier = agent["resource_id"]
    require(str(output.get("miProjectName", "")).lower() == identifier.rsplit("/", 1)[-1]
            and str(output.get("projectResourceGroupName", "")).lower() == arm_scope(identifier).split("/")[4],
            "native-foundry-agent-producer-output-mismatch")
    def materialized(body):
        properties = body.get("properties", {})
        if properties.get("tenantId"):
            require(str(properties["tenantId"]).lower() == document["target"]["tenant_id"].lower(),
                    "native-foundry-agent-tenant-mismatch")
        return (all(foundry_identity_guid(properties.get(key)) for key in ("principalId", "clientId", "tenantId"))
                and properties.get("provisioningState") in (None, "Succeeded"))
    identity = wait_foundry_resource(cloud, locks, identifier, materialized, sleep,
                                    api_version=FOUNDRY_MI_API, document=document)
    metadata = foundry_uami_metadata(document, identity)
    require(identifier in observations and digest(identity) == observations[identifier]["body_hash"],
            "native-foundry-agent-identity-changed")
    original = agent["existing_identity"]
    require(original is None or all(metadata[key] == original[key] for key in ("principal_id", "client_id", "tenant_id")),
            "native-foundry-agent-principal-changed")
    foundation = document["deployment"].get("bootstrap_foundation", {})
    original_resource = (foundation.get("resources", {}).get(identifier, {})
                         if foundation.get("contract") == EXACT_BOOTSTRAP_CONTRACT else {})
    if original_resource.get("disposition") == "preserve":
        require(digest(identity) == original_resource["body_hash"], "native-foundry-preserved-identity-changed")
    else:
        verify_ownership(identity, {**{key: document["target"][key] for key in ("factory_id", "scaleset_id")},
                                    "project_id": document["target"]["project_ids"][0]})
    proof = {"contract": binding["contract"], "resource_id": identifier, **metadata,
             "identity_body_hash": digest(identity), "producer_deployment_id": endpoint.removeprefix(ARM),
             "producer_body_hash": digest(result), "binding_hash": digest(binding),
             "completed_gates": ["agent-uami-identity"], "grants": [], "network_resources": [],
             "effective_permissions_proven": False, "status": "observing"}
    receipt["foundry_agent_readiness"] = proof
    persist()
    for scope in data["network_scopes"]:
        api = observations.get(scope, {}).get("api_version") or bootstrap_resource_versions(document).get(
            scope, "2023-11-01")
        network = wait_foundry_resource(cloud, locks, scope,
            lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded",
            sleep, api_version=api, document=document)
        require(scope != data["network_scopes"][0]
                or str(network.get("location", "")).lower() == document["target"]["region"].lower(),
                "native-foundry-agent-network-region-mismatch")
        expected_hash = observations.get(scope, {}).get("body_hash")
        require(not expected_hash or digest(network) == expected_hash, "native-foundry-agent-network-instance-changed")
        proof["network_resources"].append({"id": scope, "body_hash": digest(network), "api_version": api,
                                           "provisioning_state": "Succeeded"})
    for candidate in agent["candidate_grants"]:
        expected_principal = candidate["intent"].get("properties", {}).get("principalId")
        if guid(expected_principal) and expected_principal.lower() != metadata["principal_id"]:
            continue
        grant = wait_foundry_resource(cloud, locks, candidate["id"], lambda body: True, sleep,
                                     api_version="2022-04-01", document=document)
        expected_hash = observations.get(candidate["id"], {}).get("body_hash") or candidate["observed_hash"]
        require(expected_hash and digest(grant) == expected_hash, "native-foundry-agent-grant-instance-changed")
        properties = grant.get("properties", {})
        if not guid(expected_principal) and str(properties.get("principalId", "")).lower() != metadata["principal_id"]:
            continue
        require(str(properties.get("principalId", "")).lower() == metadata["principal_id"]
                and str(properties.get("roleDefinitionId", "")).lower() == data["role_definition_id"].lower()
                and properties.get("principalType") == "ServicePrincipal"
                and all(properties.get(key) in (None, "") for key in (
                    "condition", "conditionVersion", "delegatedManagedIdentityResourceId"))
                and str(properties.get("scope", data["network_scopes"][0])).lower() == data["network_scopes"][0],
                "native-foundry-agent-network-grant-conflict")
        proof["grants"].append({"id": candidate["id"], "scope": data["network_scopes"][0],
                                "principal_id": metadata["principal_id"], "role_definition_id": data["role_definition_id"],
                                "body_hash": digest(grant)})
    require(len(proof["grants"]) == 1, "native-foundry-agent-network-grant-required")
    proof["completed_gates"].append("agent-network-role-observation")
    proof["status"] = "observed"
    receipt.pop("pending_foundry_gate", None)
    persist()


def verify_foundry_agent_receipt(document, receipt):
    data = document["deployment"]["foundry_lifecycle"]
    binding = data["agent_identity_binding"]
    if binding is None:
        require("foundry_agent_readiness" not in receipt, "native-foundry-unexpected-agent-proof")
        return
    proof = receipt.get("foundry_agent_readiness", {})
    candidates = {row["id"] for row in data["agent_identity"]["candidate_grants"]}
    grants = proof.get("grants")
    producer = next(step for step in document["deployment"]["steps"] if step["id"] == binding["producer_step"])
    require(proof.get("contract") == binding["contract"] and proof.get("status") == "observed"
            and proof.get("resource_id") == data["agent_identity"]["resource_id"]
            and proof.get("tenant_id") == document["target"]["tenant_id"].lower()
            and foundry_identity_guid(proof.get("principal_id")) and foundry_identity_guid(proof.get("client_id"))
            and proof["principal_id"] != proof["client_id"]
            and proof.get("provisioning_state") in (None, "Succeeded")
            and proof.get("binding_hash") == digest(binding)
            and hash_value(proof.get("identity_body_hash")) and hash_value(proof.get("producer_body_hash"))
            and proof.get("producer_deployment_id") == deployment_endpoint(document, producer).removeprefix(ARM)
            and proof.get("completed_gates") == binding["required_gates"]
            and proof.get("effective_permissions_proven") is False
            and isinstance(grants, list) and len(grants) == 1,
            "native-foundry-agent-receipt-incomplete")
    original = data["agent_identity"]["existing_identity"]
    require(original is None or all(proof[key] == original[key] for key in ("principal_id", "client_id", "tenant_id")),
            "native-foundry-agent-receipt-incomplete")
    require(all(row.get("id") in candidates and row.get("scope") == data["network_scopes"][0]
                and row.get("principal_id") == proof["principal_id"]
                and row.get("role_definition_id") == data["role_definition_id"]
                and hash_value(row.get("body_hash")) for row in grants), "native-foundry-agent-grant-receipt-incomplete")
    network = proof.get("network_resources", [])
    require([row.get("id") for row in network] == data["network_scopes"]
            and all(row.get("provisioning_state") == "Succeeded" and hash_value(row.get("body_hash"))
                    and re.fullmatch(r"20\d{2}-\d{2}-\d{2}(?:-preview)?", str(row.get("api_version", "")))
                    for row in network), "native-foundry-agent-network-receipt-incomplete")


def verify_foundry_agent_current(cloud, locks, document, receipt, sleep):
    verify_foundry_agent_receipt(document, receipt)
    if not document["deployment"]["foundry_lifecycle"]["agent_identity_binding"]:
        return
    proof = receipt["foundry_agent_readiness"]
    identity = wait_foundry_resource(cloud, locks, proof["resource_id"], lambda body: True, sleep,
                                    api_version=FOUNDRY_MI_API, attempts=1, document=document)
    metadata = foundry_uami_metadata(document, identity)
    require(all(metadata[key] == proof[key] for key in ("principal_id", "client_id", "tenant_id"))
            and digest(identity) == proof["identity_body_hash"], "native-foundry-agent-identity-changed")
    for grant in proof["grants"]:
        body = wait_foundry_resource(cloud, locks, grant["id"], lambda body: True, sleep,
                                    api_version="2022-04-01", attempts=1, document=document)
        require(digest(body) == grant["body_hash"], "native-foundry-agent-grant-instance-changed")


def verify_foundry_account_agent(document, account, receipt):
    data = document["deployment"]["foundry_lifecycle"]
    injections = account.get("properties", {}).get("networkInjections") or []
    if not data["agent_identity_binding"]:
        require(not injections and str(account.get("identity", {}).get("type", "")).lower() == "systemassigned",
                "foundry-account-network-injection-mismatch")
        return
    agent = receipt["foundry_agent_readiness"]
    require(foundry_selected_uami(account) == agent["resource_id"], "native-foundry-account-agent-identity-mismatch")
    identity = account["identity"]
    attached = next(iter(identity["userAssignedIdentities"].values()))
    require(isinstance(attached, dict) and str(attached.get("principalId", "")).lower() == agent["principal_id"]
            and str(attached.get("clientId", "")).lower() == agent["client_id"]
            and str(identity.get("principalId", "")).lower() != agent["principal_id"],
            "native-foundry-account-agent-identity-mismatch")
    require(isinstance(injections, list) and len(injections) == 1 and isinstance(injections[0], dict)
            and injections[0].get("scenario") == "agent"
            and str(injections[0].get("subnetArmId", "")).lower() == data["network_scopes"][-1]
            and injections[0].get("useMicrosoftManagedNetwork") is False,
            "foundry-account-network-injection-mismatch")


def foundry_readiness(cloud, locks, document, receipt, persist, account_result, sleep):
    data = document["deployment"]["foundry_lifecycle"]
    identifier = data["account_resource_id"]
    outputs = account_result.get("properties", {}).get("outputs", {})
    require(outputs.get("aiFoundryV2ResourceId", {}).get("value", "").lower() == identifier
            and outputs.get("aiFoundryV2Name", {}).get("value", "").lower() == identifier.rsplit("/", 1)[-1],
            "foundry-account-outputs-mismatch")
    account = wait_foundry_resource(cloud, locks, identifier,
        lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded"
        and foundry_identity_guid(body.get("identity", {}).get("principalId")), sleep, document=document)
    require(str(account.get("identity", {}).get("tenantId", "")).lower()
            == document["target"]["tenant_id"].lower(), "foundry-account-tenant-mismatch")
    owner = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    owner["project_id"] = document["target"]["project_ids"][0]
    verify_ownership(account, owner)
    require(account.get("kind") == "AIServices"
            and account.get("location", "").lower() == document["target"]["region"].lower(),
            "foundry-account-topology-mismatch")
    injections = account.get("properties", {}).get("networkInjections") or []
    if data["network_scopes"]:
        verify_foundry_agent_current(cloud, locks, document, receipt, sleep)
        agent = receipt["foundry_agent_readiness"]
    verify_foundry_account_agent(document, account, receipt)
    principal = account["identity"]["principalId"].lower()
    proof = {"contract": FOUNDRY_CONTRACT, "account_resource_id": identifier,
             "principal_id": principal, "account_body_hash": digest(account),
             "principal_binding_hash": digest(data["principal_binding"]),
             "completed_gates": ["account-identity"]}
    receipt["foundry_readiness"] = proof
    persist()
    if data["require_capability_host"]:
        host = identifier + "/capabilityHosts/" + identifier.rsplit("/", 1)[-1] + "@aml_aiagentservice"
        ready = wait_foundry_resource(cloud, locks, host,
            lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded", sleep, document=document)
        proof["capability_host"] = {
            "id": host, "body_hash": digest(ready), "status": "Succeeded",
            "configured_identity_id": agent["resource_id"], "configured_principal_id": agent["principal_id"],
            "agent_proof_hash": digest(agent),
            "evidence": "account-provider-readiness-with-source-selected-uami",
            "general_effective_permissions_proven": False}
        proof["completed_gates"].append("configured-agent-network-ready")
    current = wait_foundry_resource(cloud, locks, identifier,
        lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded", sleep, document=document)
    require(str(current.get("identity", {}).get("principalId", "")).lower() == principal,
            "foundry-account-principal-changed")
    require(str(current.get("identity", {}).get("tenantId", "")).lower()
            == document["target"]["tenant_id"].lower(), "foundry-account-tenant-mismatch")
    if data["agent_identity_binding"]:
        require(current.get("identity") == account.get("identity")
                and current.get("properties", {}).get("networkInjections") == injections,
                "native-foundry-account-agent-identity-changed")
        verify_foundry_agent_current(cloud, locks, document, receipt, sleep)
    verify_foundry_account_agent(document, current, receipt)
    proof["status"] = "provider-ready" if data["require_capability_host"] else "succeeded"
    persist()


def verify_foundry_live_readiness(cloud, locks, document, receipt, sleep):
    verify_foundry_readiness_receipt(document, receipt)
    verify_foundry_agent_current(cloud, locks, document, receipt, sleep)
    proof = receipt["foundry_readiness"]
    account = wait_foundry_resource(cloud, locks, proof["account_resource_id"],
        lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded",
        sleep, attempts=1, document=document)
    require(digest(account) == proof["account_body_hash"], "native-foundry-account-instance-changed")
    verify_foundry_account_agent(document, account, receipt)
    if "capability_host" in proof:
        host = proof["capability_host"]
        body = wait_foundry_resource(cloud, locks, host["id"],
            lambda value: value.get("properties", {}).get("provisioningState") == "Succeeded",
            sleep, attempts=1, document=document)
        require(digest(body) == host["body_hash"], "native-foundry-capability-host-changed")


def run_foundry_phases(cloud, locks, document, source_root, receipt, persist, sleep):
    data = document["deployment"]["foundry_lifecycle"]
    require("account_resource_id" in data and all(isinstance(phase.get("changes"), list)
            for phase in data["phases"]), "native-foundry-frozen-phases-required")
    preceding, cumulative, observations, payloads, provenance = {}, [], receipt.get("foundry_initial_observations"), [], []
    verify_foundry_observation_rows(document, observations)
    verify_foundry_identity_current(cloud, locks, document)
    if "foundry_identity_continuation" in document["deployment"]:
        receipt["foundry_identity_continuation"] = copy.deepcopy(document["deployment"]["foundry_identity_continuation"])
    # Before any mutation, every cumulative preview must still equal its reviewed bytes.
    for phase in data["phases"]:
        cumulative.extend(phase["step_ids"])
        locks.assert_held()
        captured, source_changes = {}, {}
        observed = evaluate_what_if(cloud, document, {"id": phase["id"], "scope": "subscription"},
            combined_plan_payload(cloud, document, source_root, cumulative), sleep,
            resource_payloads=captured, source_changes=source_changes)
        require(observed == phase["changes"], "native-foundry-preview-changed")
        verify_bootstrap_preservation(document, observed)
        payloads.append(captured)
        provenance.append(source_changes)
    if data["agent_identity_binding"]:
        rebound = copy.deepcopy(document)
        rebound["deployment"]["foundry_lifecycle"]["phases"][0]["source_changes"] = provenance[0]
        freeze_foundry_agent_binding(cloud, rebound, payloads)
        require(rebound["deployment"]["foundry_lifecycle"]["agent_identity"] == data["agent_identity"],
                "native-foundry-agent-binding-changed")
    receipt["foundry_phases"] = []
    receipt["foundry_phase_observations"] = []
    for phase in data["phases"]:
        locks.assert_held()
        locks.authorize(document)
        verify_foundry_identity_current(cloud, locks, document)
        if phase["id"] == "foundry-project-phase":
            verify_foundry_provider_readiness_receipt(document, receipt)
            verify_foundry_agent_current(cloud, locks, document, receipt, sleep)
        root_step = {"id": phase["id"], "scope": "subscription"}
        payload = combined_plan_payload(cloud, document, source_root, phase["step_ids"])
        for identifier, proof in observations.items():
            status, _, body = cloud.arm("GET", identifier, proof["api_version"], allowed=(200, 404))
            require(status == 200 and digest(body) == proof["body_hash"],
                    "native-foundry-phase-instance-changed")
        source_changes = {}
        current = evaluate_what_if(cloud, document, root_step, payload, sleep,
                                   unchanged_resources=observations, source_changes=source_changes,
                                   phase_receipt=receipt)
        verify_bootstrap_preservation(document, current)
        verify_foundry_phase_changes(current, phase["changes"], preceding, observations)
        if phase["id"] == "foundry-prerequisites":
            verify_foundry_source_grants(document, source_changes)
        if phase["id"] == "foundry-project-phase":
            verify_foundry_readiness_receipt(document, receipt)
            if data["require_capability_host"]:
                host = receipt["foundry_readiness"]["capability_host"]
                current_host = wait_foundry_resource(cloud, locks, host["id"],
                    lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded",
                    sleep, attempts=1, document=document)
                require(digest(current_host) == host["body_hash"], "native-foundry-capability-host-changed")
        if phase["id"] == "foundry-account-phase":
            foundry_agent_readiness(cloud, locks, document, receipt, persist, observations, sleep)
            verify_foundry_agent_current(cloud, locks, document, receipt, sleep)
            status, _, _ = cloud.arm("GET", data["account_resource_id"], FOUNDRY_API, allowed=(200, 404))
            require(status == 404, "native-foundry-first-run-account-already-exists")
        locks.assert_held()
        locks.authorize(document)
        endpoint = deployment_endpoint(document, root_step)
        receipt.update(pending_deployment=endpoint.removeprefix(ARM), mutation_started=True)
        persist()
        verify_foundry_identity_current(cloud, locks, document)
        if phase["id"] == "foundry-account-phase":
            verify_foundry_agent_current(cloud, locks, document, receipt, sleep)
            status, _, _ = cloud.arm("GET", data["account_resource_id"], FOUNDRY_API, allowed=(200, 404))
            require(status == 404, "native-foundry-first-run-account-already-exists")
        elif phase["id"] == "foundry-project-phase":
            verify_foundry_live_readiness(cloud, locks, document, receipt, sleep)
        verify_foundry_live_inventory(cloud, locks, document, observations)
        locks.authorize(document)
        cloud.request("PUT", endpoint + "?api-version=2022-09-01", ARM, data=payload, allowed=(200, 201, 202))
        wait_foundry_resource(cloud, locks, endpoint.removeprefix(ARM),
            lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded",
            sleep, attempts=1440, read=lambda: cloud.request("GET", endpoint + "?api-version=2022-09-01", ARM),
            document=document)
        for step in document["deployment"]["steps"]:
            if step["id"] not in phase["step_ids"]:
                continue
            child = deployment_endpoint(document, step).removeprefix(ARM)
            result = wait_foundry_resource(cloud, locks, child,
                lambda body: body.get("properties", {}).get("provisioningState") == "Succeeded",
                sleep, attempts=1, read=lambda: cloud.request(
                    "GET", ARM + child + "?api-version=2022-09-01", ARM), document=document)
            receipt["deployments"].append({"step_id": step["id"], "id": child, "status": "succeeded"})
            if step["id"] == data["account_step"]:
                foundry_readiness(cloud, locks, document, receipt, persist, result, sleep)
        observation = observe_foundry_phase(cloud, document, phase, current, observations, receipt)
        receipt["foundry_phases"].append({"id": phase["id"], "status": "succeeded",
                                         "changes_hash": digest(phase["changes"])})
        observations = observation["resources"]
        receipt["foundry_phase_observations"].append(observation)
        receipt.pop("pending_deployment", None)
        persist()
        preceding = {row["resource_id"]: row for row in phase["changes"]}


def verify_foundry_phase_receipts(document, receipt):
    data = document.get("deployment", {}).get("foundry_lifecycle")
    if data is None:
        return
    if "foundry_identity_stage" in document["deployment"]:
        verify_foundry_identity_receipt(document, receipt)
        return
    require(receipt.get("foundry_identity_continuation") == document["deployment"].get("foundry_identity_continuation"),
            "native-foundry-identity-continuation-receipt-missing")
    require(receipt.get("foundry_phases") == [
        {"id": phase["id"], "status": "succeeded", "changes_hash": digest(phase["changes"])}
        for phase in data["phases"]], "native-foundry-phase-receipts-incomplete")
    verify_foundry_readiness_receipt(document, receipt)
    require(data.get("contract") == FOUNDRY_CONTRACT, "native-foundry-sequence-required")
    observations = receipt.get("foundry_phase_observations")
    require(isinstance(observations, list) and len(observations) == 3,
            "native-foundry-phase-observations-incomplete")
    verify_foundry_observation_history(document, receipt)
    proof = receipt["foundry_readiness"]
    require(observations[1]["resources"][data["account_resource_id"]]["body_hash"] == proof["account_body_hash"],
            "native-foundry-account-observation-mismatch")
    if data["agent_identity_binding"]:
        agent = receipt["foundry_agent_readiness"]
        require(observations[0]["resources"][agent["resource_id"]]["body_hash"] == agent["identity_body_hash"],
                "native-foundry-agent-identity-observation-mismatch")


def verify_foundry_receipt(document, receipt):
    if "foundry_lifecycle" not in document.get("deployment", {}):
        return
    if "foundry_identity_stage" in document["deployment"]:
        verify_foundry_identity_receipt(document, receipt)
        return
    require(receipt.get("run_id") == document["run_id"]
            and receipt.get("manifest_hash") == document["manifest_hash"]
            and receipt.get("source_commit") == document["source"]["commit"]
            and receipt.get("target") == document["target"]
            and not receipt.get("pending_deployment") and not receipt.get("pending_foundry_gate"),
            "native-foundry-receipt-context-required")
    verify_foundry_phase_receipts(document, receipt)
    closure = receipt.get("foundry_final_closure")
    observed = foundry_inventory_observations(document, closure)
    last = receipt["foundry_phase_observations"][-1]
    require(digest(closure) == last["closure_hash"] == receipt.get("inventory_closure_hash")
            and observed == last["resources"], "native-foundry-final-instance-evidence-changed")
    verify_bootstrap_final_closure(document, closure)
    foundation = document["deployment"].get("bootstrap_foundation", {})
    preserved = {key for key, row in foundation.get("resources", {}).items() if row.get("disposition") == "preserve"}
    groups, ownership = receipt.get("resource_groups"), receipt.get("ownership")
    require(isinstance(groups, list) and isinstance(ownership, list)
            and all(isinstance(row, dict) and isinstance(row.get("resource_id"), str) for row in groups + ownership),
            "native-foundry-final-ownership-evidence-required")
    group_ids = [row["resource_id"] for row in groups]
    owned_ids = [row["resource_id"] for row in ownership]
    require(len(group_ids) == len(set(group_ids)) and len(owned_ids) == len(set(owned_ids))
            and set(group_ids) == set(closure["groups"]) == {scope.lower() for scope in document["locks"]["scopes"]}
            and set(owned_ids) == set(closure["resources"]) - preserved
            and all(isinstance(row.get("owner"), dict) and all(
                row["owner"].get(key) == document["target"][key] for key in ("factory_id", "scaleset_id"))
                for row in groups + ownership)
            and all(row.get("body_hash") == observed[row["resource_id"]]["body_hash"] for row in groups + ownership)
            and all(all(row.get(key) == closure["resources"][row["resource_id"]].get(key)
                        for key in ("type", "api_version", "body_hash", "etag")) for row in ownership)
            and all(row.get("etag") == closure["groups"][row["resource_id"]].get("etag") for row in groups),
            "native-foundry-final-ownership-evidence-changed")


def verify_foundry_readiness_receipt(document, receipt):
    """Require service readiness for the reviewed configuration, not general effective access."""
    verify_foundry_provider_readiness_receipt(document, receipt)


def verify_foundry_provider_readiness_receipt(document, receipt):
    data = document["deployment"]["foundry_lifecycle"]
    verify_foundry_agent_receipt(document, receipt)
    proof = receipt.get("foundry_readiness", {})
    expected_status = "provider-ready" if data["require_capability_host"] else "succeeded"
    completed = data["principal_binding"]["required_gates"]
    require(proof.get("contract") == FOUNDRY_CONTRACT and proof.get("status") == expected_status
            and proof.get("account_resource_id") == data["account_resource_id"]
            and foundry_identity_guid(proof.get("principal_id")) and hash_value(proof.get("account_body_hash"))
            and proof.get("principal_binding_hash") == digest(data["principal_binding"])
            and proof.get("completed_gates") == completed,
            "native-foundry-readiness-receipt-incomplete")
    require("grants" not in proof, "native-foundry-unreviewed-sami-grants-forbidden")
    if data["require_capability_host"]:
        host = proof.get("capability_host", {})
        agent = receipt["foundry_agent_readiness"]
        require(host.get("id") == data["account_resource_id"] + "/capabilityHosts/"
                + data["account_resource_id"].rsplit("/", 1)[-1] + "@aml_aiagentservice"
                and host.get("status") == "Succeeded" and hash_value(host.get("body_hash"))
                and host.get("configured_identity_id") == agent["resource_id"]
                and host.get("configured_principal_id") == agent["principal_id"]
                and host.get("agent_proof_hash") == digest(agent)
                and host.get("evidence") == "account-provider-readiness-with-source-selected-uami"
                and host.get("general_effective_permissions_proven") is False,
                "native-foundry-capability-host-receipt-incomplete")


def validate_preservation_permit(document):
    foundation = document["deployment"]["bootstrap_foundation"]
    permit = foundation.get("preservation_permit")
    require(isinstance(permit, dict) and permit.get("contract") == PRESERVATION_PERMIT_CONTRACT
            and permit.get("approved") is True and guid(permit.get("review_id"))
            and hash_value(permit.get("owner_hash")) and guid(permit.get("workflow_id"))
            and permit.get("approval_hash") == digest({key: value for key, value in permit.items()
                                                     if key != "approval_hash"}),
            "reviewed-preservation-consent-required")
    proposal = permit.get("proposal")
    require(isinstance(proposal, dict) and permit.get("proposal_hash") == digest(proposal)
            and proposal.get("owner_hash") == permit["owner_hash"]
            and proposal.get("workflow_id") == permit["workflow_id"] == foundation["workflow_id"]
            and proposal.get("source_commit") == document["source"]["commit"]
            and hash_value(proposal.get("bootstrap_hash"))
            and proposal.get("operator_id") == document["identity"]["object_id"]
            and proposal.get("deployment_object_id") == document["identity"]["deployment_object_id"]
            and proposal.get("scopes") == sorted(foundation["groups"])
            and isinstance(proposal.get("target"), dict)
            and all(proposal.get("target", {}).get(key) == document["target"][key] for key in
                    ("factory_id", "scaleset_id", "subscription_id", "tenant_id", "region"))
            and all(proposal.get(key) == [] for key in ("writes", "deletes", "ownership_grants")),
            "reviewed-preservation-context-mismatch")
    runner = proposal.get("runner", {})
    require(isinstance(runner, dict), "reviewed-preservation-runner-proof-required")
    vm = runner.get("resource_id", "")
    resources = proposal.get("resources")
    require(isinstance(vm, str) and NESTED_ID.fullmatch(vm)
            and resource_type_from_id(vm) == "microsoft.compute/virtualmachines"
            and vm in foundation["resources"] and isinstance(foundation["resources"][vm], dict)
            and foundation["resources"][vm].get("disposition") == "preserve"
            and hash_value(runner.get("request_hash"))
            and hash_value(runner.get("body_hash"))
            and runner["body_hash"] == foundation["resources"][vm].get("body_hash")
            and runner.get("receipt_hash") == digest(foundation["resources"][vm].get("receipt"))
            and isinstance(resources, dict) and len(resources) == 2
            and all(isinstance(key, str) and isinstance(row, dict) for key, row in resources.items()),
            "reviewed-preservation-runner-proof-required")
    extension = vm + "/extensions/mde.linux"
    commands = [key for key in resources if re.fullmatch(
        re.escape(vm) + r"/runcommands/register-aifactory-gha-\d{14}-\d+", key)]
    require(len(commands) == 1 and set(resources) == {extension, commands[0]},
            "reviewed-preservation-exact-children-required")
    ext, command = resources[extension], resources[commands[0]]
    require(ext.get("type") == "microsoft.compute/virtualmachines/extensions"
            and ext.get("publisher") == "Microsoft.Azure.AzureDefenderForServers"
            and ext.get("extension_type") == "MDE.Linux" and ext.get("provisioning_state") in ("Failed", "Succeeded")
            and command.get("type") == "microsoft.compute/virtualmachines/runcommands"
            and command.get("provisioning_state") == command.get("execution_state") == "Succeeded"
            and type(command.get("exit_code")) is int and command["exit_code"] == 0
            and hash_value(command.get("script_sha256"))
            and all(row.get("scope") == arm_scope(vm) for row in resources.values())
            and isinstance(proposal.get("warnings"), list)
            and all(isinstance(row, dict) for row in proposal["warnings"]) and any(
                row.get("resource_id") == extension and row.get("code") == "defender-security-readiness-unverified"
                and row.get("provisioning_state") == ext["provisioning_state"] for row in proposal["warnings"]),
            "reviewed-preservation-state-or-security-warning-required")
    return permit


def has_dns_soa_permit(proof):
    return ("dns_soa_preservation_permit" in proof or "dns_soa_baseline" in proof
            or any(isinstance(row, dict) and row.get("preservation") == "reviewed-dns-soa-instance"
                   for row in proof.get("resources", {}).values()))


def validate_dns_zone_receipt(receipt, parent, operator_id):
    fields = {"resource_id", "receipt_hash", "plan_id", "plan_hash"}
    require(isinstance(receipt, dict) and set(receipt) in (fields, fields | {"basis"})
            and receipt["resource_id"] == parent and guid(receipt["plan_id"])
            and hash_value(receipt["plan_hash"]) and hash_value(receipt["receipt_hash"]),
            "dns-soa-exact-preserved-parent-required")
    if "basis" not in receipt:
        return
    basis = receipt["basis"]
    hashes = {"approved_current_review_sha256", "native_plan_hash", "source_payload_sha256",
              "recovery_archive_hash", "success_receipt_hash", "baseline_body_hash"}
    require(isinstance(basis, dict) and set(basis) == hashes | {
                "contract", "plan_id", "plan_hash", "operator_id", "resource_id", "provenance"}
            and basis["contract"] == "accepted-current-prerequisite-baseline-v1"
            and basis["plan_id"] == receipt["plan_id"] and basis["plan_hash"] == receipt["plan_hash"]
            and guid(basis["operator_id"]) and basis["operator_id"] == operator_id
            and basis["resource_id"] == parent and all(hash_value(basis[key]) for key in hashes)
            and receipt["receipt_hash"] == digest(basis)
            and isinstance(basis["provenance"], dict)
            and set(basis["provenance"]) == {"native_effect_index", "native_effect_hash"}
            and type(basis["provenance"]["native_effect_index"]) is int
            and 10 <= basis["provenance"]["native_effect_index"] < 131
            and hash_value(basis["provenance"]["native_effect_hash"]),
            "dns-soa-parent-baseline-witness-invalid")


def validate_dns_soa_preservation_permit(document):
    """Present-state consent only; the protected baseline proves the parent, not SOA ownership."""
    proof = document["deployment"]["bootstrap_foundation"]
    require(proof.get("contract") == EXACT_BOOTSTRAP_CONTRACT
            and document["operation"] in ("create-factory", "create-scaleset", "deploy-project"),
            "dns-soa-preservation-operation-required")
    permit = proof.get("dns_soa_preservation_permit")
    require(isinstance(permit, dict) and set(permit) == {
        "contract", "approved", "review_id", "owner_hash", "workflow_id", "proposal_hash", "proposal", "approval_hash"}
        and permit["contract"] == DNS_SOA_PERMIT_CONTRACT and permit["approved"] is True
        and guid(permit["review_id"]) and hash_value(permit["owner_hash"])
        and guid(permit["workflow_id"]) and permit["approval_hash"] == digest({
            key: value for key, value in permit.items() if key != "approval_hash"}),
        "dns-soa-preservation-consent-required")
    proposal, baseline = permit["proposal"], proof.get("dns_soa_baseline")
    require(isinstance(baseline, dict) and set(baseline) == {"owner_hash", "workflow_id", "bootstrap_hash", "zones"}
            and baseline["owner_hash"] == permit["owner_hash"]
            and baseline["workflow_id"] == permit["workflow_id"] == proof.get("workflow_id")
            and hash_value(baseline["bootstrap_hash"]) and baseline["bootstrap_hash"] == proof.get("evidence_hash")
            and isinstance(baseline["zones"], dict) and 1 <= len(baseline["zones"]) <= 128,
            "dns-soa-original-zone-baseline-required")
    require(isinstance(proposal, dict) and set(proposal) == {
        "consent", "owner_hash", "workflow_id", "source_commit", "operator_id", "deployment_object_id",
        "target", "scopes", "bootstrap_hash", "baseline_hash", "parents", "resources",
        "writes", "deletes", "ownership_grants"}
        and permit["proposal_hash"] == digest(proposal)
        and proposal["consent"] == "present-state-preserve-only"
        and proposal["owner_hash"] == baseline["owner_hash"]
        and proposal["workflow_id"] == baseline["workflow_id"]
        and proposal["bootstrap_hash"] == baseline["bootstrap_hash"]
        and proposal["baseline_hash"] == digest(baseline)
        and proposal["source_commit"] == document["source"]["commit"] == proof.get("source_commit")
        and proposal["operator_id"] == document["identity"]["object_id"]
        and proposal["deployment_object_id"] == document["identity"]["deployment_object_id"]
        and proposal["target"] == document["target"]
        and proposal["scopes"] == sorted(proof["groups"]) == sorted({scope.lower() for scope in document["locks"]["scopes"]})
        and all(proposal[key] == [] for key in ("writes", "deletes", "ownership_grants")),
        "dns-soa-preservation-context-mismatch")
    parents, resources = proposal["parents"], proposal["resources"]
    require(isinstance(parents, dict) and isinstance(resources, dict)
            and set(parents) == set(baseline["zones"])
            and all(isinstance(key, str) and key == key.lower() and DNS_SOA_ZONE_ID.fullmatch(key)
                    and arm_scope(key) in proof["groups"] for key in parents)
            and set(resources) == {key + "/soa/@" for key in parents}
            and set(resources) == {key for key, row in proof["resources"].items()
                                  if isinstance(row, dict) and row.get("preservation") == "reviewed-dns-soa-instance"}
            and not set(resources) & set(document["deployment"].get("known_ownership", {})),
            "dns-soa-exact-apices-required")
    fields = {"type", "scope", "api_version", "body_hash", "etag"}
    for parent, entry in parents.items():
        original = baseline["zones"][parent]
        require(isinstance(original, dict) and set(original) == fields | {"disposition", "preservation", "receipt"}
                and original == proof["resources"].get(parent)
                and original["type"] == "microsoft.network/privatednszones" and original["scope"] == arm_scope(parent)
                and isinstance(original["api_version"], str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", original["api_version"])
                and hash_value(original["body_hash"])
                and (original["etag"] is None or isinstance(original["etag"], str) and 0 < len(original["etag"]) <= 1024)
                and original["disposition"] == "preserve" and original["preservation"] == "bootstrap-prerequisite"
                and isinstance(entry, dict) and set(entry) == {"baseline_hash", "record_set_inventory_hash"}
                and entry["baseline_hash"] == digest(original) and hash_value(entry["record_set_inventory_hash"]),
                "dns-soa-exact-preserved-parent-required")
        validate_dns_zone_receipt(original["receipt"], parent, proposal["operator_id"])
        identifier = parent + "/soa/@"
        row, actual = resources[identifier], proof["resources"].get(identifier)
        require(isinstance(row, dict) and set(row) == fields | {"parent_id"} and row["parent_id"] == parent
                and row["type"] == "microsoft.network/privatednszones/soa" and row["scope"] == arm_scope(parent)
                and isinstance(row["api_version"], str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", row["api_version"])
                and hash_value(row["body_hash"])
                and (row["etag"] is None or isinstance(row["etag"], str) and 0 < len(row["etag"]) <= 1024)
                and isinstance(actual, dict) and actual == {
                    **{field: row[field] for field in fields}, "disposition": "preserve",
                    "preservation": "reviewed-dns-soa-instance", "permit_hash": permit["approval_hash"]},
                "dns-soa-preservation-cannot-grant-ownership")
    return permit


def dns_record_set_inventory(closure, parent):
    """Fingerprint all eight independently collected private-DNS record-set types."""
    require(isinstance(closure, dict) and isinstance(closure.get("collections"), dict)
            and isinstance(closure.get("resources"), dict), "dns-soa-record-set-inventory-required")
    collections, resources = {}, {}
    for kind in DNS_RECORD_TYPES:
        path = parent + "/" + kind
        entry = closure["collections"].get(path)
        require(isinstance(entry, dict) and set(entry) == {"api_version", "ids", "items", "body_hash", "unsupported"}
                and entry["unsupported"] is None and hash_value(entry["body_hash"])
                and isinstance(entry["api_version"], str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", entry["api_version"])
                and isinstance(entry["ids"], list)
                and all(isinstance(key, str) and key == key.lower() and NESTED_ID.fullmatch(key)
                        and key.rsplit("/", 1)[0] == path for key in entry["ids"])
                and entry["ids"] == sorted(set(entry["ids"]))
                and isinstance(entry["items"], list)
                and all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in entry["items"])
                and sorted(row["id"].lower() for row in entry["items"]) == entry["ids"]
                and digest(entry["items"]) == entry["body_hash"], "dns-soa-record-set-inventory-required")
        rows = {key: row for key, row in closure["resources"].items() if key.rsplit("/", 1)[0] == path}
        require(set(rows) == set(entry["ids"]) and all(isinstance(row, dict)
                and row.get("type") == "microsoft.network/privatednszones/" + kind
                and hash_value(row.get("body_hash")) for row in rows.values()),
                "dns-soa-record-set-inventory-incomplete")
        collections[path], resources = entry, {**resources, **rows}
    require(collections[parent + "/soa"]["ids"] == [parent + "/soa/@"], "dns-soa-exact-apices-required")
    return {"collections": collections, "resources": resources}


def verify_dns_soa_preservation(document, closure):
    proof = document["deployment"]["bootstrap_foundation"]
    permit = validate_dns_soa_preservation_permit(document)
    for parent, entry in permit["proposal"]["parents"].items():
        require(digest(dns_record_set_inventory(closure, parent)) == entry["record_set_inventory_hash"],
                "dns-soa-record-set-inventory-changed")
        for identifier in (parent, parent + "/soa/@"):
            metadata = closure["resources"].get(identifier)
            require(isinstance(metadata, dict) and all(metadata.get(field) == proof["resources"][identifier][field]
                    for field in ("type", "api_version", "body_hash", "etag")), "dns-soa-preserved-instance-changed")


def validate_exact_bootstrap(document):
    proof = document["deployment"]["bootstrap_foundation"]
    target = document["target"]
    require(document["operation"] in ("create-factory", "create-scaleset", "deploy-project")
            and proof.get("contract") == EXACT_BOOTSTRAP_CONTRACT
            and proof.get("source_commit") == document["source"]["commit"]
            and hash_value(proof.get("evidence_hash")) and guid(proof.get("workflow_id")),
            "exact-bootstrap-source-proof-required")
    groups, resources = proof.get("groups"), proof.get("resources")
    scopes = {scope.lower() for scope in document["locks"]["scopes"]}
    require(isinstance(groups, dict) and groups and set(groups) <= scopes
            and isinstance(resources, dict) and set(groups) <= set(resources),
            "exact-bootstrap-scopes-required")
    permit = validate_preservation_permit(document) if "preservation_permit" in proof else None
    permit_rows = permit["proposal"]["resources"] if permit else {}
    dns_permit = validate_dns_soa_preservation_permit(document) if has_dns_soa_permit(proof) else None
    dns_rows = dns_permit["proposal"]["resources"] if dns_permit else {}
    require(not set(dns_rows) & set(permit_rows), "dns-soa-permits-must-be-independent")
    require(set(permit_rows) <= set(resources), "reviewed-preservation-resources-missing")
    for group, receipt in groups.items():
        require(group == group.lower() and RG_ID.fullmatch(group) and isinstance(receipt, dict)
                and guid(receipt.get("plan_id")) and hash_value(receipt.get("plan_hash")),
                "created-bootstrap-group-receipt-required")
    for identifier, row in resources.items():
        require(isinstance(identifier, str) and identifier == identifier.lower()
                and (RG_ID.fullmatch(identifier) or NESTED_ID.fullmatch(identifier))
                and arm_scope(identifier) in groups and isinstance(row, dict),
                "exact-bootstrap-resource-scope-required")
        kind = "microsoft.resources/resourcegroups" if identifier in groups else resource_type_from_id(identifier)
        require(row.get("type") == kind and row.get("scope") == arm_scope(identifier)
                and isinstance(row.get("api_version"), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-preview)?", row["api_version"])
                and hash_value(row.get("body_hash")) and "etag" in row
                and (row["etag"] is None or isinstance(row["etag"], str) and 0 < len(row["etag"]) <= 1024),
                "exact-bootstrap-resource-instance-required")
        if row.get("preservation") == "reviewed-dns-soa-instance":
            require(identifier in dns_rows, "dns-soa-preservation-consent-required")
            continue
        if row.get("preservation") == "reviewed-instance":
            require(identifier in permit_rows and identifier not in groups
                    and row.get("disposition") == "preserve" and "owner" not in row and "receipt" not in row
                    and row.get("permit_hash") == permit["approval_hash"]
                    and all(row.get(key) == permit_rows[identifier].get(key)
                            for key in ("type", "scope", "api_version", "body_hash", "etag")),
                    "reviewed-preservation-cannot-grant-ownership")
            continue
        require(identifier not in permit_rows and "permit_hash" not in row,
                "reviewed-preservation-cannot-grant-ownership")
        receipt = row.get("receipt")
        require(isinstance(receipt, dict) and guid(receipt.get("plan_id"))
                and hash_value(receipt.get("plan_hash")) and hash_value(receipt.get("receipt_hash"))
                and isinstance(receipt.get("resource_id"), str),
                "exact-bootstrap-consumed-receipt-required")
        origin = receipt["resource_id"]
        require(origin in resources and arm_scope(origin) == row["scope"], "bootstrap-receipt-resource-mismatch")
        disposition = row.get("disposition")
        require(disposition in ("owned", "preserve"), "bootstrap-resource-disposition-required")
        if disposition == "owned":
            owner = row.get("owner")
            require(origin == identifier and isinstance(owner, dict) and set(owner) <= set(TAG_KEYS)
                    and all(owner.get(key) == target[key] for key in ("factory_id", "scaleset_id"))
                    and ("project_id" not in owner or re.fullmatch(r"\d{3}", owner["project_id"])),
                    "exact-bootstrap-resource-owner-required")
        else:
            require("owner" not in row and identifier not in groups
                    and (origin == identifier or identifier.startswith(origin + "/"))
                    and row.get("preservation") in ("bootstrap-prerequisite", "provider-readonly"),
                    "bootstrap-preservation-cannot-authorize-ownership")
            if origin != identifier:
                require(row["preservation"] == "provider-readonly",
                        "bootstrap-dependent-requires-exact-receipt")
        if identifier in groups:
            require(disposition == "owned" and all(receipt[key] == groups[identifier][key]
                    for key in ("plan_id", "plan_hash")), "bootstrap-group-proof-conflict")
    return proof


def bootstrap_resource_versions(document):
    proof = document.get("deployment", {}).get("bootstrap_foundation", {})
    return {key: row["api_version"] for key, row in proof.get("resources", {}).items()
            if proof.get("contract") == EXACT_BOOTSTRAP_CONTRACT}


def exact_bootstrap_snapshot(cloud, document):
    proof = validate_exact_bootstrap(document)
    closure, bodies = collect_resource_closure(cloud, sorted(proof["groups"]),
                                               bootstrap_resource_versions(document))
    require(set(bodies) == set(proof["resources"]), "bootstrap-exact-resource-inventory-changed")
    if has_dns_soa_permit(proof):
        verify_dns_soa_preservation(document, closure)
    if "preservation_permit" in proof:
        permit = validate_preservation_permit(document)
        proposal = permit["proposal"]
        for identifier, row in proposal["resources"].items():
            props = bodies[identifier].get("properties", {})
            require(props.get("provisioningState") == row["provisioning_state"],
                    "reviewed-preservation-instance-state-changed")
            if row["type"].endswith("/extensions"):
                require(props.get("publisher") == row["publisher"] and props.get("type") == row["extension_type"]
                        and props.get("settings", {}).get("azureResourceId", "").lower() == proposal["runner"]["resource_id"],
                        "reviewed-defender-instance-changed")
            else:
                script = clean_path(Path(__file__).parent / "runner-registration.sh").read_text(encoding="utf-8").strip()
                require(hashlib.sha256(script.encode()).hexdigest() == row["script_sha256"]
                        and props.get("source", {}).get("script", "").replace("\r\n", "\n").strip() == script,
                        "reviewed-registration-source-changed")
                _, _, expanded = cloud.request("GET", ARM + identifier + "?api-version=" + row["api_version"]
                                               + "&%24expand=instanceView", ARM)
                instance = expanded.get("properties", {}).get("instanceView", {})
                require(instance.get("executionState") == "Succeeded" and instance.get("exitCode") == 0,
                        "reviewed-registration-execution-not-terminal")
                expanded.get("properties", {}).pop("instanceView", None)
                require(digest(expanded) == row["body_hash"], "reviewed-registration-instance-changed")
    result = {}
    expected = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    for group in proof["groups"]:
        verify_group_ownership(bodies[group], expected, bodies)
    for identifier, row in proof["resources"].items():
        metadata = (closure["groups"] if identifier in proof["groups"] else closure["resources"])[identifier]
        require_bootstrap_instance(identifier, body_hash=metadata["body_hash"] == row["body_hash"],
                                   etag=metadata.get("etag") == row["etag"])
        tags = bodies[identifier].get("tags") or {}
        require(not str(tags.get("aifactory.shared", "")).lower() == "true"
                and all(tags.get(TAG_KEYS[key], value) == value for key, value in expected.items()),
                "bootstrap-resource-ownership-conflict")
        if row["disposition"] == "preserve":
            if row["preservation"] == "provider-readonly":
                names = set(cloud.provider_operations(row["type"].split("/")[0]))
                require(row["type"] + "/read" in names
                        and not any(row["type"] + "/" + action in names for action in ("write", "delete")),
                        "bootstrap-provider-child-is-writable")
            result[identifier] = {"body_hash": row["body_hash"], "preserve": True}
        else:
            require(all(tags.get(TAG_KEYS[key], value) == value for key, value in row["owner"].items()),
                    "bootstrap-resource-ownership-conflict")
            result[identifier] = {"body_hash": row["body_hash"], "owner": row["owner"]}
    return result


def verify_bootstrap_preservation(document, changes):
    proof = document["deployment"].get("bootstrap_foundation", {})
    if proof.get("contract") != EXACT_BOOTSTRAP_CONTRACT:
        return
    if has_dns_soa_permit(proof):
        validate_exact_bootstrap(document)
    retained = {key for key, row in proof["resources"].items() if row["disposition"] == "preserve"}
    require(not any(change["change_type"] != "NoChange" and any(
        change["resource_id"].lower() == key or change["resource_id"].lower().startswith(key + "/")
        for key in retained) for change in changes), "bootstrap-prerequisite-write-forbidden")


def verify_bootstrap_final_closure(document, closure, bodies=None):
    proof = document["deployment"].get("bootstrap_foundation", {})
    if proof.get("contract") != EXACT_BOOTSTRAP_CONTRACT:
        return set()
    if has_dns_soa_permit(proof):
        validate_exact_bootstrap(document)
        verify_dns_soa_preservation(document, closure)
    preserved = {key for key, row in proof["resources"].items() if row["disposition"] == "preserve"}
    if not preserved:
        return preserved
    require(isinstance(closure, dict) and isinstance(closure.get("resources"), dict)
            and isinstance(closure.get("groups"), dict), "bootstrap-final-closure-required")
    resources, groups = closure["resources"], closure["groups"]
    scopes = {scope.lower() for scope in document["locks"]["scopes"]}
    require(set(groups) == scopes and not set(groups) & set(resources)
            and all(isinstance(row, dict) and hash_value(row.get("body_hash")) for row in groups.values())
            and all(isinstance(key, str) and key == key.lower() and arm_scope(key) in scopes
                    and isinstance(row, dict) for key, row in resources.items()),
            "bootstrap-final-closure-scope-mismatch")
    expected = {key for key in proof["resources"] if any(key == parent or key.startswith(parent + "/")
                                                       for parent in preserved)}
    require(expected <= set(resources), "bootstrap-preserved-resource-missing-after-deployment")
    protected = {key for key in resources if any(key == parent or key.startswith(parent + "/")
                                               for parent in preserved)}
    require(protected <= set(proof["resources"]), "bootstrap-preserved-descendant-unreviewed")
    if bodies is not None:
        require(set(bodies) == set(resources) | set(groups), "bootstrap-final-closure-body-incomplete")
    for key in protected:
        require(all(resources[key].get(field) == proof["resources"][key].get(field)
                    for field in ("type", "api_version", "body_hash", "etag"))
                and (bodies is None or digest(bodies[key]) == resources[key]["body_hash"]),
                "bootstrap-preserved-resource-changed-during-deployment")
    return preserved


def bootstrap_ownership_snapshot(cloud, document):
    proof = document["deployment"].get("bootstrap_foundation")
    if proof is None:
        return {}
    if proof.get("contract") == EXACT_BOOTSTRAP_CONTRACT:
        return exact_bootstrap_snapshot(cloud, document)
    require(isinstance(proof, dict) and proof.get("contract") == "created-group-ownership-v1"
            and isinstance(proof.get("groups"), dict), "created-bootstrap-groups-proof-required")
    for group, receipt in proof["groups"].items():
        require(isinstance(group, str) and RG_ID.fullmatch(group) and isinstance(receipt, dict)
                and guid(receipt.get("plan_id")) and hash_value(receipt.get("plan_hash")),
                "created-bootstrap-group-receipt-required")
    groups = sorted({scope.lower() for scope in document["locks"]["scopes"]} & set(proof["groups"]))
    if not groups:
        return {}
    closure, bodies = collect_resource_closure(cloud, groups)
    expected = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
    for group in groups:
        verify_group_ownership(bodies[group], expected, bodies)
    result = {}
    for identifier, metadata in closure["resources"].items():
        tags = bodies[identifier].get("tags") or {}
        tagged = {key: tags[TAG_KEYS[key]] for key in TAG_KEYS if TAG_KEYS[key] in tags}
        if tagged:
            require(all(tagged.get(key) == value for key, value in expected.items()),
                    "bootstrap-resource-ownership-conflict")
            continue
        raise Blocked("exact-bootstrap-resource-proof-required")
    return result


def freeze_deployment_plan(cloud, document, source_root):
    """Read-only whole-plan what-if for a caller-resolved, ordered ARM plan."""
    if single_writer(document):
        _, state = RepositoryCoordination(cloud, document).state()
        require(state["active"] is None, "single-writer-repository-active-claim")
        require(not any(key.startswith("runs/" + document["run_id"] + ".") for key in state["records"]),
                "single-writer-run-already-submitted")
    source_root = verify_source(cloud, source_root, document["source"])
    return _freeze_deployment_contents(cloud, document, source_root)


def _freeze_deployment_contents(cloud, document, source_root):
    """Read-only content preflight; only freeze_deployment_plan verifies publication."""
    cloud.verify_identity()
    result = json.loads(canonical(document["deployment"]))
    draft = {**document, "deployment": result}
    persona_helper(source_root).freeze(cloud, draft, result, source_root)
    if "bootstrap_foundation" in result:
        result["bootstrap_ownership"] = bootstrap_ownership_snapshot(cloud, draft)
    for step in result["steps"]:
        template = cloud.compile_template(source_root, step["template"])
        require(set(template["parameters"]) == set(step["parameters"]), "parameters-not-fully-resolved")
        step["template_hash"] = digest(template)
        verify_preserved_network(cloud, draft, step, source_root, template=template, freeze=True)
    if freeze_foundry_identity_stage(cloud, draft, source_root):
        result["configuration_hash"] = digest(document["config"])
        return result
    payload = combined_plan_payload(cloud, draft, source_root)
    result["changes"] = evaluate_what_if(cloud, draft, {"id": "factory", "scope": "subscription"}, payload)
    verify_bootstrap_preservation(draft, result["changes"])
    freeze_foundry_lifecycle(cloud, draft, source_root)
    result["configuration_hash"] = digest(document["config"])
    return result


def persona_helper(source_root):
    path = Path(source_root) / "bootstrap" / "lib" / "registered_personas.py"
    if not path.is_file():
        path = Path(__file__).with_name("registered_personas.py")
    spec = importlib.util.spec_from_file_location("registered_personas_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def persona_worker(document, source_root, *, execute=False):
    try:
        return persona_helper(source_root).worker(document, source_root, execute=execute)
    except (ValueError, RuntimeError, OSError) as error:
        raise Blocked("persona-access-apply-failed" if execute else "persona-access-preflight-failed") from error


def run_deployment_worker(envelope, source_root, expected_run, expected_hash, cloud=None, sleep=time.sleep):
    require(isinstance(envelope, dict), "invalid-worker-envelope")
    envelope = json.loads(canonical(envelope))
    if envelope.get("manifest", {}).get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
        return factory_deletion_module().run_worker(
            envelope, source_root, expected_run, expected_hash, cloud, sleep)
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
    locks = coordination(cloud, document)
    locks.held = dict(context)
    locks.verify_enrollment()
    locks.assert_held()
    locks.execution_claim = _ExecutionClaim(document, locks.read_claim())
    locks.authorize(document)
    if "foundry_lifecycle" in document["deployment"]:
        original_sleep = sleep
        def guarded_sleep(seconds):
            locks.assert_held()
            original_sleep(seconds)
            locks.assert_held()
        sleep = guarded_sleep
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
        if "foundry_identity_stage" in document["deployment"]:
            run_foundry_identity_stage(cloud, locks, document, source_root, receipt, persist, sleep)
            return receipt
        if "foundry_lifecycle" in document["deployment"]:
            receipt["foundry_initial_observations"] = {}
        persona_worker(document, source_root)
        bootstrap_owners = bootstrap_ownership_snapshot(cloud, document)
        require(bootstrap_owners == document["deployment"].get("bootstrap_ownership", {}),
                "bootstrap-resource-inventory-changed-since-prepare")
        before_ids = set()
        previous_owners, previous_receipts = {}, {}
        modified_ids = {row["resource_id"].lower() for row in document["deployment"]["changes"]
                        if row["change_type"] != "NoChange"}
        preserved_ids = {key for key, row in bootstrap_owners.items() if row.get("preserve") is True}
        verify_bootstrap_preservation(document, document["deployment"]["changes"])
        existing_scopes = []
        for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]:
            status, _, group = cloud.arm("GET", scope, RG_API, allowed=(200, 404))
            if status == 200:
                marker = (group.get("tags") or {}).get("AIF-Persona-Access")
                selected = persona_helper(source_root).selected_config(
                    document["config"], document["target"]["environment"])
                require(not marker or marker == persona_helper(source_root).mode(selected),
                        "persona-access-downgrade-forbidden")
                if scope in document["locks"]["scopes"]:
                    existing_scopes.append(scope)
        if existing_scopes:
            closure, current_bodies = collect_resource_closure(cloud, existing_scopes,
                                                               bootstrap_resource_versions(document))
            if "foundry_lifecycle" in document["deployment"]:
                receipt["foundry_initial_observations"] = foundry_inventory_observations(document, closure, current_bodies)
            for scope in existing_scopes:
                verify_group_ownership(current_bodies[scope.lower()],
                                       {key: document["target"][key] for key in ("factory_id", "scaleset_id")}, current_bodies)
            before_ids.update(closure["resources"])
            for key, metadata in closure["resources"].items():
                if key in preserved_ids:
                    require(metadata["body_hash"] == bootstrap_owners[key]["body_hash"],
                            "bootstrap-preserved-resource-instance-changed")
                    continue
                tags = current_bodies[key].get("tags") or {}
                owner = {field: tags[TAG_KEYS[field]] for field in TAG_KEYS if TAG_KEYS[field] in tags}
                if all(field in owner for field in ("factory_id", "scaleset_id")):
                    previous_owners[key] = owner
                else:
                    evidence = document["deployment"].get("known_ownership", {}).get(key, {})
                    if not evidence and key in bootstrap_owners:
                        require_bootstrap_instance(
                            key, body_hash=bootstrap_owners[key]["body_hash"] == metadata["body_hash"])
                        previous_owners[key] = bootstrap_owners[key]["owner"]
                    else:
                        previous_owners[key] = verified_receipt_owner(locks, evidence, key, metadata["body_hash"], previous_receipts)
                require(all(previous_owners[key].get(field) == document["target"][field]
                            for field in ("factory_id", "scaleset_id")), "existing-resource-owner-mismatch")
                require(key not in modified_ids or not previous_owners[key].get("project_id")
                        or previous_owners[key]["project_id"] in document["target"]["project_ids"],
                        "existing-other-project-resource-write-forbidden")
        locks.assert_held()
        cloud.verify_identity(require_default=True)
        verify_foundry_identity_current(cloud, locks, document)
        payload = combined_plan_payload(cloud, document, source_root)
        root_step = {"id": "factory", "scope": "subscription"}
        reviewed = sorted(({**row, "resource_id": row["resource_id"].lower()}
                           for row in document["deployment"]["changes"]), key=lambda row: row["resource_id"])
        require(evaluate_what_if(cloud, document, root_step, payload, sleep) == reviewed,
                "arm-what-if-changed-since-prepare")
        locks.assert_held()
        locks.authorize(document)
        require(bootstrap_ownership_snapshot(cloud, document) == bootstrap_owners,
                "bootstrap-resource-inventory-changed-before-write")
        for step in document["deployment"]["steps"]:
            verify_preserved_network(cloud, document, step, source_root)
        if "foundry_lifecycle" in document["deployment"]:
            run_foundry_phases(cloud, locks, document, source_root, receipt, persist, sleep)
            verify_foundry_phase_receipts(document, receipt)
        else:
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
        locks.assert_held()
        cloud.verify_identity(require_default=True)
        receipt["persona_access"] = persona_worker(document, source_root, execute=True)
        locks.assert_held()
        persist()
        closure, bodies = collect_resource_closure(cloud, document["locks"]["scopes"],
                                                   bootstrap_resource_versions(document))
        verify_bootstrap_final_closure(document, closure, bodies)
        if "foundry_lifecycle" in document["deployment"]:
            last = receipt["foundry_phase_observations"][-1]
            require(foundry_inventory_observations(document, closure, bodies) == last["resources"]
                    and digest(closure) == last["closure_hash"], "native-foundry-final-instance-changed")
            receipt["foundry_final_closure"] = copy.deepcopy(closure)
            account_id = document["deployment"]["foundry_lifecycle"]["account_resource_id"]
            require(str(bodies.get(account_id, {}).get("identity", {}).get("principalId", "")).lower()
                    == receipt["foundry_readiness"]["principal_id"], "foundry-final-principal-changed")
            require(str(bodies.get(account_id, {}).get("identity", {}).get("tenantId", "")).lower()
                    == document["target"]["tenant_id"].lower(), "foundry-final-tenant-changed")
            verify_foundry_account_agent(document, bodies.get(account_id, {}), receipt)
            verify_foundry_agent_current(cloud, locks, document, receipt, sleep)
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
            if resource_id in preserved_ids:
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
        foundation = document["deployment"].get("bootstrap_foundation", {})
        if foundation.get("contract") == EXACT_BOOTSTRAP_CONTRACT:
            receipt["bootstrap_preserved"] = {
                key: row for key, row in foundation["resources"].items() if row["disposition"] == "preserve"}
            if "preservation_permit" in foundation:
                receipt["bootstrap_preservation_permit"] = foundation["preservation_permit"]
            if "dns_soa_preservation_permit" in foundation:
                receipt["bootstrap_dns_soa_preservation_permit"] = foundation["dns_soa_preservation_permit"]
                receipt["bootstrap_dns_soa_baseline"] = foundation["dns_soa_baseline"]
            if preserved_ids:
                receipt["bootstrap_final_closure"] = closure
        require(receipt["ownership"] or receipt["resource_groups"], "post-deployment-owned-inventory-empty")
        require(set(document["target"]["project_ids"]) <= {
            row["owner"].get("project_id") for row in receipt["ownership"] + receipt["resource_groups"]},
            "selected-project-inventory-incomplete")
        if "foundry_lifecycle" in document["deployment"]:
            verify_foundry_receipt(document, receipt)
            verify_foundry_identity_current(cloud, locks, document)
            verify_foundry_live_readiness(cloud, locks, document, receipt, sleep)
            verify_foundry_live_inventory(cloud, locks, document, last["resources"], closure_hash=last["closure_hash"])
        locks.authorize(document)
        receipt["status"] = "succeeded"
        persist()
    except BaseException as error:
        receipt["status"] = "reconciliation-required"
        receipt.update(failure_fields(error, "unexpected-worker-failure"))
        persist()
    finally:
        cloud.tokens.clear()
    return receipt


def verify_worker_receipt(locks, document):
    _, _, result = locks.request("GET", "runs/" + document["run_id"] + ".worker.json")
    if document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
        return factory_deletion_module().verify_worker_result(document, result)
    require(isinstance(result, dict) and result.get("schema") == 1 and result.get("status") == "succeeded"
            and result.get("run_id") == document["run_id"] and result.get("manifest_hash") == document["manifest_hash"]
            and result.get("source_commit") == document["source"]["commit"] and result.get("target") == document["target"],
            "scoped-worker-receipt-unverified")
    if "foundry_identity_stage" in document["deployment"]:
        verify_foundry_identity_receipt(document, result)
        return result
    expected = [step["id"] for step in document["deployment"]["steps"]]
    require([step.get("step_id") for step in result.get("deployments", [])] == expected,
            "scoped-worker-steps-incomplete")
    verify_foundry_receipt(document, result)
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
    foundation = document["deployment"].get("bootstrap_foundation", {})
    if foundation.get("contract") == EXACT_BOOTSTRAP_CONTRACT:
        if has_dns_soa_permit(foundation):
            validate_exact_bootstrap(document)
        require(result.get("bootstrap_dns_soa_preservation_permit") == foundation.get("dns_soa_preservation_permit")
                and result.get("bootstrap_dns_soa_baseline") == foundation.get("dns_soa_baseline"),
                "scoped-worker-dns-soa-preservation-incomplete")
        preserved = {key: row for key, row in foundation["resources"].items() if row["disposition"] == "preserve"}
        require(result.get("bootstrap_preserved") == preserved,
            "scoped-worker-preservation-evidence-incomplete")
        require(result.get("bootstrap_preservation_permit") == foundation.get("preservation_permit"),
                "scoped-worker-reviewed-preservation-incomplete")
        if preserved:
            closure = result.get("bootstrap_final_closure")
            require(isinstance(closure, dict) and digest(closure) == result["inventory_closure_hash"],
                    "scoped-worker-final-preservation-closure-unverified")
            verify_bootstrap_final_closure(document, closure)
            ownership = result["ownership"]
            require(all(isinstance(row, dict) and isinstance(row.get("resource_id"), str) for row in ownership),
                    "scoped-worker-final-ownership-unverified")
            identifiers = [row["resource_id"].lower() for row in ownership]
            require(len(set(identifiers)) == len(identifiers)
                    and set(identifiers) == set(closure["resources"]) - set(preserved)
                    and all(all(row.get(field) == closure["resources"][row["resource_id"].lower()].get(field)
                                for field in ("type", "api_version", "body_hash", "etag")) for row in ownership)
                    and all(row["body_hash"] == closure["groups"][row["resource_id"].lower()].get("body_hash")
                            and row.get("etag") == closure["groups"][row["resource_id"].lower()].get("etag")
                            for row in groups),
                    "scoped-worker-final-ownership-unverified")
    return result


def protected_worker_envelope(document, locks):
    raw = canonical({"manifest": document, "lease_context": locks.held})
    require(len(raw) <= MAX_DOCUMENT, "protected-worker-envelope-too-large")
    return raw


def failed_worker_diagnostic(locks, document):
    """Read bound failure metadata without granting success or cleanup authority."""
    if document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
        return None
    try:
        status, _, result = locks.request("GET", "runs/" + document["run_id"] + ".worker.json")
    except (Blocked, OSError, KeyError, TypeError, ValueError):
        return None
    if (status != 200 or type(result) is not dict or type(result.get("schema")) is not int
            or result["schema"] != 1 or result.get("status") != "reconciliation-required"
            or result.get("error_code") != "bootstrap-resource-instance-changed"
            or type(result.get("mutation_started")) is not bool
            or result.get("run_id") != document["run_id"]
            or result.get("manifest_hash") != document["manifest_hash"]
            or result.get("source_commit") != document["source"]["commit"]
            or result.get("target") != document["target"]):
        return None
    detail = safe_instance_diagnostic(result["error_code"], result.get("error_diagnostic"))
    foundation = document["deployment"].get("bootstrap_foundation")
    resources = foundation.get("resources") if type(foundation) is dict else None
    if detail is None or type(resources) is not dict or detail["resource_id"].lower() not in resources:
        return None
    return detail


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
    expected = cloud.command(["git", "show", document["source"]["commit"] + ":" + scoped_template(document)],
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
        if document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
            require(result.get("id") == run_id and run_id > 0
                    and result.get("display_title") == "factory-lifecycle [" + document["run_id"] + "]",
                    "factory-delete-run-identity-unverified")
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
    if result.get("conclusion") != "success":
        raise Blocked("scoped-github-run-failed", error_diagnostic=failed_worker_diagnostic(locks, document))
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
    expected = cloud.command(["git", "show", document["source"]["commit"] + ":" + scoped_template(document)],
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
        if document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
            require(result.get("id") == run["id"] and result.get("pipeline", {}).get("id") == pipeline,
                    "factory-delete-run-identity-unverified")
        require(result.get("resources", {}).get("repositories", {}).get("self", {}).get("version") == route["commit"],
                "scoped-ado-run-commit-mismatch")
        if result.get("state") == "completed":
            receipt["remote_terminal"] = True
            if result.get("result") != "succeeded":
                raise Blocked("scoped-ado-run-failed", error_diagnostic=failed_worker_diagnostic(locks, document))
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
    if not path.exists():
        try:
            os.link(staged, path)
            staged.unlink()
            return
        except FileExistsError:
            pass
        except OSError:
            # Filesystems without hard-link support use the replace path below.
            pass
    for attempt in range(RECEIPT_REPLACE_ATTEMPTS):
        try:
            os.replace(staged, path)
            return
        except PermissionError:
            if attempt == RECEIPT_REPLACE_ATTEMPTS - 1:
                raise Blocked("receipt-atomic-replace-failed") from None
            time.sleep(RECEIPT_REPLACE_RETRY_SECONDS)


class _RepositoryDeletionMember(RepositoryCoordination):
    def assert_held(self):
        self.cohort.assert_held()

    def claim_run(self):
        self.cohort.claim_runs()
        self.authorize(self.document)


class _RepositoryDeletionCohort:
    """One Git CAS reserves the entire cohort, including its logical identities.

    These reservations have no expiry. A fresh private-repository/state read is
    the renewal observation; uncertain writes poison the shared store until an
    operator reconciles it. Never acquire independent per-child reservations.
    """

    def __init__(self, members):
        self.members = members
        self.held, self.active = {}, None
        self.claimed, self.closed = False, False
        self.frozen = [canonical(member.document) for member in members]
        first = members[0]
        self.store = first.store
        self.cohort_hash = digest(sorted(member.document["manifest_hash"] for member in members))
        self.record = "cohorts/" + self.cohort_hash + ".json"
        for member in members:
            require(all(member.settings.get(key) == first.settings.get(key) for key in (
                "provider", "coordination_mode", "repository", "state_ref", "coordination_hash", "revision"))
                and all(member.document["route"].get(key) == first.document["route"].get(key)
                        for key in ("kind", "repository", "writer_id", "shared_remote")),
                "single-writer-cohort-authority-mismatch")
            member.cohort, member.store = self, self.store

    def _state(self):
        require(not self.store.write_failed, "single-writer-write-reconciliation-required")
        for member, frozen in zip(self.members, self.frozen):
            require(canonical(member.document) == frozen, "claimed-manifest-changed")
        head, value = self.members[0].state()
        for member in self.members[1:]:
            BlobLocks.verify_enrollment_document(member, value["enrollment"], "aifactory-single-writer-v1",
                                                "repository-exclusive-writer")
        self.observed_head = head
        return head, value

    def _active(self, value):
        require(self.held and self.active is not None and value["active"] == self.active,
                "single-writer-active-claim-changed")
        for member in self.members:
            expected = {scope.lower(): self.held[scope.lower()] for scope in
                        member.settings["scopes"] + member.settings["common_dependencies"]}
            require(member.held == expected, "single-writer-cohort-context-changed")

    def acquire(self):
        for member in self.members:
            validate_manifest(member.document)
        head, value = self._state()
        require(value["active"] is None, "single-writer-repository-active-claim")
        require(self.record not in value["records"] and not any(
            key.startswith("runs/" + member.document["run_id"] + ".")
            for member in self.members for key in value["records"]), "single-writer-run-already-submitted")
        identifier = str(uuid4())
        scopes = {scope.lower() for member in self.members for scope in
                  member.settings["scopes"] + member.settings["common_dependencies"]}
        logical = {"factory/" + member.document["target"]["factory_id"] for member in self.members}
        logical.update("scaleset/" + member.document["target"]["factory_id"] + "/" +
                       member.document["target"]["scaleset_id"] for member in self.members)
        self.held = {scope: identifier for scope in sorted(scopes)}
        active = {"kind": "deletion-cohort", "claim_id": identifier, "cohort_hash": self.cohort_hash,
                  "revision": self.members[0].settings["revision"],
                  "coordination_hash": self.members[0].settings["coordination_hash"],
                  "context": {scope: identifier for scope in sorted(scopes | logical)},
                  "manifests": sorted(member.document["manifest_hash"] for member in self.members)}
        self.active = {**active, "owner_hash": digest(active)}
        for member in self.members:
            member.held = {scope.lower(): identifier for scope in
                           member.settings["scopes"] + member.settings["common_dependencies"]}
        # Record attempted ownership before the request: a lost response can
        # still have installed every reservation, so cleanup must fail closed.
        self.store.update(head, value, active=self.active)
        self.assert_held()

    def assert_held(self):
        _, value = self._state()
        self._active(value)

    def claim_runs(self):
        if self.claimed:
            return
        head, value = self._state()
        self._active(value)
        proofs = []
        for member in self.members:
            document = member.document
            validate_manifest(document)
            proof = {"schema": 1, "claim_id": str(uuid4()), "run_id": document["run_id"],
                     "manifest_hash": document["manifest_hash"], "source": document["source"],
                     "accepted_at": utc_now(), "lease_context_hash": digest(member.held)}
            name = "runs/" + document["run_id"]
            require(name + ".json" not in value["records"] and name + ".claim.json" not in value["records"],
                    "single-writer-run-already-submitted")
            value["records"][name + ".claim.json"] = proof
            value["records"][name + ".json"] = {
                "schema": 1, "run_id": document["run_id"], "state": "claimed",
                "manifest_hash": document["manifest_hash"], "execution_claim": proof}
            proofs.append(proof)
        self.store.replace(head, value)
        self.claimed = True
        for member, proof in zip(self.members, proofs):
            member.execution_claim = _ExecutionClaim(member.document, proof)

    @staticmethod
    def _receipt_content(receipt):
        return {key: value for key, value in receipt.items()
                if key not in ("updated_at", "locks_retained", "lock_retained")}

    def _receipts(self, value, receipts, aggregate):
        for member, receipt in zip(self.members, receipts):
            if member.execution_claim is not None:
                receipt["execution_claim"] = json.loads(member.execution_claim.proof)
            name = "runs/" + member.document["run_id"] + ".json"
            previous = value["records"].get(name, {})
            require(receipt.get("run_id") == member.document["run_id"]
                    and receipt.get("manifest_hash") == member.document["manifest_hash"]
                    and receipt.get("target") == member.document["target"]
                    and receipt.get("source_commit") == member.document["source"]["commit"]
                    and receipt.get("cohort_hash") == self.cohort_hash,
                    "single-writer-record-binding-mismatch")
            if previous.get("status") in ("succeeded", "blocked", "reconciliation-required"):
                require(self._receipt_content(previous) == self._receipt_content(receipt),
                        "single-writer-terminal-record-immutable")
            value["records"][name] = json.loads(canonical(receipt))
        value["records"][self.record] = json.loads(canonical(aggregate))

    def persist(self, receipts, aggregate):
        if self.closed or not self.claimed:
            return
        head, value = self._state()
        self._active(value)
        self._receipts(value, receipts, aggregate)
        self.store.replace(head, value)

    def release(self):
        if not self.held:
            return
        head, value = self._state()
        self._active(value)
        aggregate = value["records"].get(self.record, {})
        first = self.members[0].document
        require(self.claimed and aggregate.get("status") == "succeeded"
                and aggregate.get("cohort_hash") == self.cohort_hash
                and aggregate.get("factory_id") == first["target"]["factory_id"]
                and aggregate.get("source_commit") == first["source"]["commit"]
                and aggregate.get("source_ref") == first["source"]["ref"]
                and len(aggregate.get("children", [])) == len(self.members),
                "single-writer-claim-retained-reconciliation-required")
        for member, child in zip(self.members, aggregate["children"]):
            document = member.document
            name = "runs/" + document["run_id"]
            receipt = value["records"].get(name + ".json", {})
            expected = {row["id"].lower() for row in document["deletion"]["resource_groups"] +
                        document["deletion"]["resources"]}
            deleted = receipt.get("deleted_resources", [])
            require(receipt.get("status") == "succeeded" and receipt.get("operation") == "delete"
                    and receipt == child and receipt.get("run_id") == document["run_id"]
                    and receipt.get("manifest_revision") == document["manifest_revision"]
                    and receipt.get("manifest_hash") == document["manifest_hash"]
                    and receipt.get("target") == document["target"]
                    and receipt.get("source_commit") == document["source"]["commit"]
                    and receipt.get("source_ref") == document["source"]["ref"]
                    and receipt.get("cohort_hash") == self.cohort_hash
                    and receipt.get("execution_claim") == json.loads(member.execution_claim.proof)
                    and value["records"].get(name + ".claim.json") == receipt["execution_claim"]
                    and not any(key.startswith("pending_") for key in receipt)
                    and len(deleted) == len(expected) and {key.lower() for key in deleted} == expected,
                    "single-writer-deletion-receipt-incomplete")
            member.cloud.verify_identity()
            for row in document["deletion"]["resource_groups"] + document["deletion"]["resources"]:
                status, _, _ = member.cloud.arm("GET", row["id"], row.get("api_version", RG_API),
                                               allowed=(200, 404))
                require(status == 404, "single-writer-terminal-deletion-unverified")
        # Compare-and-swap against the same observed head after final absence
        # checks. No worker receipt exists for local ARM deletion.
        for member in self.members:
            receipt = value["records"]["runs/" + member.document["run_id"] + ".json"]
            receipt.update(lock_retained=False, locks_retained=[])
        aggregate.update(lock_retained=False, locks_retained=[])
        for receipt in aggregate["children"]:
            receipt.update(lock_retained=False, locks_retained=[])
        value["active"] = None
        self.store.replace(head, value)
        self._close()

    def abort(self, receipts, aggregate):
        if not self.held:
            return
        head, value = self._state()
        self._active(value)
        require(not any(receipt.get("mutation_started") for receipt in receipts),
                "single-writer-claim-retained-reconciliation-required")
        for receipt in receipts:
            receipt.update(lock_retained=False, locks_retained=[])
        aggregate.update(lock_retained=False, locks_retained=[])
        self._receipts(value, receipts, aggregate)
        value["active"] = None
        self.store.replace(head, value)
        self._close()

    def _close(self):
        self.closed = True
        self.held.clear()
        for member in self.members:
            member.held.clear()
            member.closed = True


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


def execute_cohort(documents, source_root, execution_root, receipt_path, cloud_factory=Cloud, lock_factory=None):
    """Accept all factory children under the full physical union before deleting."""
    if isinstance(documents, list) and documents and any(
            document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1" for document in documents):
        return execute_factory_deletion_cohort(
            documents, source_root, execution_root, receipt_path, cloud_factory, lock_factory)
    require(isinstance(documents, list) and documents, "nonempty-delete-cohort-required")
    documents = json.loads(canonical(documents))
    selective = all(document.get("deletion_scope", {}).get("contract") == SELECTIVE_PROJECT_DELETE for document in documents)
    for document in documents:
        validate_manifest(document)
        require(document["operation"] == "delete" and (selective or
                document["deletion"].get("inventory_mode") == "arm-provider-closure-v1"
                and all(row["delete"] for row in document["deletion"]["resource_groups"] +
                        document["deletion"]["resources"])), "cohort-whole-owned-groups-required")
    first = documents[0]
    repository_cohort = single_writer(first)
    require(all(single_writer(document) == repository_cohort for document in documents),
            "cohort-coordination-mode-mismatch")
    if selective:
        require(all(document["reviewed_scope"] == first["reviewed_scope"]
                    and document["deletion_scope"]["options"] == first["deletion_scope"]["options"]
                    and document["deletion_scope"]["project_id"] == first["deletion_scope"]["project_id"]
                    and document["deletion_scope"]["project_number"] == first["deletion_scope"]["project_number"]
                    for document in documents), "cohort-project-policy-mismatch")
        require(sorted(document["target"]["environment"] for document in documents)
                == sorted(first["deletion_scope"]["options"]["environments"]),
                "cohort-project-environments-incomplete")
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
    lock_factory = lock_factory or (_RepositoryDeletionMember if repository_cohort else BlobLocks)
    members = [lock_factory(cloud, document) for cloud, document in zip(clouds, documents)]
    union = (_RepositoryDeletionCohort if repository_cohort else _CohortLeases)(members)
    aggregate = {"schema": 1, "operation": "delete-project" if selective else "delete-factory",
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
        if repository_cohort:
            union.persist(aggregate["children"], aggregate)
        for locks, receipt in zip(members, aggregate["children"]):
            if not repository_cohort and receipt["run_id"] in claimed:
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
            if selective:
                verify_project_inventory(cloud, document)
                verify_project_permissions(cloud, document["deletion"])
            else:
                verify_full_inventory(cloud, document)
                _, identity_inventory = collect_resource_closure(cloud, document["locks"]["scopes"])
                for member in documents:
                    verify_deletion_identity(member, identity_inventory)
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
            if selective:
                delete_project_resources(cloud, locks, document, receipt, persist)
            else:
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
        aggregate.update(failure_fields(error, "unexpected-runtime-failure"))
        if not repository_cohort and not claim_attempted:
            try:
                union.release()
            except (Blocked, OSError):
                aggregate["status"] = "reconciliation-required"
                aggregate["error_code"] = "lock-release-reconciliation-required"
                aggregate.pop("error_diagnostic", None)
        for receipt in aggregate["children"]:
            if receipt["status"] != "succeeded":
                receipt["status"] = aggregate["status"]
                receipt["error_code"] = aggregate["error_code"]
                if "error_diagnostic" in aggregate:
                    receipt["error_diagnostic"] = aggregate["error_diagnostic"]
        if repository_cohort and not any(row["mutation_started"] for row in aggregate["children"]):
            try:
                union.abort(aggregate["children"], aggregate)
            except BaseException:
                aggregate["status"] = "reconciliation-required"
                aggregate["error_code"] = "single-writer-claim-retained-reconciliation-required"
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


def execute(document, source_root, execution_root, receipt_path, cloud=None, lock_factory=None):
    if document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
        return execute_factory_deletion_cohort(
            [document], source_root, execution_root, receipt_path,
            cloud_factory=(lambda _: cloud) if cloud is not None else Cloud, lock_factory=lock_factory)
    document = json.loads(canonical(document))
    validate_manifest(document)
    if single_writer(document) and document["operation"] == "delete":
        execution_root, receipt_path = clean_path(execution_root), clean_path(receipt_path)
        require(not receipt_path.exists() and receipt_path.parent == execution_root, "new-isolated-receipt-required")
        aggregate_path = Path(execution_root) / (document["run_id"] + ".cohort.json")
        require(clean_path(receipt_path) != clean_path(aggregate_path), "new-isolated-receipt-required")
        result = execute_cohort([document], source_root, execution_root, aggregate_path,
                                cloud_factory=lambda frozen: cloud or Cloud(frozen), lock_factory=lock_factory)
        receipt = result["children"][0]
        if result["status"] != "succeeded":
            receipt["status"] = result["status"]
            receipt.update({key: result[key] for key in ("error_code", "error_diagnostic") if key in result})
        write_receipt(receipt_path, receipt)
        return receipt
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
    locks = (lock_factory or coordination)(cloud, document)
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
            if (document["operation"] in ("create-factory", "create-scaleset")
                    or "foundry_lifecycle" in document.get("deployment", {})):
                status, _, _ = cloud.arm("GET", scope, RG_API, allowed=(200, 404))
                if status == 404:
                    require(scope in document["locks"]["scopes"], "common-dependency-does-not-exist")
                    continue
            cloud.assert_no_active_deployments(scope)
        cloud.assert_no_active_runs(locks.enrollment)
        if document["operation"] == "delete":
            if document.get("deletion_scope"):
                require(document["deletion_scope"]["options"]["environments"] == [document["target"]["environment"]],
                        "multi-environment-project-cohort-required")
                delete_project_resources(cloud, locks, document, receipt, persist)
            elif document["deletion"].get("inventory_mode") == "arm-provider-closure-v1":
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
        if "foundry_identity_stage" in document.get("deployment", {}):
            verify_foundry_identity_receipt(document, receipt.get("worker_receipt", {}))
            receipt.update(completion="identity-only", continuation_required=True)
        receipt["status"] = "succeeded"
        persist()
        locks.release()
        receipt["parent_locks_retained"] = sorted(locks.held)
        persist()
        return receipt
    except BaseException as error:
        receipt["status"] = "reconciliation-required" if receipt["mutation_started"] else "blocked"
        receipt.update(failure_fields(error, "unexpected-runtime-failure"))
        if not receipt["mutation_started"]:
            try:
                locks.release()
            except Blocked:
                receipt["error_code"] = "lock-release-reconciliation-required"
                receipt.pop("error_diagnostic", None)
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
        print(json.dumps({"status": "blocked", **failure_fields(error, "invalid-runtime-input")},
                         separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
