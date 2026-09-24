"""Add-only, reviewed operator enrollment for the Linux scoped lifecycle contract.

This is the canonical standard-library implementation shared by CLI and shell
callers. It never writes the consumer register or publishes a runtime binding.
Call load_request(...), plan(request), then ensure(request, plan_hash, yes=True,
acknowledge_exclusive_writer_governance=True). Cloud accepts a subprocess.run
compatible command_runner and urllib opener for offline testing.

Required non-secret options for a new binding:
  repository, ref, shared_remote (bool), writer_id, auth_namespace, runner,
  resource_group_ids (exact writable RG ARM IDs), common_dependency_ids ([]),
  deployment_roles ([{scope: RG ID, role_definition_id: role GUID or ARM ID}]).
  ado_tenant_id is additionally required for ADO; it is NOT the target tenant.
  ADO authentication selects an enabled cached CLI account in that tenant without
  changing the default subscription. Multiple subscriptions for one identity are
  supported; missing or ambiguous identities require explicit account setup.
Existing binding values may supply route/scopes, but are never overwritten.
runner is the lifecycle hosted/self-hosted Linux object, not the bootstrap VM.
GitHub environments must be pre-provisioned. GitHub's environment PUT is an
upsert and does not support conditional creation; even GET-then-PUT can replace
concurrently created protection rules. This helper never calls that PUT. It
reuses environments unchanged and creates only absent OIDC variables with POST;
duplicate/conflicting variable creation fails without updating the variable.

ARM resource-group, user-assigned identity, federated credential, storage-account
and role-assignment provisioning uses the documented idempotent create-or-update
PUT contracts. Those endpoints are create-or-update, not atomic create-only, so
missing objects are executable plan actions (not blockers) and are written only
under an explicit serialized-provisioning acknowledgment
(acknowledge_exclusive_writer_governance). Every create re-reads immediately
before the PUT, never overwrites an object that appeared in the gap, verifies the
result with a fresh snapshot, and never issues DELETE/PATCH or an invented
If-None-Match guarantee. Known conflicts are refused with zero writes.
Private containers use the storage data-plane create API, which fails (409) if the
container already exists. The operator's blob-data role is granted before any
container or lease write; those data-plane writes retry only known RBAC
propagation (403) and never treat an authorization failure as absence.
Factory-common containers instead use reviewed ARM provisioning before container-
scoped RBAC; no account-wide data role or access to business containers is granted.
Lock/enrollment blobs use supported conditional PUTs.
New disjoint targets are allowed under shared bindings, with independent writer,
auth namespace and identity; a missing identity still needs that provisioning.
Identity options: identity_id means strictly reuse; otherwise identity_name and
identity_resource_group_id optionally override deterministic prerequisite names.
Coordination options: coordination_account_id OR coordination_resource_group_id,
container, coordination_blob. Defaults share a tenant/subscription-derived account,
factory-locks container and coordination.json across ALL factories/providers.
Explicit coordination_mode="single-writer" instead uses private provider Git
state with one repository-wide designated writer and persistent claims/receipts.
It rejects Blob options and never reads/provisions coordination storage or data
RBAC. The separate reviewed workflow grants repository state-write permission.
Exclusive governance must also cover shared-hub changes from other repositories;
this mode provides no global exclusion. See factory_lifecycle_contract.txt.
Planned new accounts require public_network_access = Enabled or Disabled. Reuse never
changes networking or security policies. Disabled needs existing private routing;
this helper does not deploy private endpoints or firewall exceptions.
Explicit coordination_storage_mode = factory-common requires coordination_account_id
from the caller's authoritative frozen common deployment plan (the salted common
name is never reconstructed here). It defaults to private factorymeta, preserves
known enrollment coordinates, and requires ADLS Gen2/HNS. It never touches lake3.
Missing accounts additionally require coordination_account_creation: the reviewed
canonical ARM account PUT body (location, kind, sku, properties, optional tags and
identity), with HNS and publicNetworkAccess Disabled. No fallback account is made.
Private routing/DNS and Entra data access must work before enrollment can complete;
provision those separately and replan after a blocked first private creation.
Existing shared-key-enabled common accounts are reused unchanged, using only Entra
Bearer tokens. Governance explicitly trusts account/key administrators: they can
bypass or destroy coordination. Leases are not a security boundary against them.
The common account, metadata container and their RG must be retained during normal
factory deletion; plan/result lifecycle_protection identifies that deletion boundary.
Missing RGs require create_resource_group_ids plus approved_group_creation_scope
= /subscriptions/<selected-subscription>. Existing unowned RGs remain blockers.

The returned binding_candidate is the API's closed RuntimeBinding object, NOT an
API request envelope. Publish only through catalog prepare/confirm configure-binding.
Refresh plans after any state change; failed/uncertain writes are not rolled back.
"""

from __future__ import annotations

import argparse
import base64
import copy
import fnmatch
import hashlib
import importlib.util
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from email.utils import formatdate
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5


ARM = "https://management.azure.com"
STORAGE = "https://storage.azure.com/"
ADO_AUDIENCE = "499b84ac-1321-427f-aa17-267ca6975798"
DATA_ROLE = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
RG_API = "2021-04-01"
IDENTITY_API = "2023-01-31"
STORAGE_API = "2023-05-01"
ROLE_API = "2022-04-01"
MAX_BYTES = 8 * 1024 * 1024
NAME = r"[A-Za-z0-9_.-]{1,128}"
RG = re.compile(r"/subscriptions/([a-f0-9-]{36})/resourcegroups/([A-Za-z0-9_.()-]{1,90})", re.I)
OPTIONS = {
    "repository", "ref", "writer_id", "auth_namespace", "runner", "shared_remote",
    "identity_id", "identity_name", "identity_resource_group_id", "coordination_account_id",
    "coordination_resource_group_id", "container", "coordination_blob", "public_network_access",
    "resource_group_ids", "common_dependency_ids", "deployment_roles",
    "create_resource_group_ids", "approved_group_creation_scope", "ado_tenant_id",
    "coordination_storage_mode", "coordination_account_creation",
    "coordination_mode",
}


def _single_writer_module():
    spec = importlib.util.spec_from_file_location("provider_repository_state", Path(__file__).with_name("provider_repository_state.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _single_writer(request):
    return request.get("coordination_mode") == "single-writer"


class EnrollmentError(Exception):
    """Only bounded, non-secret codes cross the command/API boundary."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def require(value, code):
    if not value:
        raise EnrollmentError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate-json-key")
            result[key] = value
        return result
    try:
        require(len(raw) <= MAX_BYTES, "document-too-large")
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(EnrollmentError("nonfinite-json")))
    except (ValueError, TypeError, UnicodeError):
        raise EnrollmentError("invalid-json") from None


def guid(value):
    try:
        require(isinstance(value, str) and bool(UUID(value).int), "invalid-guid")
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise EnrollmentError("invalid-guid") from None


def rg_id(value):
    require(isinstance(value, str), "invalid-resource-group-id")
    match = RG.fullmatch(value)
    require(match and match[2] not in (".", ".."), "invalid-resource-group-id")
    guid(match[1])
    return value.lower()


def resource_id(value, kind):
    require(isinstance(value, str), "invalid-resource-id")
    match = re.fullmatch(r"(.+)/providers/" + re.escape(kind) + r"/([A-Za-z0-9_-]{3,128})", value, re.I)
    require(match, "invalid-resource-id")
    rg_id(match[1])
    return value.lower()


def lock_blob(scope):
    return "locks/" + hashlib.sha256(rg_id(scope).encode("utf-8")).hexdigest() + ".lock"


def default_coordination(subscription, tenant):
    seed = guid(subscription) + ":" + guid(tenant)
    return {"account_name": "aflock" + hashlib.sha256(seed.encode()).hexdigest()[:18],
            "resource_group_id": f"/subscriptions/{guid(subscription)}/resourcegroups/aifactory-enrollment",
            "container": "factory-locks", "coordination_blob": "coordination.json"}


def _common_mode(request):
    return request.get("coordination_storage_mode") == "factory-common"


def _container_id(request):
    return request["account_id"] + "/blobservices/default/containers/" + request["coordinates"]["container"]


def _common_account_creation(body, region, public):
    require(isinstance(body, dict) and set(body) <= {"location", "kind", "sku", "properties", "tags", "identity"},
            "invalid-common-account-creation")
    require(body.get("location") == region and body.get("kind") == "StorageV2"
            and isinstance(body.get("sku"), dict) and set(body["sku"]) == {"name"}
            and body["sku"]["name"] in ("Standard_LRS", "Standard_GRS", "Standard_ZRS",
                                      "Standard_GZRS", "Standard_RAGRS", "Standard_RAGZRS"),
            "common-account-canonical-location-kind-sku-required")
    props = body.get("properties")
    require(isinstance(props, dict) and set(props) <= {
        "isHnsEnabled", "allowSharedKeyAccess", "allowBlobPublicAccess", "supportsHttpsTrafficOnly",
        "minimumTlsVersion", "defaultToOAuthAuthentication", "publicNetworkAccess", "networkAcls",
        "accessTier", "encryption", "keyPolicy", "largeFileSharesState"},
        "invalid-common-account-creation-properties")
    require(props.get("isHnsEnabled") is True and type(props.get("allowSharedKeyAccess")) is bool
            and props.get("allowBlobPublicAccess") is False and props.get("supportsHttpsTrafficOnly") is True
            and props.get("minimumTlsVersion") == "TLS1_2" and props.get("accessTier") == "Hot",
            "common-account-canonical-security-policy-required")
    require(public == "Disabled" and props.get("publicNetworkAccess") == "Disabled",
            "common-account-private-network-policy-required")
    network = props.get("networkAcls")
    require(isinstance(network, dict) and network.get("defaultAction") == "Deny"
            and network.get("bypass") in ("None", "AzureServices"),
            "common-account-private-network-policy-required")
    return copy.deepcopy(body)


def resolve_factory_common_storage(common_resource_group_id, parameters, *, tenant_id,
                                   naming_identity=None, naming_identity_id=None,
                                   project_naming=None, evaluated_account_id=None):
    """Pure projection of common13/dataLake naming and the non-CMK account body.

    parameters is a frozen subset of 13-rgLevel inputs, NOT arbitrary UI defaults:
    location, locationSuffix, env (dev/test/prod), commonLakeNamePrefixMax8chars,
    commonResourceSuffix, tags; optional commonResourceAbbreviation, skuNameStorage,
    IPwhiteList, cmk. Defaults below are the canonical Bicep defaults.

    Evidence is either the exact ARM-read canonical CMK/project UAMI, or an account
    ID evaluated by ARM in the caller's trusted frozen common plan. No random salt
    is accepted/generated and uniqueString is never reimplemented. A project UAMI
    also requires project_naming: resource_group_id, projectNumber, resourceSuffix,
    keepMIandKVsuffixAs001 (optional, default false), from that project's plan.
    The caller must bind this identity/plan evidence to the selected factory and
    reject incomplete/ambiguous inventory; this pure function does no cloud reads.

    When no such evidence exists, first review narrowly scoped common-RG/naming
    prerequisites or a native ARM what-if evaluation; never run all common13
    unlocked merely to discover the name. CMK requires its separate reviewed
    identity/key-access prerequisites and an explicit canonical creation body.
    Network provisioning is separate: exact VNet/subnet, blob private endpoint,
    private DNS/zone link (or approved hub DNS), and operator/runner routing must
    exist before data-plane enrollment completes. No lake3 or network writes here.
    """
    group = rg_id(common_resource_group_id)
    tenant = guid(tenant_id)
    required = {"location", "locationSuffix", "env", "commonLakeNamePrefixMax8chars",
                "commonResourceSuffix", "tags"}
    require(isinstance(parameters, dict) and required <= set(parameters)
            and set(parameters) <= required | {
                "commonResourceAbbreviation", "skuNameStorage", "IPwhiteList", "cmk"},
            "canonical-common-parameters-required")
    env, suffix = parameters["env"], parameters["commonResourceSuffix"]
    prefix = parameters["commonLakeNamePrefixMax8chars"]
    abbreviation = parameters.get("commonResourceAbbreviation", "esml")
    require(env in ("dev", "test", "prod") and isinstance(suffix, str)
            and re.fullmatch(r"(?:-[0-9]{3})?", suffix)
            and isinstance(prefix, str) and re.fullmatch(r"[a-z0-9]{1,8}", prefix)
            and isinstance(abbreviation, str) and re.fullmatch(r"[a-z0-9]{1,12}", abbreviation)
            and re.fullmatch(r"[a-z0-9]{1,12}", str(parameters["locationSuffix"]))
            and re.fullmatch(r"[a-z0-9]+", str(parameters["location"])),
            "invalid-canonical-common-naming-parameters")
    require(isinstance(parameters["tags"], dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in parameters["tags"].items()),
            "canonical-common-tags-required")
    require(parameters.get("cmk", False) is False,
            "common-cmk-identity-key-access-and-reviewed-creation-body-required")
    salt = None
    if naming_identity is not None:
        expected = resource_id(naming_identity_id, "Microsoft.ManagedIdentity/userAssignedIdentities")
        require(isinstance(naming_identity, dict)
                and str(naming_identity.get("id", "")).lower() == expected
                and expected.split("/")[2] == group.split("/")[2], "canonical-naming-identity-id-conflict")
        props = naming_identity.get("properties", {})
        require(guid(props.get("tenantId")) == tenant
                and guid(props.get("principalId")) != guid(props.get("clientId")),
                "canonical-naming-identity-tenant-or-identifiers-conflict")
        name = expected.rsplit("/", 1)[1]
        if project_naming is None:
            require(expected.split("/providers/")[0] == group, "canonical-naming-identity-scope-conflict")
            pattern = "id-cmn-cmk-" + env + r"-([a-z0-9]{5})" + re.escape(suffix)
        else:
            require(isinstance(project_naming, dict)
                    and {"resource_group_id", "projectNumber", "resourceSuffix"} <= set(project_naming)
                    and set(project_naming) <= {
                        "resource_group_id", "projectNumber", "resourceSuffix", "keepMIandKVsuffixAs001"},
                    "canonical-project-naming-required")
            require(expected.split("/providers/")[0] == rg_id(project_naming["resource_group_id"]),
                    "canonical-naming-identity-scope-conflict")
            number, resource_suffix = project_naming["projectNumber"], project_naming["resourceSuffix"]
            keep = project_naming.get("keepMIandKVsuffixAs001", False)
            require(re.fullmatch(r"[0-9]{3}", str(number))
                    and re.fullmatch(r"-[0-9]{3}", str(resource_suffix)) and type(keep) is bool,
                    "canonical-project-naming-required")
            mi_suffix = "-001" if keep else resource_suffix
            pattern = (r"mi-(?:aca-)?prj" + number + "-" + parameters["locationSuffix"] + "-" + env
                       + r"-([a-z0-9]{5})[a-z0-9_-]{10}" + re.escape(mi_suffix))
        match = re.fullmatch(pattern, name)
        require(match, "canonical-naming-identity-pattern-conflict")
        salt = match[1]
    require(naming_identity is not None or naming_identity_id is None, "canonical-naming-identity-read-required")
    if evaluated_account_id is not None:
        evaluated = resource_id(evaluated_account_id, "Microsoft.Storage/storageAccounts")
        require(evaluated.split("/providers/")[0] == group, "canonical-common-account-scope-conflict")
        match = re.fullmatch(re.escape(prefix) + r"([a-z0-9]{5})"
                             + re.escape(abbreviation + suffix.replace("-", "") + env), evaluated.rsplit("/", 1)[1])
        require(match and (salt is None or salt == match[1]), "canonical-common-naming-evidence-conflict")
        salt = match[1]
    require(salt is not None, "canonical-common-naming-evidence-required")
    name = prefix + salt + abbreviation + suffix.replace("-", "") + env
    require(re.fullmatch(r"[a-z0-9]{3,24}", name), "invalid-canonical-common-account-name")
    whitelist = parameters.get("IPwhiteList", "")
    require(isinstance(whitelist, str), "invalid-canonical-common-ip-whitelist")
    ips = [] if whitelist in ("", "null") else whitelist.replace("\\s+", "").split(",")
    try:
        for ip in ips:
            ipaddress.IPv4Network(ip, strict=False)
    except (ValueError, TypeError):
        raise EnrollmentError("invalid-canonical-common-ip-whitelist") from None
    body = {
        "location": parameters["location"], "kind": "StorageV2",
        "sku": {"name": parameters.get("skuNameStorage", "Standard_ZRS")},
        "tags": copy.deepcopy(parameters["tags"]), "identity": {"type": "None"},
        "properties": {
            "isHnsEnabled": True, "allowBlobPublicAccess": False, "allowSharedKeyAccess": True,
            "publicNetworkAccess": "Disabled", "accessTier": "Hot", "minimumTlsVersion": "TLS1_2",
            "supportsHttpsTrafficOnly": True, "largeFileSharesState": "Disabled",
            "keyPolicy": {"keyExpirationPeriodInDays": 14},
            "encryption": {"keySource": "Microsoft.Storage", "identity": None, "keyvaultproperties": None,
                           "services": {service: {"enabled": True, "keyType": key_type}
                                        for service, key_type in (("blob", "Account"), ("file", "Account"),
                                                                  ("queue", "Service"), ("table", "Service"))}},
            "networkAcls": {"defaultAction": "Deny", "bypass": "AzureServices",
                            "ipRules": [{"action": "Allow", "value": ip} for ip in ips], "virtualNetworkRules": []},
        },
    }
    _common_account_creation(body, parameters["location"], "Disabled")
    return {"coordination_storage_mode": "factory-common",
            "coordination_account_id": group + "/providers/microsoft.storage/storageaccounts/" + name,
            "coordination_account_creation": body, "public_network_access": "Disabled"}


def validate_runner(runner, provider):
    require(isinstance(runner, dict) and runner.get("os") == "linux", "linux-scoped-runner-required")
    if runner.get("kind") == "hosted":
        require(set(runner) == {"kind", "os", "image"} and runner["image"] in (
            "ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04"), "invalid-hosted-runner")
    elif provider == "gha":
        labels = runner.get("labels")
        require(set(runner) == {"kind", "os", "labels"} and runner.get("kind") == "self-hosted"
                and isinstance(labels, list) and 2 <= len(labels) <= 16
                and all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", x) for x in labels)
                and {"self-hosted", "linux"} <= {x.lower() for x in labels}, "invalid-github-runner")
    else:
        require(set(runner) <= {"kind", "os", "pool", "agent_name"} and runner.get("kind") == "self-hosted"
                and re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", str(runner.get("pool", "")))
                and ("agent_name" not in runner or re.fullmatch(r"[A-Za-z0-9_. -]{1,128}", runner["agent_name"])),
                "invalid-ado-runner")


def _validate_binding(binding):
    allowed = {"contract_version", "orchestrator", "writer_id", "repository", "ref", "shared_remote",
               "auth_namespace", "deployment_object_id", "runner", "locks", "targets"}
    require(set(binding) <= allowed and binding.get("contract_version") == 1
            and binding.get("orchestrator") in ("gha", "ado")
            and isinstance(binding.get("targets"), list) and binding["targets"]
            and isinstance(binding.get("locks"), dict), "invalid-existing-binding")
    single = binding["locks"].get("coordination_mode") == "single-writer"
    require(set(binding["locks"]) == ({"provider", "coordination_mode", "repository", "state_ref", "coordination_hash", "revision"}
            if single else {"account_url", "container", "coordination_blob", "coordination_hash", "revision"}),
            "invalid-existing-binding")
    require((all(binding["locks"].get(k) == v for k, v in _single_writer_module().coordinates(binding["repository"]).items())
             if single else re.fullmatch(r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net", str(binding["locks"]["account_url"])))
            and re.fullmatch(r"[a-f0-9]{64}", str(binding["locks"]["coordination_hash"]))
            and type(binding["locks"]["revision"]) is int and binding["locks"]["revision"] >= 1,
            "invalid-existing-binding")
    require(type(binding.get("shared_remote")) is bool and isinstance(binding.get("repository"), str)
            and isinstance(binding.get("ref"), str) and re.fullmatch(NAME, str(binding.get("writer_id", ""))),
            "invalid-existing-binding")
    if binding.get("runner") is not None:
        validate_runner(binding["runner"], binding["orchestrator"])
    if binding.get("deployment_object_id") is not None:
        guid(binding["deployment_object_id"])
    require(len({item.get("scale_set_id") for item in binding["targets"] if isinstance(item, dict)})
            == len(binding["targets"]), "ambiguous-existing-binding")
    for item in binding["targets"]:
        require(isinstance(item, dict) and set(item) <= {
            "scale_set_id", "resource_group_ids", "common_dependency_ids", "execution"},
            "invalid-existing-binding-target")
        guid(item.get("scale_set_id"))
        require(isinstance(item.get("resource_group_ids"), list) and item["resource_group_ids"]
                and isinstance(item.get("common_dependency_ids", []), list), "invalid-existing-binding-target")
        if item.get("execution"):
            require(set(item["execution"]) == {"writer_id", "auth_namespace", "deployment_object_id", "runner"},
                    "invalid-existing-binding-execution")
            guid(item["execution"]["deployment_object_id"])
            validate_runner(item["execution"]["runner"], binding["orchestrator"])


def _one(rows, field, value, code):
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), code)
    matches = [row for row in rows if row.get(field) == value]
    require(len(matches) == 1, code)
    return matches[0]


def load_request(consumer_root, factory_id, scale_set_id, environment, options):
    """Read a schema-2 consumer register; no local or cloud mutation.

    consumer_root is the repository containing azurefactory/register.json.
    options is a closed non-secret JSON object (see OPTIONS and CLI --help).
    """
    root = Path(consumer_root).resolve()
    path = root / "azurefactory" / "register.json"
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES, "consumer-register-required")
    require(path.resolve().is_relative_to(root), "consumer-register-escapes-root")
    raw = path.read_bytes()
    document = parse_json(raw)
    require(isinstance(document, dict) and document.get("schema_version") == 2, "consumer-schema-2-required")
    require(isinstance(options, dict) and set(options) <= OPTIONS, "unknown-enrollment-option")
    require(environment in ("dev", "stage", "prod"), "explicit-environment-required")
    factory = _one(document.get("factories"), "id", guid(factory_id), "exact-registered-factory-required")
    require(factory.get("kind", "ai") == "ai", "unsupported-factory-type")
    scale = _one(factory.get("scale_sets"), "id", guid(scale_set_id), "exact-registered-scaleset-required")
    require(scale.get("environment") == environment, "registered-environment-mismatch")
    tenant, subscription = guid(scale.get("tenant_id")), guid(scale.get("subscription_id"))
    provider = scale.get("orchestrator")
    require(provider in ("gha", "ado"), "registered-orchestrator-required")
    require(re.fullmatch(r"[a-z][a-z0-9-]{1,19}", str(factory.get("prefix", "")))
            and re.fullmatch(r"[a-z0-9]+", str(factory.get("region", "")))
            and re.fullmatch(r"(?!000)[0-9]{3}", str(scale.get("suffix", ""))), "invalid-registered-target")
    target = {"factory_id": factory["id"], "scaleset_id": scale["id"], "environment": environment,
              "tenant_id": tenant, "subscription_id": subscription, "prefix": factory["prefix"],
              "region": factory["region"], "suffix": scale["suffix"]}
    bindings = document.get("bindings")
    require(isinstance(bindings, dict), "binding-inventory-required")
    inventory = []
    for owner, routes in bindings.items():
        require(isinstance(routes, dict), "invalid-existing-binding")
        for kind, binding in routes.items():
            require(kind in ("ado", "gha") and isinstance(binding, dict), "invalid-existing-binding")
            _validate_binding(binding)
            require(binding["orchestrator"] == kind, "invalid-existing-binding")
            inventory.append({"factory_id": owner, "provider": kind, "binding": copy.deepcopy(binding)})
    old = bindings.get(factory["id"], {}).get(provider)
    old_target = None
    if old:
        matches = [x for x in old["targets"] if x.get("scale_set_id") == scale["id"]]
        require(len(matches) <= 1, "ambiguous-existing-binding")
        old_target = matches[0] if matches else None
    execution = (old_target or {}).get("execution") or old or {}
    route = {"kind": provider}
    for key in ("repository", "ref", "shared_remote"):
        route[key] = options.get(key, (old or {}).get(key))
    for key in ("writer_id", "auth_namespace", "runner"):
        route[key] = options.get(key, execution.get(key))
    pattern = (r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" if provider == "gha" else
               r"https://dev\.azure\.com/[A-Za-z0-9_.%-]+/[A-Za-z0-9_.%-]+/_git/[A-Za-z0-9_.%-]+")
    require(isinstance(route["repository"], str) and re.fullmatch(pattern, route["repository"])
            and all(x not in (".", "..") for x in unquote(route["repository"]).split("/")),
            "explicit-safe-repository-required")
    require(isinstance(route["ref"], str) and re.fullmatch(r"refs/(heads|tags)/[A-Za-z0-9_./-]+", route["ref"])
            and ".." not in route["ref"], "explicit-consumer-ref-required")
    require(type(route["shared_remote"]) is bool, "explicit-shared-remote-required")
    require(all(isinstance(route[key], str) and re.fullmatch(NAME, route[key])
                for key in ("writer_id", "auth_namespace")), "explicit-writer-and-auth-namespace-required")
    validate_runner(route["runner"], provider)
    scopes = sorted(rg_id(x) for x in options.get("resource_group_ids", (old_target or {}).get("resource_group_ids", [])))
    dependencies = sorted(rg_id(x) for x in options.get("common_dependency_ids", (old_target or {}).get("common_dependency_ids", [])))
    require(1 <= len(scopes) <= 24 and len(dependencies) <= 24
            and len(set(scopes + dependencies)) == len(scopes + dependencies), "exact-disjoint-physical-scopes-required")
    require(all(x.split("/")[2] == subscription for x in scopes), "writable-scope-subscription-mismatch")
    mode = options.get("coordination_mode", "blob")
    require(mode in ("blob", "single-writer"), "invalid-coordination-mode")
    if mode == "single-writer":
        forbidden = {"coordination_storage_mode", "coordination_account_creation", "coordination_account_id",
                     "coordination_resource_group_id", "container", "coordination_blob", "public_network_access"}
        require(not forbidden.intersection(options), "single-writer-blob-options-forbidden")
        coordinates = _single_writer_module().coordinates(route["repository"])
        for item in inventory:
            binding = item["binding"]
            bound = {rg_id(x) for t in binding["targets"]
                     for x in t.get("resource_group_ids", []) + t.get("common_dependency_ids", [])}
            if bound.intersection(scopes + dependencies):
                require(all(binding["locks"].get(k) == v for k, v in coordinates.items()),
                        "overlapping-coordination-namespaces-conflict")
        if old:
            require(all(old["locks"].get(k) == v for k, v in coordinates.items()),
                    "existing-binding-coordinates-conflict")
        return _single_writer_request(root, raw, target, route, scopes, dependencies, inventory, options)
    storage_mode = options.get("coordination_storage_mode", "dedicated")
    require(storage_mode in ("dedicated", "factory-common", "connectivity-hub"), "invalid-coordination-storage-mode")
    require(storage_mode == "factory-common" or "coordination_account_creation" not in options,
            "common-account-creation-requires-factory-common-mode")
    require(storage_mode != "factory-common" or options.get("coordination_account_id"),
            "canonical-common-account-id-required")
    defaults = default_coordination(subscription, tenant)
    overlapping = []
    for item in inventory:
        binding = item["binding"]
        bound = {rg_id(x) for t in binding["targets"]
                 for x in t.get("resource_group_ids", []) + t.get("common_dependency_ids", [])}
        if bound.intersection(scopes + dependencies):
            require(binding["locks"].get("coordination_mode") != "single-writer",
                    "overlapping-coordination-namespaces-conflict")
            overlapping.append({key: binding["locks"].get(key) for key in ("account_url", "container", "coordination_blob")})
    if old:
        require(old["locks"].get("coordination_mode") != "single-writer", "existing-binding-coordinates-conflict")
        overlapping.append({key: old["locks"][key] for key in ("account_url", "container", "coordination_blob")})
    require(not overlapping or all(x == overlapping[0] for x in overlapping), "overlapping-coordination-namespaces-conflict")
    coordination_rg = rg_id(options.get("coordination_resource_group_id", defaults["resource_group_id"]))
    account_id = options.get("coordination_account_id")
    if account_id:
        account_id = resource_id(account_id, "Microsoft.Storage/storageAccounts")
        coordination_rg = account_id.split("/providers/")[0]
        require("coordination_resource_group_id" not in options
                or rg_id(options["coordination_resource_group_id"]) == coordination_rg,
                "coordination-resource-group-conflict")
    elif overlapping:
        # Exact ARM identity is required for custom coordinates; never guess an RG.
        require(overlapping[0]["account_url"] == "https://" + defaults["account_name"] + ".blob.core.windows.net",
                "existing-coordination-account-id-required")
    account_id = account_id or coordination_rg + "/providers/microsoft.storage/storageaccounts/" + defaults["account_name"]
    require(storage_mode == "connectivity-hub" or account_id.split("/")[2] == subscription, "coordination-subscription-mismatch")
    if storage_mode == "connectivity-hub":
        require(coordination_rg not in scopes and coordination_rg not in dependencies,
                "shared-hub-must-not-be-factory-owned-or-deleted")
        require(account_id.rsplit("/", 1)[1] == "afhub" + hashlib.sha256(coordination_rg.encode()).hexdigest()[:19]
                and options.get("container") == "hub-locks", "canonical-shared-hub-coordinates-required")
    account_name = account_id.rsplit("/", 1)[1]
    require(re.fullmatch(r"[a-z0-9]{3,24}", account_name), "invalid-coordination-account-name")
    coordinates = {"account_url": "https://" + account_name + ".blob.core.windows.net",
                   "container": options.get("container", overlapping[0]["container"] if overlapping else (
                       "factorymeta" if storage_mode == "factory-common" else defaults["container"])),
                   "coordination_blob": options.get("coordination_blob", overlapping[0]["coordination_blob"] if overlapping else defaults["coordination_blob"])}
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", str(coordinates["container"]))
            and "--" not in coordinates["container"], "invalid-container")
    require(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_./-]{0,255}", str(coordinates["coordination_blob"]))
            and ".." not in coordinates["coordination_blob"] and not coordinates["coordination_blob"].startswith(("locks/", "runs/")),
            "invalid-coordination-blob")
    require(not overlapping or coordinates == overlapping[0], "overlapping-coordination-namespaces-conflict")
    require(storage_mode != "factory-common" or coordinates["container"] != "lake3",
            "business-container-cannot-host-coordination")
    identity_rg = rg_id(options.get("identity_resource_group_id", coordination_rg))
    identity_id = options.get("identity_id")
    reuse_identity = bool(identity_id)
    if not identity_id:
        name = options.get("identity_name", "afwriter-" + digest(target | {"provider": provider})[:16])
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{3,128}", name), "invalid-identity-name")
        identity_id = identity_rg + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/" + name
    identity_id = resource_id(identity_id, "Microsoft.ManagedIdentity/userAssignedIdentities")
    identity_rg = identity_id.split("/providers/")[0]
    require(reuse_identity or identity_id.split("/")[2] == subscription, "identity-subscription-mismatch")
    public = options.get("public_network_access")
    require(public in (None, "Enabled", "Disabled"), "invalid-public-network-policy")
    account_creation = options.get("coordination_account_creation")
    if account_creation is not None:
        account_creation = _common_account_creation(account_creation, target["region"], public)
    creation = sorted(rg_id(x) for x in options.get("create_resource_group_ids", []))
    require(set(creation) <= set(scopes + [identity_rg, coordination_rg]), "resource-group-creation-escapes-scope")
    require(all(x.split("/")[2] == subscription for x in creation), "resource-group-creation-escapes-subscription")
    approved = options.get("approved_group_creation_scope")
    require(approved is None or approved.lower() == "/subscriptions/" + subscription, "invalid-approved-group-creation-scope")
    require(not creation or approved, "explicit-wider-group-creation-approval-required")
    roles = []
    for role in options.get("deployment_roles", []):
        require(isinstance(role, dict) and set(role) == {"scope", "role_definition_id"}, "invalid-role-grant")
        scope = rg_id(role["scope"])
        require(scope in scopes, "role-grant-escapes-explicit-writable-scope")
        definition = role["role_definition_id"]
        if re.fullmatch(r"[a-fA-F0-9-]{36}", str(definition)):
            definition = f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/{guid(definition)}"
        require(re.fullmatch(re.escape(f"/subscriptions/{subscription}") +
                             r"/providers/microsoft.authorization/roledefinitions/[a-f0-9-]{36}", definition, re.I),
                "invalid-role-definition-id")
        guid(definition.rsplit("/", 1)[1])
        roles.append({"scope": scope, "role_definition_id": definition.lower()})
    require(len({(x["scope"], x["role_definition_id"]) for x in roles}) == len(roles), "duplicate-role-grant")
    require(provider != "ado" or options.get("ado_tenant_id"), "explicit-ado-tenant-id-required")
    ado_tenant = guid(options.get("ado_tenant_id")) if provider == "ado" else None
    return {"schema": 1, "consumer_root": str(root), "consumer_hash": hashlib.sha256(raw).hexdigest(),
            "target": target, "route": route, "scopes": scopes, "common_dependencies": dependencies,
            "identity_id": identity_id, "reuse_identity": reuse_identity,
            "account_id": account_id, "coordinates": coordinates, "public_network_access": public,
            "coordination_storage_mode": storage_mode, "coordination_account_creation": account_creation,
            "create_resource_group_ids": creation, "approved_group_creation_scope": approved,
            "deployment_roles": sorted(roles, key=canonical), "ado_tenant_id": ado_tenant,
            "existing_bindings": inventory, "options": copy.deepcopy(options)}


def _single_writer_request(root, raw, target, route, scopes, dependencies, inventory, options):
    subscription = target["subscription_id"]
    identity_rg = rg_id(options.get("identity_resource_group_id", scopes[0]))
    identity_id = options.get("identity_id")
    reuse = bool(identity_id)
    if not identity_id:
        name = options.get("identity_name", "afwriter-" + digest({"repository": route["repository"], "writer": route["writer_id"]})[:16])
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{3,128}", name), "invalid-identity-name")
        identity_id = identity_rg + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/" + name
    identity_id = resource_id(identity_id, "Microsoft.ManagedIdentity/userAssignedIdentities")
    identity_rg = identity_id.split("/providers/")[0]
    require(reuse or identity_id.split("/")[2] == subscription, "identity-subscription-mismatch")
    creation = sorted(rg_id(x) for x in options.get("create_resource_group_ids", []))
    require(set(creation) <= set(scopes + [identity_rg]), "resource-group-creation-escapes-scope")
    require(all(x.split("/")[2] == subscription for x in creation), "resource-group-creation-escapes-subscription")
    approved = options.get("approved_group_creation_scope")
    require(approved is None or approved.lower() == "/subscriptions/" + subscription, "invalid-approved-group-creation-scope")
    require(not creation or approved, "explicit-wider-group-creation-approval-required")
    roles = []
    for role in options.get("deployment_roles", []):
        require(isinstance(role, dict) and set(role) == {"scope", "role_definition_id"}, "invalid-role-grant")
        scope = rg_id(role["scope"])
        require(scope in scopes, "role-grant-escapes-explicit-writable-scope")
        definition = role["role_definition_id"]
        if re.fullmatch(r"[a-fA-F0-9-]{36}", str(definition)):
            definition = f"/subscriptions/{subscription}/providers/microsoft.authorization/roledefinitions/{guid(definition)}"
        require(isinstance(definition, str) and re.fullmatch(re.escape(f"/subscriptions/{subscription}") +
                r"/providers/microsoft.authorization/roledefinitions/[a-f0-9-]{36}", definition, re.I), "invalid-role-definition-id")
        guid(definition.rsplit("/", 1)[1])
        roles.append({"scope": scope, "role_definition_id": definition.lower()})
    require(len({(x["scope"], x["role_definition_id"]) for x in roles}) == len(roles), "duplicate-role-grant")
    require(route["kind"] != "ado" or options.get("ado_tenant_id"), "explicit-ado-tenant-id-required")
    return {"schema": 1, "consumer_root": str(root), "consumer_hash": hashlib.sha256(raw).hexdigest(),
            "target": target, "route": route, "scopes": scopes, "common_dependencies": dependencies,
            "identity_id": identity_id, "reuse_identity": reuse, "coordination_mode": "single-writer",
            "coordinates": _single_writer_module().coordinates(route["repository"]),
            "create_resource_group_ids": creation, "approved_group_creation_scope": approved,
            "deployment_roles": sorted(roles, key=canonical),
            "ado_tenant_id": guid(options["ado_tenant_id"]) if route["kind"] == "ado" else None,
            "existing_bindings": inventory, "options": copy.deepcopy(options)}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise EnrollmentError("redirect-forbidden")


def _run_cli(argv, **kwargs):
    executable = shutil.which(argv[0])
    require(executable, "command-unavailable-or-failed")
    return subprocess.run([executable, *argv[1:]], **kwargs)


class Cloud:
    """Azure CLI profile and gh authentication only; never logs in or switches accounts."""

    def __init__(self, request, command_runner=None, opener=None):
        self.request_config = request
        self.command_runner = command_runner or _run_cli
        self.opener = opener or build_opener(NoRedirect())
        self.read_only = True
        self.serialized_provisioning = False
        self.tokens = {}
        self.operator_id = None

    def command(self, argv, data=None):
        try:
            result = self.command_runner(argv, input=data, capture_output=True, check=False,
                                         timeout=120, shell=False)
        except (OSError, subprocess.SubprocessError):
            raise EnrollmentError("command-unavailable-or-failed") from None
        require(result.returncode == 0, "authenticated-cli-command-failed")
        raw = result.stdout
        return raw.decode("utf-8") if isinstance(raw, bytes) else raw

    def az(self, *args):
        require(tuple(args[:2]) in (("account", "show"), ("account", "list"),
                                    ("account", "get-access-token"), ("identity", "show"))
                or tuple(args[:3]) == ("storage", "account", "check-name"),
                "unreviewed-cli-command-forbidden")
        return parse_json(self.command(["az", *args, "--only-show-errors", "--output", "json"]))

    def _ado_subscription(self, tenant):
        accounts = self.az("account", "list", "--all", "--query",
                           "[].{id:id,tenantId:tenantId,state:state,accountName:user.name}")
        require(isinstance(accounts, list) and all(isinstance(item, dict) for item in accounts),
                "ado-account-metadata-invalid")
        selected = [item for item in accounts
                    if isinstance(item.get("tenantId"), str) and item["tenantId"].lower() == tenant
                    and item.get("state") == "Enabled"]
        require(selected, "ado-tenant-account-unavailable")
        require(all(isinstance(item.get("accountName"), str) and item["accountName"].strip()
                    for item in selected), "ado-account-identity-unverified")
        require(len({item["accountName"].strip().casefold() for item in selected}) == 1,
                "ado-tenant-account-ambiguous")
        return min(guid(item.get("id")) for item in selected)

    def token(self, audience, tenant=None):
        require(not _single_writer(self.request_config) or audience != STORAGE,
                "single-writer-storage-access-forbidden")
        target = self.request_config["target"]
        tenant = tenant or target["tenant_id"]
        key = (audience, tenant)
        if key not in self.tokens:
            args = ["account", "get-access-token", "--resource", audience]
            # --tenant alone still uses the default CLI user, which may belong to
            # the separate Azure deployment tenant rather than the ADO tenant.
            subscription = self._ado_subscription(tenant) if audience == ADO_AUDIENCE else target["subscription_id"]
            args += ["--subscription", subscription]
            value = self.az(*args)
            try:
                token = value["accessToken"]
                encoded = token.split(".")[1]
                claims = parse_json(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
                require(guid(claims["tid"]) == tenant and float(claims["exp"]) > time.time()
                        and float(claims.get("nbf", 0)) <= time.time() + 60, "token-tenant-or-lifetime-mismatch")
                audiences = {audience.rstrip("/")}
                if audience == ARM + "/":
                    audiences |= {"https://management.core.windows.net", "797f4846-ba00-4fd7-ba43-dac1f8f63013"}
                if audience == ADO_AUDIENCE:
                    audiences.add("https://app.vssps.visualstudio.com")
                require(str(claims["aud"]).rstrip("/") in audiences, "token-audience-mismatch")
                oid = guid(claims["oid"])
            except (KeyError, IndexError, ValueError, TypeError):
                raise EnrollmentError("invalid-authenticated-token") from None
            if audience == ARM + "/":
                self.operator_id = oid
            self.tokens[key] = token
        return self.tokens[key]

    def http(self, method, url, audience, data=None, headers=None, tenant=None, allowed=(200,)):
        require(method in ("GET", "HEAD", "PUT", "POST"), "delete-or-replacement-forbidden")
        require(not self.read_only or method in ("GET", "HEAD"), "plan-mutation-forbidden")
        require(audience != ARM + "/" or method in ("GET", "HEAD") or self.serialized_provisioning,
                "arm-serialized-provisioning-required")
        parsed = urlsplit(url)
        expected = {"management.azure.com"} if audience == ARM + "/" else (
            {urlsplit(self.request_config["coordinates"]["account_url"]).hostname} if audience == STORAGE else {"dev.azure.com"})
        require(parsed.scheme == "https" and parsed.hostname in expected and not parsed.username
                and not parsed.password and parsed.port in (None, 443), "untrusted-cloud-endpoint")
        outgoing = dict(headers or {})
        require(not any(k.lower() == "authorization" for k in outgoing), "caller-authorization-forbidden")
        outgoing["Authorization"] = "Bearer " + self.token(audience, tenant)
        if audience == STORAGE:
            outgoing["x-ms-version"] = "2023-11-03"
            outgoing["x-ms-date"] = formatdate(usegmt=True)
        body = data if isinstance(data, bytes) else canonical(data) if data is not None else None
        if body is not None and not isinstance(data, bytes):
            outgoing["Content-Type"] = "application/json"
        try:
            response = self.opener.open(Request(url, method=method, data=body, headers=outgoing), timeout=90)
        except HTTPError as exc:
            response = exc
        except (URLError, OSError, TimeoutError):
            raise EnrollmentError("remote-request-uncertain") from None
        with response:
            status = response.status if hasattr(response, "status") else response.code
            incoming = {key.lower(): value for key, value in response.headers.items()}
            raw = response.read(MAX_BYTES + 1)
        require(status in allowed, f"remote-request-failed-{status}")
        require(len(raw) <= MAX_BYTES, "remote-response-too-large")
        if raw and raw.lstrip().startswith((b"{", b"[")):
            value = parse_json(raw)
        else:
            value = raw
        return status, incoming, value

    def arm(self, method, identifier, version, data=None, headers=None, allowed=(200,)):
        require(identifier.startswith("/subscriptions/"), "arm-scope-required")
        return self.http(method, ARM + identifier + ("&" if "?" in identifier else "?") + "api-version=" + version,
                         ARM + "/", data, headers, allowed=allowed)

    def collection(self, identifier, version):
        url = ARM + identifier + ("&" if "?" in identifier else "?") + "api-version=" + version
        subscription = identifier.split("/")[2]
        rows, seen = [], set()
        while url:
            require(url not in seen and len(seen) < 100, "incomplete-cloud-inventory")
            seen.add(url)
            _, _, body = self.http("GET", url, ARM + "/")
            require(isinstance(body, dict) and isinstance(body.get("value"), list), "invalid-cloud-inventory")
            rows.extend(body["value"])
            require(len(rows) <= 10000, "incomplete-cloud-inventory")
            url = body.get("nextLink")
            if url:
                require(url.startswith(ARM + "/subscriptions/" + subscription + "/"),
                        "inventory-pagination-escaped-subscription")
        return rows

    def storage(self, method, blob=None, data=None, headers=None, allowed=(200,)):
        require(not _single_writer(self.request_config), "single-writer-storage-access-forbidden")
        coordinates = self.request_config["coordinates"]
        url = coordinates["account_url"] + "/" + coordinates["container"]
        url += "?restype=container" if blob is None else "/" + quote(blob, safe="/")
        if method == "PUT":
            if blob is None:
                require(not headers and data in (None, b""), "private-container-create-required")
            else:
                require(headers and ("If-None-Match" in headers or "If-Match" in headers), "conditional-storage-write-required")
        try:
            return self.http(method, url, STORAGE, data, headers, allowed=allowed)
        except EnrollmentError as exc:
            if _common_mode(self.request_config) and exc.code in (
                    "remote-request-uncertain", "remote-request-failed-401", "remote-request-failed-403"):
                raise EnrollmentError("common-storage-private-routing-dns-or-entra-access-required:" + exc.code) from None
            raise

    def gh(self, method, endpoint, body=None, allowed=(200,)):
        require(method in ("GET", "POST") or (
            method == "PATCH" and _single_writer(self.request_config)
            and endpoint == "repos/" + urlsplit(self.request_config["route"]["repository"]).path.strip("/").removesuffix(".git")
            + "/git/refs/heads/aifactory-state/single-writer-v1"
            and isinstance(body, dict) and body.get("force") is False), "delete-or-replacement-forbidden")
        require(not self.read_only or method == "GET", "plan-mutation-forbidden")
        require(endpoint.startswith("repos/") and "://" not in endpoint, "untrusted-github-endpoint")
        argv = ["gh", "api", "--hostname", "github.com", "--include", "--method", method, endpoint]
        if body is not None:
            argv += ["--input", "-"]
        # gh exits nonzero on HTTP errors; unlike generic CLI errors an explicit
        # HTTP status header permits distinguishing a real 404 from auth failure.
        try:
            result = self.command_runner(argv, input=canonical(body) if body is not None else None,
                                         capture_output=True, check=False, timeout=120, shell=False)
        except (OSError, subprocess.SubprocessError):
            raise EnrollmentError("github-authentication-or-command-failed") from None
        raw = result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout
        header, sep, text = raw.replace("\r\n", "\n").partition("\n\n")
        match = re.match(r"HTTP/\S+\s+(\d{3})", header)
        require(match and sep, "github-authentication-or-command-failed")
        status = int(match[1])
        require(status in allowed, f"github-request-failed-{status}")
        require(result.returncode == 0 or status == 404, "github-authentication-or-command-failed")
        headers = {k.lower(): v.strip() for line in header.splitlines()[1:] if ":" in line
                   for k, v in [line.split(":", 1)]}
        return status, headers, parse_json(text) if text.strip() else None

    def state_request(self, kind, method, endpoint, body, allowed):
        require(_single_writer(self.request_config), "single-writer-not-selected")
        if kind == "gha":
            return self.gh(method, endpoint, body, allowed)
        return self.http(method, endpoint, ADO_AUDIENCE, data=body,
                         tenant=self.request_config["ado_tenant_id"], allowed=allowed)


def _absent(response):
    status, headers, body = response
    require(status in (200, 404), "invalid-read-status")
    if isinstance(body, bytes):
        body = {"length": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    return None if status == 404 else {"body": body, "etag": headers.get("etag")}


def _identity(value, request):
    require(isinstance(value, dict), "invalid-managed-identity")
    require(str(value.get("id", "")).lower() == request["identity_id"], "managed-identity-arm-id-conflict")
    props = value.get("properties", value)
    result = {"id": request["identity_id"], "tenant_id": guid(props.get("tenantId")),
              "client_id": guid(props.get("clientId")), "principal_id": guid(props.get("principalId"))}
    require(result["tenant_id"] == request["target"]["tenant_id"]
            and result["client_id"] != result["principal_id"], "managed-identity-tenant-or-identifiers-conflict")
    return result


def _provider(cloud, request, identity):
    route, target = request["route"], request["target"]
    if route["kind"] == "gha":
        repository = route["repository"].removeprefix("https://github.com/").removesuffix(".git")
        base = "repos/" + repository
        _, _, repo = cloud.gh("GET", base)
        require(repo.get("full_name", "").lower() == repository.lower(), "github-repository-mismatch")
        _, _, subject = cloud.gh("GET", base + "/actions/oidc/customization/sub")
        require(subject.get("use_default") is True, "github-custom-oidc-subject-unsupported")
        path = base + "/environments/" + quote(route["auth_namespace"], safe="")
        environment = _absent(cloud.gh("GET", path, allowed=(200, 404)))
        variables = {}
        if environment:
            for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"):
                variables[name] = _absent(cloud.gh("GET", path + "/variables/" + name, allowed=(200, 404)))
                expected = {"AZURE_CLIENT_ID": identity["client_id"] if identity else None,
                            "AZURE_TENANT_ID": target["tenant_id"], "AZURE_SUBSCRIPTION_ID": target["subscription_id"]}[name]
                if variables[name]:
                    require(expected is not None and variables[name]["body"].get("value") == expected,
                            "github-variable-conflict")
        return {"kind": "gha", "environment": environment, "variables": variables, "path": path,
                "issuer": "https://token.actions.githubusercontent.com",
                "subject": "repo:" + repo["full_name"] + ":environment:" + route["auth_namespace"]}
    parts = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
    organization, project = parts[:2]
    base = "https://dev.azure.com/" + quote(organization, safe="")
    project_url = base + "/_apis/projects/" + quote(project, safe="") + "?api-version=7.1"
    _, _, project_body = cloud.http("GET", project_url, ADO_AUDIENCE, tenant=request["ado_tenant_id"])
    project_id = guid(project_body.get("id"))
    require(str(project_body.get("name", "")).lower() == project.lower(), "ado-project-mismatch")
    _, _, repository_body = cloud.http(
        "GET", base + "/" + project_id + "/_apis/git/repositories/" + quote(parts[3], safe="") + "?api-version=7.1",
        ADO_AUDIENCE, tenant=request["ado_tenant_id"])
    require(str(repository_body.get("name", "")).lower() == parts[3].lower()
            and str(repository_body.get("project", {}).get("id", "")).lower() == project_id,
            "ado-repository-mismatch")
    list_url = base + "/" + project_id + "/_apis/serviceendpoint/endpoints?" + urlencode(
        {"endpointNames": route["auth_namespace"], "api-version": "7.1"})
    _, headers, rows = cloud.http("GET", list_url, ADO_AUDIENCE, tenant=request["ado_tenant_id"])
    require(not headers.get("x-ms-continuationtoken") and isinstance(rows.get("value"), list),
            "incomplete-service-endpoint-inventory")
    matches = [row for row in rows["value"] if str(row.get("name", "")).lower() == route["auth_namespace"].lower()]
    require(len(matches) <= 1, "ambiguous-service-endpoint")
    endpoint = matches[0] if matches else None
    result = {"kind": "ado", "endpoint": endpoint, "base": base,
              "project_id": project_id, "project_name": project_body["name"], "issuer": None, "subject": None}
    if endpoint:
        require(endpoint.get("name") == route["auth_namespace"] and endpoint.get("type", "").lower() == "azurerm",
                "service-endpoint-conflict")
        require(endpoint.get("isReady") is True and endpoint.get("isShared") is False
                and not endpoint.get("operationStatus"), "service-endpoint-not-ready-or-shared")
        references = endpoint.get("serviceEndpointProjectReferences", [])
        require(len(references) == 1 and str(references[0].get("projectReference", {}).get("id", "")).lower() == project_id,
                "service-endpoint-project-reference-conflict")
        auth, data = endpoint.get("authorization", {}), endpoint.get("data", {})
        params = auth.get("parameters", {})
        require(auth.get("scheme") == "WorkloadIdentityFederation"
                and str(params.get("tenantid", "")).lower() == target["tenant_id"]
                and str(data.get("subscriptionId", "")).lower() == target["subscription_id"]
                and identity is not None and str(params.get("serviceprincipalid", "")).lower() == identity["client_id"],
                "service-endpoint-identity-conflict")
        for field, key in (("workloadIdentityFederationIssuer", "issuer"), ("workloadIdentityFederationSubject", "subject")):
            found = [source[field] for source in (data, params) if source.get(field)]
            require(found and len(set(found)) == 1, "service-endpoint-federation-response-required")
            result[key] = found[0]
        issuer = urlsplit(result["issuer"])
        require(issuer.scheme == "https" and issuer.hostname and not issuer.username and not issuer.query
                and isinstance(result["subject"], str) and 0 < len(result["subject"]) <= 600,
                "invalid-service-endpoint-federation-response")
    return result


def _fic_properties(provider):
    return {"issuer": provider["issuer"], "subject": provider["subject"], "audiences": ["api://AzureADTokenExchange"]}


def _fic(cloud, request, provider, identity):
    if not identity:
        return {"id": request["identity_id"] + "/federatedidentitycredentials/af-" + digest(request["route"])[:24],
                "exists": False}
    rows = cloud.collection(request["identity_id"] + "/federatedIdentityCredentials", IDENTITY_API)
    identifier = request["identity_id"] + "/federatedidentitycredentials/af-" + digest(request["route"])[:24]
    expected = _fic_properties(provider)
    matching = []
    for row in rows:
        props = row.get("properties", {})
        same_name = str(row.get("id", "")).lower() == identifier
        same_subject = props.get("issuer") == provider["issuer"] and props.get("subject") == provider["subject"]
        if same_name or same_subject:
            require(provider["issuer"] and props == expected, "federated-credential-conflict")
            matching.append(row)
    require(len(matching) <= 1, "ambiguous-federated-credential")
    require(matching or len(rows) < 20, "managed-identity-federated-credential-capacity-exhausted")
    return {"id": matching[0]["id"] if matching else identifier, "exists": bool(matching), "inventory_hash": digest(rows)}


def _permission(permissions, action, data=False):
    key, excluded = ("dataActions", "notDataActions") if data else ("actions", "notActions")
    return any(any(fnmatch.fnmatchcase(action.lower(), x.lower()) for x in row.get(key, []))
               and not any(fnmatch.fnmatchcase(action.lower(), x.lower()) for x in row.get(excluded, []))
               for row in permissions)


def _valid_permission_rows(permissions):
    return isinstance(permissions, list) and all(
        isinstance(row, dict) and all(
            isinstance(row.get(key, []), list) and all(isinstance(value, str) for value in row.get(key, []))
            for key in ("actions", "notActions", "dataActions", "notDataActions"))
        for row in permissions)


def _deny_applies(deny, principal_id, operations, *, unresolved_actions=False):
    props = deny.get("properties", {})
    if not isinstance(props.get("scope", "/"), str):
        return True
    scope = str(props.get("scope", "")).lower().rstrip("/")
    inherited_subscription = deny.get("_inherited_subscription")
    no_children = props.get("doNotApplyToChildScopes", False)
    relevant = [
        (action, data) for identifier, action, data in operations
        if identifier == scope or (no_children is not True and (
            not scope or identifier.startswith(scope + "/")
            or (scope.startswith("/providers/microsoft.management/managementgroups/")
                and inherited_subscription and identifier.startswith(inherited_subscription + "/"))))]
    if not relevant:
        return False
    permissions = props.get("permissions")
    if not _valid_permission_rows(permissions) or not permissions:
        return True
    if not unresolved_actions and not any(_permission(permissions, action, data) for action, data in relevant):
        return False
    excluded = props.get("excludePrincipals", [])
    if isinstance(excluded, list) and principal_id and any(
            isinstance(value, dict) and str(value.get("id", "")).lower() == principal_id for value in excluded):
        return False
    principals = props.get("principals")
    if not isinstance(principals, list) or not principals:
        return True
    for value in principals:
        if not isinstance(value, dict):
            return True
        identifier, kind = str(value.get("id", "")).lower(), str(value.get("type", "")).lower()
        if identifier == principal_id or (identifier == "00000000-0000-0000-0000-000000000000"
                                         and kind == "systemdefined"):
            return True
        # Group membership and an as-yet unallocated writer cannot be resolved
        # from ARM evidence alone. Do not infer an exclusion or query Graph.
        if principal_id is None or kind not in ("user", "serviceprincipal", "managedidentity"):
            return True
        try:
            guid(identifier)
        except EnrollmentError:
            return True
    return False


@lru_cache(maxsize=512)
def _permission_patterns_overlap(allowed, excluded):
    """Find an action allowed by every glob and excluded by none (Azure '*' only)."""
    patterns = tuple(value.lower() for value in allowed + excluded)
    if any(any(char in pattern for char in "?[]") for pattern in patterns):
        return True

    def closure(pattern, positions):
        result = set(positions)
        for position in tuple(result):
            while position < len(pattern) and pattern[position] == "*":
                position += 1
                result.add(position)
        return frozenset(result)

    alphabet = set("".join(patterns)) - {"*"}
    alphabet.add("\0")  # Represents any other literal, not a proposed API action.
    initial = tuple(closure(pattern, {0}) for pattern in patterns)
    pending, seen = deque([initial]), {initial}
    while pending:
        state = pending.popleft()
        accepts = [len(pattern) in positions for pattern, positions in zip(patterns, state)]
        if all(accepts[:len(allowed)]) and not any(accepts[len(allowed):]):
            return True
        for char in alphabet:
            following = tuple(closure(pattern, {
                position if pattern[position] == "*" else position + 1
                for position in positions if position < len(pattern) and pattern[position] in ("*", char)})
                for pattern, positions in zip(patterns, state))
            if not all(following[:len(allowed)]) or following in seen:
                continue
            if len(seen) >= 4096:
                return True  # Unresolved policy complexity requires independent review.
            seen.add(following)
            pending.append(following)
    return False


def _writer_deny_applies(deny, request, definitions, principal_id):
    props = deny.get("properties", {})
    denied_scope = str(props.get("scope", "")).lower()
    for scope in request["scopes"]:
        identifier = (denied_scope if denied_scope.startswith(scope + "/")
                      else scope + "/providers/microsoft.resources/deployments/runtime")
        if not _deny_applies(deny, principal_id, [(identifier, "", False)], unresolved_actions=True):
            continue
        permissions = [permission for role in request["deployment_roles"] if role["scope"] == scope
                       for permission in definitions[role["role_definition_id"]].get("properties", {}).get("permissions", [])]
        denied = props.get("permissions")
        if not _valid_permission_rows(denied) or not denied:
            return True
        # Deployment payloads are not supplied here. An effective non-delete
        # permission denied inside an explicit deployment grant needs review.
        for row in denied:
            for grant in permissions:
                for left in row.get("actions", []):
                    for right in grant.get("actions", []):
                        for verb in ("read", "write", "action"):
                            if _permission_patterns_overlap(
                                    (left, right, "*/" + verb),
                                    tuple(row.get("notActions", [])) + tuple(grant.get("notActions", []))):
                                return True
    return False


def _roles(cloud, request, identity, operator_id, operator_operations):
    single = _single_writer(request)
    storage_scope = "" if single else request["account_id"] + "/blobservices/default/containers/" + request["coordinates"]["container"]
    subscription = "/subscriptions/" + request["target"]["subscription_id"]
    requested = copy.deepcopy(request["deployment_roles"])
    storage_subscription = subscription if single else "/subscriptions/" + request["account_id"].split("/")[2]
    if not single:
        requested.append({"scope": storage_scope,
                          "role_definition_id": storage_subscription + "/providers/microsoft.authorization/roledefinitions/" + DATA_ROLE})
    role_definitions = {}
    for item in requested:
        definition = item["role_definition_id"]
        role_definitions[definition] = cloud.arm("GET", definition, ROLE_API)[2]
    assignments = [row for scope in sorted({subscription, storage_subscription})
                   for row in cloud.collection(scope + "/providers/Microsoft.Authorization/roleAssignments", ROLE_API)]
    blockers = []
    affected = request["scopes"] + ([] if single else [storage_scope])
    # Inspect every applicable assignment without Graph name resolution.
    relevant = []
    for assignment in assignments:
        props = assignment.get("properties", {})
        scope = str(props.get("scope", "")).lower()
        if props.get("principalId", "").lower() not in {operator_id, (identity or {}).get("principal_id")}:
            continue
        if not any(x == scope or x.startswith(scope + "/") for x in affected):
            continue
        if props.get("condition"):
            blockers.append("conditional-role-assignment-requires-independent-rights-review")
            continue
        definition = str(props.get("roleDefinitionId", "")).lower()
        if definition not in role_definitions and not single:
            role_definitions[definition] = cloud.arm("GET", definition, ROLE_API)[2]
        relevant.append(props)
    grants = []
    for item in requested:
        expected_role = item["role_definition_id"].rsplit("/", 1)[1]
        exists = any(x.get("principalId", "").lower() == (identity or {}).get("principal_id")
                     and str(x.get("roleDefinitionId", "")).lower().endswith("/" + expected_role)
                     and (item["scope"] == str(x.get("scope", "")).lower()
                          or item["scope"].startswith(str(x.get("scope", "")).lower() + "/")) for x in relevant)
        grants.append(dict(item, exists=exists, principal="writer"))
    for scope in request["scopes"]:
        permissions = [permission for x in requested if x["scope"] == scope
                       for permission in role_definitions[x["role_definition_id"]].get("properties", {}).get("permissions", [])]
        if not _permission(permissions, "Microsoft.Resources/deployments/write"):
            blockers.append("explicit-deployment-role-required:" + scope)
    operator_permissions = [permission for x in relevant if x.get("principalId", "").lower() == operator_id
                            and (storage_scope == str(x.get("scope", "")).lower()
                                 or storage_scope.startswith(str(x.get("scope", "")).lower() + "/"))
                            for permission in role_definitions.get(str(x["roleDefinitionId"]).lower(), {}).get("properties", {}).get("permissions", [])]
    operator_access = single or all(_permission(operator_permissions, action, data=True) for action in (
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"))
    container_create = "Microsoft.Storage/storageAccounts/blobServices/containers/write"
    # When the operator's blob-data role does not exist yet it is granted in this same
    # run (before the container is created), so evaluate container-create rights against
    # the permissions the operator will hold after that planned grant, not just today's.
    planned_operator_permissions = list(operator_permissions)
    if not operator_access:
        planned_operator_permissions += role_definitions[requested[-1]["role_definition_id"]].get(
            "properties", {}).get("permissions", [])
    if any(action == container_create for _, action, _ in operator_operations) and not _permission(
            planned_operator_permissions, container_create):
        blockers.append("operator-container-create-permission-not-verified")
    if not single:
        grants.append(dict(requested[-1], exists=operator_access, principal="operator"))
    operator_operations = list(operator_operations)
    for grant in grants:
        if not grant["exists"]:
            principal = operator_id if grant["principal"] == "operator" else (identity or {}).get("principal_id")
            identifier = grant["scope"] + "/providers/microsoft.authorization/roleassignments/" + str(uuid5(
                NAMESPACE_URL, grant["scope"] + ":" + (principal or "unallocated") + ":" + grant["role_definition_id"]))
            operator_operations.append((identifier, "Microsoft.Authorization/roleAssignments/write", False))
    writer_operations = [
        (scope + "/providers/microsoft.resources/deployments/runtime", action, False)
        for scope in request["scopes"] for action in (
            "Microsoft.Resources/deployments/read", "Microsoft.Resources/deployments/write")]
    blob_operations = [
        (storage_scope + "/blobs/" + blob, action, True)
        for blob in ([] if single else [request["coordinates"]["coordination_blob"]] + [
            lock_blob(scope) for scope in request["scopes"] + request["common_dependencies"]]
        )
        for action in ("Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
                       "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write")]
    operator_operations.extend(blob_operations)
    writer_operations.extend(blob_operations)
    denies = {}
    subscriptions = {"/".join(identifier.split("/")[:3])
                     for identifier, _, _ in operator_operations + writer_operations}
    for selected_subscription in sorted(subscriptions):
        path = selected_subscription + "/providers/Microsoft.Authorization/denyAssignments"
        rows = cloud.collection(path, ROLE_API)
        rows += cloud.collection(path + "?$filter=atScope()", ROLE_API)
        for row in rows:
            entry = dict(row, _inherited_subscription=selected_subscription)
            denies[digest(entry)] = entry
    for deny in denies.values():
        if (_deny_applies(deny, operator_id, operator_operations)
                or _deny_applies(deny, (identity or {}).get("principal_id"), writer_operations)
                or _writer_deny_applies(deny, request, role_definitions, (identity or {}).get("principal_id"))):
            blockers.append("deny-assignment-requires-independent-rights-review")
    return {"grants": grants, "assignments_hash": digest(assignments), "denies_hash": digest(denies),
            "definitions_hash": digest(role_definitions), "blockers": sorted(set(blockers))}


def merge_enrollment(existing, request, identity):
    """Pure add-only merge; identity=None permits preflight, never publication."""
    target, route = request["target"], request["route"]
    writer = {key: copy.deepcopy(route[key]) for key in ("kind", "repository", "shared_remote", "auth_namespace", "runner")}
    writer["deployment_object_id"] = identity["principal_id"] if identity else None
    single = _single_writer(request)
    protocol = "aifactory-single-writer-v1" if single else "aifactory-physical-lock-v1"
    enforcement = "repository-exclusive-writer" if single else "all-writers-exclusive"
    if existing is None:
        result = {"schema": 1, "protocol": protocol, "enforcement": enforcement,
                  "revision": 0, "writers": {}, "scopes": {}}
    else:
        require(isinstance(existing, dict) and existing.get("schema") == 1
                and existing.get("protocol") == protocol
                and existing.get("enforcement") == enforcement
                and type(existing.get("revision")) is int and existing["revision"] >= 1
                and isinstance(existing.get("writers"), dict) and isinstance(existing.get("scopes"), dict),
                "invalid-existing-enrollment")
        result = copy.deepcopy(existing)
        for scope, record in result["scopes"].items():
            require(rg_id(scope) == scope and isinstance(record, dict), "noncanonical-existing-enrollment-scope")
            enrolled = record.get("writers")
            require(isinstance(enrolled, list) and enrolled and all(isinstance(x, str) for x in enrolled)
                    and len(set(enrolled)) == len(enrolled)
                    and all(writer_id in result["writers"] for writer_id in enrolled),
                    "invalid-existing-scope-writers")
            dependencies = record.get("common_dependencies")
            require(isinstance(dependencies, list)
                    and all(rg_id(x) == x and x in result["scopes"] for x in dependencies),
                    "invalid-existing-scope-dependencies")
    for writer_id, previous in result["writers"].items():
        require(isinstance(previous, dict), "invalid-existing-writer")
        require(not single or writer_id == route["writer_id"], "single-writer-repository-writer-conflict")
        if writer_id != route["writer_id"]:
            require(not (previous.get("kind") == route["kind"]
                         and str(previous.get("repository", "")).lower().removesuffix(".git") == route["repository"].lower().removesuffix(".git")
                         and str(previous.get("auth_namespace", "")).lower() == route["auth_namespace"].lower()),
                    "auth-namespace-already-enrolled")
    previous = result["writers"].get(route["writer_id"])
    require(previous is None or identity is not None, "existing-writer-without-verified-identity")
    require(previous is None or previous == writer, "existing-writer-conflict")
    result["writers"].setdefault(route["writer_id"], writer)
    for scope in request["scopes"]:
        wanted = {"writers": [route["writer_id"]], "scope_kind": "aifactory-owned", "allow_delete": False,
                  "target": copy.deepcopy(target), "common_dependencies": list(request["common_dependencies"])}
        if scope in result["scopes"]:
            previous = result["scopes"][scope]
            # Preserve previously reviewed deletion authority; never add or revoke it.
            require(all(previous.get(k) == v for k, v in wanted.items() if k != "allow_delete"),
                    "existing-scope-conflict")
        else:
            result["scopes"][scope] = wanted
    for scope in request["common_dependencies"]:
        previous = result["scopes"].get(scope)
        require(isinstance(previous, dict) and isinstance(previous.get("writers"), list) and previous["writers"]
                and all(writer_id in result["writers"] for writer_id in previous["writers"]),
                "common-dependency-writer-must-be-independently-enrolled")
    if existing is None or result != existing:
        result["revision"] += 1
    return result


def binding_candidate(request, identity, enrollment):
    """Closed RuntimeBinding JSON for catalog prepare/confirm configure-binding."""
    route = request["route"]
    locks = dict(request["coordinates"], coordination_hash=digest(enrollment), revision=enrollment["revision"])
    selected = {"scale_set_id": request["target"]["scaleset_id"], "resource_group_ids": request["scopes"],
                "common_dependency_ids": request["common_dependencies"]}
    execution = {"writer_id": route["writer_id"], "auth_namespace": route["auth_namespace"],
                 "deployment_object_id": identity["principal_id"], "runner": route["runner"]}
    old = next((x["binding"] for x in request["existing_bindings"] if x["factory_id"] == request["target"]["factory_id"]
                and x["provider"] == route["kind"]), None)
    if old:
        result = copy.deepcopy(old)
        require(all(result.get(k) == route[k] for k in ("repository", "ref", "shared_remote")),
                "existing-binding-route-conflict")
        require(all(result["locks"].get(k) == v for k, v in request["coordinates"].items()),
                "existing-binding-coordinates-conflict")
        found = [x for x in result["targets"] if x.get("scale_set_id") == selected["scale_set_id"]]
        expected_execution = (found[0].get("execution") if found else None) or result
        if found:
            require(all(sorted(rg_id(v) for v in found[0].get(k, [])) == selected[k]
                        for k in ("resource_group_ids", "common_dependency_ids"))
                    and all(expected_execution.get(k) == v for k, v in execution.items()),
                    "existing-binding-target-conflict")
        else:
            require(result["shared_remote"], "existing-binding-not-shared")
            selected["execution"] = execution
            result["targets"].append(selected)
        result["locks"] = locks
        return result
    return {"contract_version": 1, "orchestrator": route["kind"],
            **{k: route[k] for k in ("repository", "ref", "shared_remote")},
            **execution, "locks": locks, "targets": [selected]}


def _validate_storage(request, storage):
    props = storage.get("properties", {})
    require(str(storage.get("id", "")).lower() == request["account_id"], "storage-account-id-conflict")
    require((type(props.get("allowSharedKeyAccess")) is bool if _common_mode(request)
             else props.get("allowSharedKeyAccess") is False)
            and props.get("allowBlobPublicAccess") is False
            and props.get("supportsHttpsTrafficOnly") is True and props.get("minimumTlsVersion") in ("TLS1_2", "TLS1_3"),
            "existing-storage-security-policy-not-compatible")
    if _common_mode(request):
        require(props.get("isHnsEnabled") is True, "factory-common-storage-hns-required")
        require(props.get("publicNetworkAccess") in ("Enabled", "Disabled")
                and props.get("networkAcls", {}).get("defaultAction") == "Deny",
                "existing-common-storage-private-network-policy-not-compatible")
    if request.get("coordination_storage_mode") == "connectivity-hub":
        hub = request["account_id"].split("/providers/")[0]
        require(storage.get("kind") == "StorageV2" and props.get("isHnsEnabled") is False
                and props.get("defaultToOAuthAuthentication") is True
                and props.get("networkAcls", {}).get("defaultAction") == "Deny"
                and storage.get("tags", {}).get("aifactory.coordination") == "connectivity-hub-v1"
                and storage.get("tags", {}).get("aifactory.hub_scope_sha256") == hashlib.sha256(hub.encode()).hexdigest(),
                "shared-hub-storage-policy-conflict")
    if request["public_network_access"] is not None:
        require(props.get("publicNetworkAccess") == request["public_network_access"], "existing-storage-network-policy-conflict")


def _validate_container(container):
    require(container.get("properties", {}).get("publicAccess") in (None, "None"),
            "existing-container-public-access-forbidden")


def _lifecycle_protection(request):
    return {"account_id": request["account_id"], "container_id": _container_id(request),
            "resource_group_id": request["account_id"].split("/providers/")[0],
            "ordinary_factory_delete": "forbidden",
            "retention": "retain-coordination-account-container-and-parent-resource-group"}


def _collect_single_writer_snapshot(request, cloud):
    cloud.read_only = True
    target = request["target"]
    store = _single_writer_module().ProviderState(cloud, request["route"], EnrollmentError)
    head, repository_state = store.read()
    claim = getattr(cloud, "single_writer_enrollment_claim", None)
    require(not repository_state or repository_state["active"] in (None, claim),
            "single-writer-repository-active-claim")
    bound = any(item["binding"]["locks"].get("coordination_mode") == "single-writer"
                and item["binding"]["repository"] == request["route"]["repository"]
                for item in request["existing_bindings"])
    require(not bound or repository_state is not None and repository_state["enrollment"] is not None,
            "single-writer-enrollment-state-missing")
    account = cloud.az("account", "show", "--subscription", target["subscription_id"])
    require(str(account.get("id", "")).lower() == target["subscription_id"]
            and str(account.get("tenantId", "")).lower() == target["tenant_id"], "selected-account-tenant-mismatch")
    identity_subscription = request["identity_id"].split("/")[2]
    identity_account = None
    if identity_subscription != target["subscription_id"]:
        identity_account = cloud.az("account", "show", "--subscription", identity_subscription)
        require(str(identity_account.get("id", "")).lower() == identity_subscription
                and str(identity_account.get("tenantId", "")).lower() == target["tenant_id"], "identity-subscription-tenant-mismatch")
    cloud.token(ARM + "/")
    require(cloud.operator_id, "operator-principal-required")
    blockers, actions, groups = [], [], {}
    for scope in sorted(set(request["scopes"] + request["common_dependencies"]
                            + [request["identity_id"].split("/providers/")[0]])):
        groups[scope] = _absent(cloud.arm("GET", scope, RG_API, allowed=(200, 404)))
        if groups[scope] is None:
            (actions if scope in request["create_resource_group_ids"] else blockers).append(
                ("create-resource-group:" if scope in request["create_resource_group_ids"] else "resource-group-missing:") + scope)
        elif scope in request["scopes"]:
            tags = groups[scope]["body"].get("tags", {})
            if tags.get("aifactory.factory_id") != target["factory_id"] or tags.get("aifactory.scaleset_id") != target["scaleset_id"]:
                blockers.append("existing-resource-group-ownership-not-proven:" + scope)
    identity_arm = _absent(cloud.arm("GET", request["identity_id"], IDENTITY_API, allowed=(200, 404)))
    identity = _identity(identity_arm["body"], request) if identity_arm else None
    if identity:
        require(_identity(cloud.az("identity", "show", "--ids", request["identity_id"],
                                   "--subscription", identity_subscription), request) == identity,
                "managed-identity-changed-during-read")
    elif request["reuse_identity"]:
        blockers.append("requested-existing-identity-not-found")
    else:
        actions.append("create-user-assigned-managed-identity")
    provider = _provider(cloud, request, identity)
    if provider["kind"] == "gha":
        if not provider["environment"]:
            blockers.append("github-environment-must-be-preprovisioned-no-atomic-create")
        actions.extend("create-github-variable:" + name for name in (
            "AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID") if not provider["variables"].get(name))
    elif not provider["endpoint"]:
        actions.append("create-ado-workload-identity-service-connection")
    fic = _fic(cloud, request, provider, identity)
    if not fic["exists"]:
        actions.append("create-federated-identity-credential")
    operations = [(scope, "Microsoft.Resources/subscriptions/resourceGroups/write", False)
                  for scope, value in groups.items() if value is None]
    if identity is None:
        operations.append((request["identity_id"], "Microsoft.ManagedIdentity/userAssignedIdentities/write", False))
    if not fic["exists"]:
        operations.append((fic["id"], "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/write", False))
    roles = _roles(cloud, request, identity, cloud.operator_id, operations)
    blockers.extend(roles["blockers"])
    actions.extend("grant-role:" + x["principal"] + ":" + x["scope"] + ":" + x["role_definition_id"].rsplit("/", 1)[1]
                   for x in roles["grants"] if not x["exists"])
    previous = repository_state["enrollment"] if repository_state else None
    merged, candidate = None, None
    try:
        require(identity is not None or not bound, "existing-binding-without-verified-identity")
        proposed = merge_enrollment(previous, request, identity)
        proposed_binding = binding_candidate(request, identity or {"principal_id": None}, proposed)
        if identity:
            merged, candidate = proposed, proposed_binding
        if previous != proposed:
            actions.append("merge-coordination-enrollment-conditionally")
    except EnrollmentError as exc:
        blockers.append(exc.code)
    return {"account": {"id": account["id"], "tenant_id": account["tenantId"], "name": account.get("name")},
            "identity_account": identity_account, "operator_id": cloud.operator_id, "groups": groups,
            "identity_arm": identity_arm, "identity": identity, "provider": provider, "fic": fic, "roles": roles,
            "enrollment": {"body": previous, "etag": head} if previous else None,
            "repository_head": head, "repository_state": repository_state, "merged": merged, "candidate": candidate,
            "actions": sorted(actions), "blockers": sorted(set(blockers))}


def _collect_snapshot(request, cloud):
    if _single_writer(request):
        return _collect_single_writer_snapshot(request, cloud)
    cloud.read_only = True
    target = request["target"]
    account = cloud.az("account", "show", "--subscription", target["subscription_id"])
    require(str(account.get("id", "")).lower() == target["subscription_id"]
            and str(account.get("tenantId", "")).lower() == target["tenant_id"], "selected-account-tenant-mismatch")
    if request["account_id"].split("/")[2] != target["subscription_id"]:
        storage_account = cloud.az("account", "show", "--subscription", request["account_id"].split("/")[2])
        require(str(storage_account.get("tenantId", "")).lower() == target["tenant_id"]
                and str(storage_account.get("id", "")).lower() == request["account_id"].split("/")[2],
                "shared-hub-subscription-tenant-mismatch")
    identity_subscription = request["identity_id"].split("/")[2]
    identity_account = None
    if identity_subscription != target["subscription_id"]:
        identity_account = cloud.az("account", "show", "--subscription", identity_subscription)
        require(str(identity_account.get("id", "")).lower() == identity_subscription
                and str(identity_account.get("tenantId", "")).lower() == target["tenant_id"],
                "identity-subscription-tenant-mismatch")
    cloud.token(ARM + "/")
    require(cloud.operator_id, "operator-principal-required")
    blockers, actions, groups = [], [], {}
    infrastructure = [request["account_id"].split("/providers/")[0], request["identity_id"].split("/providers/")[0]]
    for scope in sorted(set(request["scopes"] + request["common_dependencies"] + infrastructure)):
        groups[scope] = _absent(cloud.arm("GET", scope, RG_API, allowed=(200, 404)))
        if groups[scope] is None:
            if scope in request["create_resource_group_ids"]:
                actions.append("create-resource-group:" + scope)
            else:
                blockers.append("resource-group-missing:" + scope)
        elif scope in request["scopes"]:
            tags = groups[scope]["body"].get("tags", {})
            if tags.get("aifactory.factory_id") != target["factory_id"] or tags.get("aifactory.scaleset_id") != target["scaleset_id"]:
                blockers.append("existing-resource-group-ownership-not-proven:" + scope)
    identity_arm = _absent(cloud.arm("GET", request["identity_id"], IDENTITY_API, allowed=(200, 404)))
    identity = None
    if identity_arm:
        identity = _identity(identity_arm["body"], request)
        cli_identity = _identity(cloud.az("identity", "show", "--ids", request["identity_id"],
                                        "--subscription", identity_subscription), request)
        require(identity == cli_identity, "managed-identity-changed-during-read")
    elif request["reuse_identity"]:
        blockers.append("requested-existing-identity-not-found")
    else:
        actions.append("create-user-assigned-managed-identity")
    storage = _absent(cloud.arm("GET", request["account_id"], STORAGE_API, allowed=(200, 404)))
    require(request.get("coordination_storage_mode") != "connectivity-hub" or storage is not None,
            "shared-hub-foundation-must-exist")
    container, enrollment = None, None
    blobs = {}
    if storage:
        _validate_storage(request, storage["body"])
        if _common_mode(request):
            # ARM distinguishes a missing container before scoped data RBAC exists.
            # A forbidden/unreachable data plane never becomes evidence of absence.
            container = _absent(cloud.arm("GET", _container_id(request), STORAGE_API, allowed=(200, 404)))
        else:
            container = _absent(cloud.storage("HEAD", allowed=(200, 404)))
        if container:
            container_arm = (container["body"] if _common_mode(request)
                             else cloud.arm("GET", _container_id(request), STORAGE_API)[2])
            _validate_container(container_arm)
            if _common_mode(request):
                cloud.storage("HEAD")
            enrollment = _absent(cloud.storage("GET", request["coordinates"]["coordination_blob"], allowed=(200, 404)))
            for scope in request["scopes"] + request["common_dependencies"]:
                response = cloud.storage("HEAD", lock_blob(scope), allowed=(200, 404))
                blobs[scope] = _absent(response)
                if blobs[scope]:
                    require(response[1].get("content-length") == "0", "existing-lock-blob-must-be-empty")
    else:
        name = request["account_id"].rsplit("/", 1)[1]
        inventory = cloud.collection("/subscriptions/" + target["subscription_id"] +
                                     "/providers/Microsoft.Storage/storageAccounts", STORAGE_API)
        require(not any(str(row.get("name", "")).lower() == name for row in inventory),
                "storage-name-already-in-another-resource-group")
        available = cloud.az("storage", "account", "check-name", "--name", name, "--subscription", target["subscription_id"])
        require(available.get("nameAvailable") is True, "coordination-account-global-name-unavailable")
        if request["public_network_access"] is None:
            blockers.append("explicit-new-storage-public-network-policy-required")
        if _common_mode(request):
            if request["coordination_account_creation"] is None:
                blockers.append("canonical-common-account-creation-required")
            actions.append("create-canonical-common-adls-account")
        else:
            actions.append("create-secure-coordination-account")
    if container is None:
        actions.append("create-private-coordination-container")
    container_permissions = None
    if _common_mode(request) and container is None:
        parent = request["account_id"] if storage else request["account_id"].split("/providers/")[0]
        if not storage and groups.get(parent) is None:
            parent = "/subscriptions/" + target["subscription_id"]
        container_permissions = cloud.collection(parent + "/providers/Microsoft.Authorization/permissions", ROLE_API)
        if not _permission(container_permissions, "Microsoft.Storage/storageAccounts/blobServices/containers/write"):
            blockers.append("operator-common-container-arm-create-permission-required")
    for scope in request["scopes"] + request["common_dependencies"]:
        if not blobs.get(scope):
            actions.append("create-empty-physical-lock:" + lock_blob(scope))
    provider = _provider(cloud, request, identity)
    if provider["kind"] == "gha":
        if not provider["environment"]:
            blockers.append("github-environment-must-be-preprovisioned-no-atomic-create")
        for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"):
            if not provider["variables"].get(name):
                actions.append("create-github-variable:" + name)
    elif not provider["endpoint"]:
        actions.append("create-ado-workload-identity-service-connection")
    fic = _fic(cloud, request, provider, identity)
    if not fic["exists"]:
        actions.append("create-federated-identity-credential")
    operator_operations = [(scope, "Microsoft.Resources/subscriptions/resourceGroups/write", False)
                           for scope, value in groups.items() if value is None]
    for identifier, action, missing in (
            (request["identity_id"], "Microsoft.ManagedIdentity/userAssignedIdentities/write", identity is None),
            (request["account_id"], "Microsoft.Storage/storageAccounts/write", storage is None),
            (request["account_id"] + "/blobservices/default/containers/" + request["coordinates"]["container"],
             "Microsoft.Storage/storageAccounts/blobServices/containers/write", container is None),
            (fic["id"], "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/write", not fic["exists"])):
        if missing:
            operator_operations.append((identifier.lower(), action, False))
    roles = _roles(cloud, request, identity, cloud.operator_id, operator_operations)
    blockers.extend(roles["blockers"])
    actions.extend("grant-role:" + x["principal"] + ":" + x["scope"] + ":" + x["role_definition_id"].rsplit("/", 1)[1]
                   for x in roles["grants"] if not x["exists"])
    merged, candidate = None, None
    try:
        if identity is None:
            require(not any(x["factory_id"] == target["factory_id"] and x["provider"] == request["route"]["kind"]
                            and any(t["scale_set_id"] == target["scaleset_id"] for t in x["binding"]["targets"])
                            for x in request["existing_bindings"]), "existing-binding-without-verified-identity")
        # An unallocated principal must not skip writer, scope, dependency or
        # existing binding checks. Provisional objects never leave the preflight.
        proposed = merge_enrollment(enrollment["body"] if enrollment else None, request, identity)
        proposed_binding = binding_candidate(request, identity or {"principal_id": None}, proposed)
        if identity:
            merged, candidate = proposed, proposed_binding
        if enrollment is None or enrollment["body"] != proposed:
            actions.append("merge-coordination-enrollment-conditionally")
    except EnrollmentError as exc:
        blockers.append(exc.code)
    return {"account": {"id": account["id"], "tenant_id": account["tenantId"], "name": account.get("name")},
            "identity_account": identity_account,
            "operator_id": cloud.operator_id, "groups": groups, "identity_arm": identity_arm, "identity": identity,
            "storage": storage, "container": container, "enrollment": enrollment, "blobs": blobs,
            "container_permissions": container_permissions,
            "provider": provider, "fic": fic, "roles": roles, "merged": merged, "candidate": candidate,
            "actions": sorted(actions), "blockers": sorted(set(blockers))}


def _snapshot(request, cloud):
    try:
        return _collect_snapshot(request, cloud)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise EnrollmentError("malformed-or-unavailable-cloud-state") from None


def _fresh_request(request):
    require(isinstance(request, dict) and request.get("schema") == 1, "invalid-enrollment-request")
    target = request["target"]
    fresh = load_request(request["consumer_root"], target["factory_id"], target["scaleset_id"],
                         target["environment"], request["options"])
    require(fresh == request, "consumer-or-request-changed")


def _review(request, state, acknowledge):
    scope_hash = digest(request)
    blockers = list(state["blockers"])
    if not acknowledge:
        blockers.append("exclusive-writer-governance-attestation-required")
    result = {"schema": 1, "scope_hash": scope_hash, "state_hash": digest(state),
              "target": request["target"], "route": request["route"],
              "identity_id": request["identity_id"], "identity": state["identity"],
              "coordination": ({**request["coordinates"]} if _single_writer(request) else
                               {"account_id": request["account_id"], **request["coordinates"]}),
              "resource_group_ids": request["scopes"], "common_dependency_ids": request["common_dependencies"],
              "actions": state["actions"], "blockers": sorted(set(blockers)),
              "acknowledge_exclusive_writer_governance": acknowledge,
              "can_ensure": not blockers, "enrollment_complete": False,
              "binding_publication": "catalog-prepare-confirm-configure-binding-only"}
    if _common_mode(request):
        result["coordination"]["storage_mode"] = request["coordination_storage_mode"]
        result["lifecycle_protection"] = _lifecycle_protection(request)
        result["warnings"] = [
            "account-and-key-administrators-can-bypass-or-destroy-coordination",
            "private-routing-dns-and-entra-data-access-required-before-normal-leases",
        ]
        if state["storage"] is None:
            result["coordination"]["account_creation"] = request["coordination_account_creation"]
    if _single_writer(request):
        helper = _single_writer_module()
        result["coordination_mode"] = "single-writer"
        result["warnings"] = [helper.WARNING, helper.HUB_WARNING,
                              "Single-writer coordination requires a private repository; repository visibility is never changed automatically.",
                              "Private repository administrators can bypass or destroy repository coordination."]
    result["plan_hash"] = digest(result)
    return result


def plan(request, *, cloud=None, acknowledge_exclusive_writer_governance=False):
    """Cloud-read-only plan. Tokens/HTTP bodies/configurations are never printed."""
    require(type(acknowledge_exclusive_writer_governance) is bool, "invalid-governance-acknowledgment")
    _fresh_request(request)
    cloud = cloud or Cloud(request)
    state = _snapshot(request, cloud)
    return _review(request, state, acknowledge_exclusive_writer_governance)


def _create_arm(cloud, identifier, api, body):
    """Documented ARM create-or-update; never a destructive replacement.

    ARM PUT is create-or-update, not atomic create-only, so this refuses to run
    without a serialized-provisioning acknowledgment, re-reads immediately before
    the write, and skips the PUT entirely if the object appeared in the gap so a
    concurrently created (possibly conflicting) resource is never overwritten.
    Post-create equality is re-verified by the caller's fresh snapshot.
    """
    require(cloud.serialized_provisioning, "arm-serialized-provisioning-required")
    if _absent(cloud.arm("GET", identifier, api, allowed=(200, 404))) is None:
        cloud.arm("PUT", identifier, api, body, allowed=(200, 201, 202))
    return _wait_arm(cloud, identifier, api)


def _propagating_storage_put(cloud, blob, data, headers, allowed, retry):
    """Data-plane create, retrying only known RBAC propagation (403).

    retry is enabled solely after this run created the operator's blob-data role;
    a 403 is then treated as pending replication, never as the object's absence,
    and the final attempt re-raises so a real authorization failure still surfaces.
    """
    attempts = 8 if retry else 1
    for attempt in range(attempts):
        try:
            return cloud.storage("PUT", blob, data=data, headers=headers, allowed=allowed)
        except EnrollmentError as exc:
            if exc.code not in ("remote-request-failed-403",
                                "common-storage-private-routing-dns-or-entra-access-required:remote-request-failed-403"
                                ) or attempt + 1 >= attempts:
                raise
            time.sleep(5)


def _wait_arm(cloud, identifier, api):
    for _ in range(30):
        value = _absent(cloud.arm("GET", identifier, api, allowed=(200, 404)))
        if value:
            status = value["body"].get("properties", {}).get("provisioningState", "Succeeded")
            require(status not in ("Failed", "Canceled", "Deleting"), "resource-provisioning-failed")
            if status == "Succeeded":
                return value["body"]
        time.sleep(2)
    raise EnrollmentError("resource-provisioning-not-confirmed")


def _create_provider(cloud, request, state, identity):
    provider, target, route = state["provider"], request["target"], request["route"]
    if provider["kind"] == "gha":
        path = provider["path"]
        require(provider["environment"], "github-environment-must-be-preprovisioned-no-atomic-create")
        current = _absent(cloud.gh("GET", path, allowed=(200, 404)))
        require(current == provider["environment"], "github-environment-changed")
        for name, value in {"AZURE_CLIENT_ID": identity["client_id"], "AZURE_TENANT_ID": target["tenant_id"],
                            "AZURE_SUBSCRIPTION_ID": target["subscription_id"]}.items():
            if not provider["variables"].get(name):
                require(cloud.gh("GET", path + "/variables/" + name, allowed=(200, 404))[0] == 404,
                        "github-variable-changed")
                cloud.gh("POST", path + "/variables", {"name": name, "value": value}, allowed=(201,))
    elif not provider["endpoint"]:
        require(not _provider(cloud, request, identity)["endpoint"], "service-endpoint-changed")
        body = {"name": route["auth_namespace"], "type": "azurerm", "url": ARM + "/",
                "isShared": False, "isReady": True,
                "authorization": {"scheme": "WorkloadIdentityFederation",
                                  "parameters": {"tenantid": target["tenant_id"], "serviceprincipalid": identity["client_id"]}},
                "data": {"subscriptionId": target["subscription_id"], "subscriptionName": state["account"]["name"],
                         "environment": "AzureCloud", "scopeLevel": "Subscription", "creationMode": "Manual"},
                "serviceEndpointProjectReferences": [
                    {"projectReference": {"id": provider["project_id"], "name": provider["project_name"]},
                     "name": route["auth_namespace"]}]}
        cloud.http("POST", provider["base"] + "/_apis/serviceendpoint/endpoints?api-version=7.1",
                   ADO_AUDIENCE, body, tenant=request["ado_tenant_id"], allowed=(200, 201))
    return _provider(cloud, request, identity)


def ensure(request, expected_plan, *, yes=False, acknowledge_exclusive_writer_governance=False, cloud=None):
    """Execute only additions after an exact fresh plan comparison; never rollback.

    An error after a possible write returns blocked/reconciliation_required.
    A new plan is necessary after any state change, including a successful ensure.
    Governance acknowledgment is required before any write, including protocol
    prerequisites; it never substitutes for the live permission and scope checks.
    """
    require(yes is True, "explicit-yes-required")
    require(acknowledge_exclusive_writer_governance is True,
            "exclusive-writer-governance-attestation-required")
    require(isinstance(expected_plan, str) and re.fullmatch(r"[a-f0-9]{64}", expected_plan), "expected-plan-sha256-required")
    require(type(acknowledge_exclusive_writer_governance) is bool, "invalid-governance-acknowledgment")
    _fresh_request(request)
    cloud = cloud or Cloud(request)
    state = _snapshot(request, cloud)
    review = _review(request, state, acknowledge_exclusive_writer_governance)
    require(review["plan_hash"] == expected_plan, "plan-or-live-state-changed")
    require(not state["blockers"], "enrollment-prerequisites-blocked")
    changed = False
    cloud.read_only = False
    cloud.serialized_provisioning = acknowledge_exclusive_writer_governance
    try:
        target = request["target"]
        single = _single_writer(request)
        if single and state["actions"]:
            store = _single_writer_module().ProviderState(cloud, request["route"], EnrollmentError)
            pending = state["repository_state"] or store.empty()
            require(pending["active"] is None, "single-writer-repository-active-claim")
            claim = {"kind": "enrollment", "id": str(uuid4()), "plan_hash": expected_plan}
            pending = copy.deepcopy(pending)
            pending["active"] = claim
            changed = True
            store.replace(state["repository_head"], pending)
            cloud.single_writer_enrollment_claim = claim
        for scope, existing in state["groups"].items():
            if existing is None:
                require(scope in request["create_resource_group_ids"] and request["approved_group_creation_scope"],
                        "resource-group-creation-not-approved")
                body = {"location": target["region"]}
                if scope in request["scopes"]:
                    body["tags"] = {"aifactory.factory_id": target["factory_id"], "aifactory.scaleset_id": target["scaleset_id"]}
                changed = True
                _create_arm(cloud, scope, RG_API, body)
                _wait_arm(cloud, scope, RG_API)
        identity = state["identity"]
        if identity is None:
            require(not request["reuse_identity"], "requested-existing-identity-not-found")
            changed = True
            _create_arm(cloud, request["identity_id"], IDENTITY_API, {"location": target["region"]})
            identity = _identity(_wait_arm(cloud, request["identity_id"], IDENTITY_API), request)
            require(_identity(cloud.az("identity", "show", "--ids", request["identity_id"],
                                       "--subscription", target["subscription_id"]), request) == identity,
                    "managed-identity-changed-during-read")
        if not single and state["storage"] is None:
            changed = True
            body = (request["coordination_account_creation"] if _common_mode(request) else
                    {"location": target["region"], "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                         "properties": {"allowSharedKeyAccess": False, "allowBlobPublicAccess": False,
                                        "supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2",
                                        "defaultToOAuthAuthentication": True,
                                        "publicNetworkAccess": request["public_network_access"],
                                        "networkAcls": {"defaultAction": "Deny" if request["public_network_access"] == "Disabled" else "Allow",
                                                        "bypass": "None"}}})
            _validate_storage(request, _create_arm(cloud, request["account_id"], STORAGE_API, body))
        elif _common_mode(request):
            _validate_storage(request, cloud.arm("GET", request["account_id"], STORAGE_API)[2])
        if _common_mode(request):
            # Create only metadata, using existing ARM management rights. Assigning
            # its data role afterwards never grants access to lake3 or its ACLs.
            if state["container"] is None:
                changed = True
                container = _create_arm(cloud, _container_id(request), STORAGE_API,
                                       {"properties": {"publicAccess": "None"}})
            else:
                container = cloud.arm("GET", _container_id(request), STORAGE_API)[2]
            _validate_container(container)
        # Grant RBAC (notably the operator's blob-data role) BEFORE any data-plane
        # container or lease write: a just-created account's operator otherwise
        # lacks blob-data rights to create the container.
        operator_grant_created = False
        for grant in state["roles"]["grants"]:
            if grant["exists"]:
                continue
            changed = True
            principal_id = state["operator_id"] if grant["principal"] == "operator" else identity["principal_id"]
            identifier = grant["scope"] + "/providers/Microsoft.Authorization/roleAssignments/" + str(uuid5(
                NAMESPACE_URL, grant["scope"] + ":" + principal_id + ":" + grant["role_definition_id"]))
            _create_arm(cloud, identifier, ROLE_API,
                        {"properties": {"principalId": principal_id,
                                        **({"principalType": "ServicePrincipal"} if grant["principal"] == "writer" else {}),
                                        "roleDefinitionId": grant["role_definition_id"]}})
            if grant["principal"] == "operator":
                operator_grant_created = True
        if not single and state["container"] is None and not _common_mode(request):
            changed = True
            container_id = request["account_id"] + "/blobServices/default/containers/" + request["coordinates"]["container"]
            _propagating_storage_put(cloud, None, b"", None, (201,), operator_grant_created)
            _wait_arm(cloud, container_id, STORAGE_API)
        if _common_mode(request):
            for attempt in range(8 if operator_grant_created else 1):
                try:
                    cloud.storage("HEAD")
                    break
                except EnrollmentError as exc:
                    if not (operator_grant_created and exc.code.endswith(":remote-request-failed-403")
                            and attempt < 7):
                        raise
                    time.sleep(5)
        provider_writes = any(x.startswith(("create-github", "create-ado")) for x in state["actions"])
        changed = changed or provider_writes
        provider = _create_provider(cloud, request, state, identity)
        fic = _fic(cloud, request, provider, identity)
        if not fic["exists"]:
            require(provider["issuer"] and provider["subject"], "provider-federation-not-confirmed")
            changed = True
            _create_arm(cloud, fic["id"], IDENTITY_API, {"properties": _fic_properties(provider)})
        for scope in ([] if single else request["scopes"] + request["common_dependencies"]):
            if not state["blobs"].get(scope):
                changed = True
                _propagating_storage_put(cloud, lock_blob(scope), b"",
                                         {"If-None-Match": "*", "x-ms-blob-type": "BlockBlob"}, (201,),
                                         operator_grant_created)
        # Re-read everything, including role evidence, before attesting or publishing
        # a candidate. Data-plane 403/replication delays never become a ready result.
        verified = _snapshot(request, cloud)
        require(not verified["blockers"], "post-create-rights-not-verified")
        remaining = [x for x in verified["actions"] if x != "merge-coordination-enrollment-conditionally"]
        require(not remaining, "post-create-state-not-confirmed")
        if not acknowledge_exclusive_writer_governance:
            return {"status": "incomplete", "changed": changed, "enrollment_complete": False,
                    "blockers": ["exclusive-writer-governance-attestation-required"], "binding_candidate": None}
        enrollment = verified["merged"]
        if single and state["actions"]:
            require(verified["repository_state"]["active"] == cloud.single_writer_enrollment_claim
                    and verified["repository_state"]["enrollment"] == (
                        state["repository_state"]["enrollment"] if state["repository_state"] else None),
                    "single-writer-enrollment-changed")
            cloud.read_only = False
            store.update(verified["repository_head"], verified["repository_state"], enrollment=enrollment, active=None)
        elif not single and (not verified["enrollment"] or enrollment != verified["enrollment"]["body"]):
            require((state["enrollment"] or {}).get("etag") == (verified["enrollment"] or {}).get("etag")
                    and (state["enrollment"] or {}).get("body") == (verified["enrollment"] or {}).get("body"),
                    "coordination-changed-replan-required")
            headers = {"x-ms-blob-type": "BlockBlob"}
            if verified["enrollment"]:
                require(verified["enrollment"]["etag"], "coordination-etag-required")
                headers["If-Match"] = verified["enrollment"]["etag"]
            else:
                headers["If-None-Match"] = "*"
            changed = True
            cloud.read_only = False
            cloud.storage("PUT", request["coordinates"]["coordination_blob"], data=enrollment, headers=headers, allowed=(201,))
        final = _snapshot(request, cloud)
        require(not final["actions"] and not final["blockers"] and final["enrollment"]
                and final["enrollment"]["body"] == enrollment, "final-enrollment-verification-failed")
        _fresh_request(request)
        return {"status": "changed" if changed else "unchanged", "changed": changed, "enrollment_complete": True,
                "binding_candidate": final["candidate"], "identity": final["identity"],
                **({"coordination_mode": "single-writer", "warnings": review["warnings"]} if single else {}),
                **({"lifecycle_protection": _lifecycle_protection(request)} if _common_mode(request) else {}),
                "publication_required": True, "runtime_ready": False}
    except (EnrollmentError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"status": "blocked", "changed": changed, "enrollment_complete": False,
                **({"lifecycle_protection": _lifecycle_protection(request)} if _common_mode(request) else {}),
                "reconciliation_required": changed,
                "error": exc.code if isinstance(exc, EnrollmentError) else "unexpected-response-reconciliation-required",
                "binding_candidate": None}
    finally:
        cloud.read_only = True
        cloud.serialized_provisioning = False
        if hasattr(cloud, "single_writer_enrollment_claim"):
            del cloud.single_writer_enrollment_claim


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "ensure"))
    parser.add_argument("--consumer-root", required=True)
    parser.add_argument("--factory-id", required=True)
    parser.add_argument("--scale-set-id", required=True)
    parser.add_argument("--environment", required=True, choices=("dev", "stage", "prod"))
    parser.add_argument("--options", required=True, help="Path to non-secret JSON options (closed schema in OPTIONS).")
    parser.add_argument("--expected-plan", help="Exact plan_hash SHA256 from a separate read-only plan.")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--acknowledge-exclusive-writer-governance", action="store_true",
                        help="Attest ALL writers enforce Blob leases, or exclusive repository/shared-hub governance in explicit single-writer mode.")
    args = parser.parse_args(argv)
    try:
        options = parse_json(Path(args.options).read_bytes())
        request = load_request(args.consumer_root, args.factory_id, args.scale_set_id, args.environment, options)
        kwargs = {"acknowledge_exclusive_writer_governance": args.acknowledge_exclusive_writer_governance}
        result = (plan(request, **kwargs) if args.command == "plan" else
                  ensure(request, args.expected_plan, yes=args.yes, **kwargs))
        print(canonical(result).decode("utf-8"))
        return 0 if (args.command == "plan" or result.get("enrollment_complete")) else 2
    except (EnrollmentError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(canonical({"status": "blocked", "enrollment_complete": False,
                         "error": exc.code if isinstance(exc, EnrollmentError) else "invalid-input-or-unavailable-file"}).decode())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
