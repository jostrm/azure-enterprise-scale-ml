"""Reviewed native dashboard stage for a retained connectivity hub, never a factory."""

from __future__ import annotations

import copy
import hashlib
import re
import shutil
import subprocess
import time
from uuid import uuid4

import factory_enrollment as enrollment
import hub_lock_foundation as foundation

CONTRACT_VERSION = 1
STAGE = "all-factories-dashboard"
TEMPLATE = "bootstrap/lib/all-factories-dashboard.bicep"
SOURCE_FILES = ("bootstrap/lib/all_factories_dashboard.py", TEMPLATE, *foundation.SOURCE_FILES)
DASHBOARD_API = "2020-09-01-preview"
DEPLOYMENT_API = "2022-09-01"
ordinary = foundation.ordinary
require = foundation.require
digest = enrollment.digest


def capabilities():
    return {"contract_version": CONTRACT_VERSION, "implemented_stages": [STAGE],
            "hub_dashboard": "reviewed-native-cost-drillthrough-v1",
            "requires_established_hub_coordination": True,
            "numeric_aggregation_supported": False}


def source_fingerprint(source_root):
    root = ordinary(source_root)
    files = {}
    for relative in SOURCE_FILES:
        path = ordinary(root / relative)
        require(path.is_file(), "dashboard-source-file-missing:" + relative)
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"kind": "reviewed-local-payload", "root": str(root),
            "published_ref_verified": False, "verification": "exact-local-file-bytes-only",
            "files": files, "payload_sha256": digest(files)}


def verify_source_snapshot(*, source_root, expected_payload_sha256):
    source = source_fingerprint(source_root)
    require(source["payload_sha256"] == expected_payload_sha256, "reviewed-source-payload-required")
    loaded = {SOURCE_FILES[0]: __file__, foundation.SOURCE_FILES[0]: foundation.__file__,
              foundation.SOURCE_FILES[1]: enrollment.__file__}
    require(all(hashlib.sha256(ordinary(path).read_bytes()).hexdigest() == source["files"][relative]
                for relative, path in loaded.items()), "loaded-dashboard-code-differs-from-reviewed-source")
    return source


def compile_template(path):
    """Use an existing compiler only; never install tools during privileged review."""
    bicep = shutil.which("bicep")
    require(bicep is not None, "existing-bicep-cli-required")
    result = subprocess.run([bicep, "build", str(path), "--stdout"], capture_output=True,
                            text=True, check=False, timeout=120)
    require(result.returncode == 0, "dashboard-bicep-compilation-failed:" + result.stderr)
    return enrollment.parse_json(result.stdout)


def _retained(value):
    return not any(key.lower() in ("aifactory.factory_id", "aifactory.scaleset_id")
                   for key in (value.get("tags") or {}))


def _owned_dashboard(value, identifier, rg):
    if value is None:
        return
    tags = value.get("tags") or {}
    require(str(value.get("id", "")).lower() == identifier and _retained(value)
            and tags.get("aifactory.dashboard") == "all-ai-factories-v1"
            and tags.get("aifactory.scope") == "connectivity-hub"
            and value.get("properties", {}).get("metadata", {}).get("allAiFactories", {}).get(
                "hubResourceGroupId", "").lower() == rg, "dashboard-ownership-conflict")


def prepare(*, source_root, tenant_id, hub_resource_group_id, location, selected_subscription_ids,
            expected_source_hash=None, runtime=None, compiler=None):
    """Read-only review after hub-lock-foundation; also used for every subsequent update."""
    require(isinstance(selected_subscription_ids, list) and 1 <= len(selected_subscription_ids) <= 100,
            "explicit-selected-subscriptions-required")
    subscriptions = sorted(enrollment.guid(value) for value in selected_subscription_ids)
    require(len(set(subscriptions)) == len(subscriptions), "duplicate-selected-subscriptions")
    require(isinstance(location, str) and re.fullmatch(r"[a-z0-9]{2,40}", location),
            "canonical-azure-location-required")
    rg = enrollment.rg_id(hub_resource_group_id)
    tenant = enrollment.guid(tenant_id)
    source = source_fingerprint(source_root)
    verify_source_snapshot(source_root=source_root,
                           expected_payload_sha256=expected_source_hash or source["payload_sha256"])
    target = {"tenant_id": tenant, "subscription_id": rg.split("/")[2]}
    coordinates = foundation.coordination(rg)
    runtime = runtime or foundation.Cloud(target, coordinates)
    runtime.read_only = True
    principal = enrollment.guid(runtime.principal())
    observations = []

    def read(identifier, api):
        status, _, value = runtime.arm("GET", identifier, api, allowed=(200, 404))
        require(status in (200, 404), "unexpected-dashboard-read-status")
        value = value if status == 200 else None
        observations.append({"id": identifier, "api": api, "value": copy.deepcopy(value)})
        return value

    group = read(rg, enrollment.RG_API)
    require(group is not None, "established-hub-resource-group-required")
    require(_retained(group), "dashboard-hub-resource-group-is-factory-owned")
    account = read(coordinates["account_id"], enrollment.STORAGE_API)
    require(account is not None, "established-hub-coordination-required")
    foundation.validate_shared_account(account, rg)
    container = coordinates["account_id"] + "/blobservices/default/containers/" + foundation.CONTAINER
    require(read(container, enrollment.STORAGE_API) is not None, "established-hub-container-required")
    require(runtime.blob("HEAD", allowed=(200,))[0] == 200, "authenticated-hub-data-plane-required")
    dashboard_id = rg + "/providers/microsoft.portal/dashboards/all-ai-factories"
    dashboard = read(dashboard_id, DASHBOARD_API)
    _owned_dashboard(dashboard, dashboard_id, rg)
    deployment_id = rg + "/providers/microsoft.resources/deployments/all-ai-factories"
    deployment = read(deployment_id, DEPLOYMENT_API)
    require(deployment is None or deployment.get("properties", {}).get("provisioningState") in (
        "Succeeded", "Failed", "Canceled"), "dashboard-deployment-in-progress-or-unknown")
    if deployment is not None:
        require(dashboard is not None, "dashboard-deployment-without-owned-dashboard-requires-reconciliation")
    compiled = (compiler or compile_template)(ordinary(source_root) / TEMPLATE)
    parameters = {"location": location, "selectedSubscriptionIds": subscriptions,
                  "sourcePayloadSha256": source["payload_sha256"]}
    body = {"properties": {"mode": "Incremental", "template": compiled,
                           "parameters": {key: {"value": value} for key, value in parameters.items()}}}
    plan = {
        "contract_version": CONTRACT_VERSION, "stage": STAGE, "plan_id": str(uuid4()),
        "prepared_at": time.time(), "expires_at": time.time() + 900, "source": source,
        "inputs": {"tenant_id": tenant, "hub_resource_group_id": rg, "location": location,
                   "selected_subscription_ids": subscriptions},
        "target": target, "principal_id": principal, "coordination": coordinates,
        "hub_resource_group_id": rg, "dashboard_id": dashboard_id, "lock_scopes": [rg],
        "observations": observations, "effects": [{"kind": "arm-deploy", "id": deployment_id,
            "api": DEPLOYMENT_API, "body": body, "ownership": "external-retain-never-enroll-or-delete"}],
        "auth_scopes": [{"scope": rg, "permissions": [
            "Microsoft.Resources/subscriptions/resourceGroups/read",
            "Microsoft.Storage/storageAccounts/read",
            "Microsoft.Storage/storageAccounts/blobServices/containers/read",
            "Microsoft.Portal/dashboards/read",
            "Microsoft.Portal/dashboards/write", "Microsoft.Resources/deployments/read",
            "Microsoft.Resources/deployments/write"]},
            {"scope": container, "role_definition_id": enrollment.DATA_ROLE, "authentication": "Entra-OAuth-only"}],
        "can_execute": True, "blockers": [], "numeric_aggregation_supported": False,
        "warnings": ["Reviewed incremental PUT retains one stable dashboard; it is not a factory-owned resource.",
                     "Serialize manual writers too; ARM has no verified atomic compare-and-swap for this deployment.",
                     "No cost role grants, Python API calls, financial totals or forecasts are embedded in this dashboard."],
    }
    plan["commands"] = [
        {"transport": "arm", "method": "PUT", "resource_id": deployment_id,
         "api_version": DEPLOYMENT_API, "body": copy.deepcopy(body),
         "purpose": "reviewed-dashboard-deployment"},
        {"transport": "storage", "method": "PUT", "container": foundation.CONTAINER,
         "blob": "bootstrap/dashboard/" + plan["plan_id"] + ".json",
         "precondition": "create If-None-Match:*; subsequent updates If-Match:<observed-etag>",
         "purpose": "durable-operation-evidence"},
        {"transport": "storage", "method": "PUT", "container": foundation.CONTAINER,
         "blob": foundation.lock_blob(rg), "precondition": "If-None-Match:*",
         "purpose": "retain-existing-lock-blob"},
        {"transport": "storage", "method": "PUT", "container": foundation.CONTAINER,
         "blob": foundation.lock_blob(rg), "query": "comp=lease",
         "actions": ["acquire-infinite", "renew-own", "release-own-only-after-verification"],
         "purpose": "serialize-reviewed-hub-update"},
    ]
    plan["plan_hash"] = digest(plan)
    return plan


def _same_review(plan, fresh):
    for key in ("source", "inputs", "target", "principal_id", "coordination", "hub_resource_group_id",
                "dashboard_id", "lock_scopes", "observations", "effects", "auth_scopes"):
        require(plan[key] == fresh[key], "dashboard-live-state-or-plan-changed:" + key)


def validate_receipt(receipt, plan):
    verified = receipt.get("verified_dashboard") if isinstance(receipt, dict) else None
    require(isinstance(receipt, dict) and receipt.get("status") == "succeeded"
            and receipt.get("stage") == STAGE and receipt.get("contract_version") == CONTRACT_VERSION
            and receipt.get("plan_id") == plan["plan_id"] and receipt.get("plan_hash") == plan["plan_hash"]
            and receipt.get("source") == plan["source"] and receipt.get("inputs") == plan["inputs"]
            and receipt.get("dashboard_id") == plan["dashboard_id"]
            and receipt.get("hub_resource_group_id") == plan["hub_resource_group_id"]
            and receipt.get("principal_id") == plan["principal_id"]
            and receipt.get("coordination") == plan["coordination"]
            and receipt.get("leases") == {} and receipt.get("reconciliation_required") is False
            and isinstance(verified, dict) and bool(verified)
            and receipt.get("verified_dashboard_sha256") == digest(verified)
            and receipt.get("effects_completed") == [0], "dashboard-receipt-not-verified")
    metadata = verified.get("properties", {}).get("metadata", {}).get("allAiFactories", {})
    require(verified.get("location") == plan["inputs"]["location"]
            and metadata.get("hubResourceGroupId") == plan["hub_resource_group_id"]
            and metadata.get("sourcePayloadSha256") == plan["source"]["payload_sha256"]
            and metadata.get("selectedSubscriptionIds") == plan["inputs"]["selected_subscription_ids"]
            and metadata.get("numericAggregationSupported") is False,
            "dashboard-receipt-scope-not-verified")
    return receipt


def execute(plan, *, state_dir, expected_plan_hash, runtime=None, compiler=None, sleep=time.sleep):
    require(isinstance(plan, dict) and plan.get("stage") == STAGE
            and plan.get("contract_version") == CONTRACT_VERSION and plan.get("can_execute") is True
            and not plan.get("blockers") and plan.get("plan_hash") == expected_plan_hash
            and digest({key: value for key, value in plan.items() if key != "plan_hash"}) == expected_plan_hash,
            "dashboard-plan-hash-mismatch")
    require(plan["prepared_at"] <= time.time() < plan["expires_at"], "dashboard-review-expired")
    verify_source_snapshot(source_root=plan["source"]["root"],
                           expected_payload_sha256=plan["source"]["payload_sha256"])
    runtime = runtime or foundation.Cloud(plan["target"], plan["coordination"])

    def fresh():
        return prepare(source_root=plan["source"]["root"], expected_source_hash=plan["source"]["payload_sha256"],
                       **plan["inputs"], runtime=runtime, compiler=compiler)

    _same_review(plan, fresh())
    folder = ordinary(state_dir)
    require(folder.is_dir(), "durable-existing-state-directory-required")
    receipt_path = ordinary(folder / (enrollment.guid(plan["plan_id"]) + ".json"))
    guard = ordinary(folder / ("hub-dashboard-" + digest(plan["hub_resource_group_id"]) + ".claim"))
    receipt = {key: copy.deepcopy(plan[key]) for key in (
        "contract_version", "stage", "plan_id", "plan_hash", "source", "inputs", "dashboard_id",
        "hub_resource_group_id", "principal_id", "coordination")}
    receipt.update(status="uncertain", reconciliation_required=True, leases={}, effects_completed=[],
                   receipt_path=str(receipt_path), guard_path=str(guard))
    with receipt_path.open("xb") as stream:
        stream.write(enrollment.canonical(receipt))
    with guard.open("xb") as stream:
        stream.write(enrollment.canonical({"plan_id": plan["plan_id"], "receipt_path": str(receipt_path)}))
    remote = "bootstrap/dashboard/" + plan["plan_id"] + ".json"
    remote_etag = None

    def persist():
        nonlocal remote_etag
        foundation._persist(receipt_path, receipt)
        runtime.read_only = False
        headers = {"x-ms-blob-type": "BlockBlob"}
        headers.update({"If-Match": remote_etag} if remote_etag else {"If-None-Match": "*"})
        _, result, _ = runtime.blob("PUT", remote, data=receipt, headers=headers, allowed=(201,))
        require(result.get("etag"), "dashboard-proof-etag-required")
        remote_etag = result["etag"]

    blob = foundation.lock_blob(plan["hub_resource_group_id"])
    lease = str(uuid4())
    runtime.read_only = False
    try:
        persist()
        runtime.blob("PUT", blob, data=b"", headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"},
                     allowed=(201, 412))
        receipt["leases"][plan["hub_resource_group_id"]] = lease
        persist()
        runtime.blob("PUT", blob, headers={"x-ms-lease-action": "acquire", "x-ms-lease-duration": "-1",
                     "x-ms-proposed-lease-id": lease}, query="?comp=lease", allowed=(201,))
        _same_review(plan, fresh())
        runtime.read_only = False
        require(time.time() < plan["expires_at"], "dashboard-review-expired")
        runtime.blob("PUT", blob, headers={"x-ms-lease-action": "renew", "x-ms-lease-id": lease},
                     query="?comp=lease", allowed=(200,))
        receipt["pending_effect"] = 0
        persist()
        effect = plan["effects"][0]
        runtime.arm("PUT", effect["id"], effect["api"], data=effect["body"], allowed=(200, 201, 202))
        deployed = foundation._wait(runtime, effect["id"], effect["api"], sleep)
        outputs = deployed.get("properties", {}).get("outputs", {})
        desired = outputs.get("desiredDashboard", {}).get("value")
        require(isinstance(desired, dict) and str(outputs.get("dashboardId", {}).get("value", "")).lower()
                == plan["dashboard_id"], "dashboard-deployment-outputs-not-verified")
        _, _, observed = runtime.arm("GET", plan["dashboard_id"], DASHBOARD_API)
        _owned_dashboard(observed, plan["dashboard_id"], plan["hub_resource_group_id"])
        require(foundation._contains(observed, desired), "dashboard-deployed-state-not-verified")
        metadata = observed["properties"]["metadata"]["allAiFactories"]
        require(metadata.get("sourcePayloadSha256") == plan["source"]["payload_sha256"]
                and metadata.get("selectedSubscriptionIds") == plan["inputs"]["selected_subscription_ids"]
                and metadata.get("numericAggregationSupported") is False, "dashboard-scope-not-verified")
        receipt["verified_dashboard_sha256"] = digest(desired)
        receipt["verified_dashboard"] = copy.deepcopy(desired)
        receipt["effects_completed"] = [0]
        receipt.pop("pending_effect")
        persist()
        runtime.blob("PUT", blob, headers={"x-ms-lease-action": "release", "x-ms-lease-id": lease},
                     query="?comp=lease", allowed=(200,))
        receipt.update(leases={}, status="succeeded", reconciliation_required=False)
        persist()
        validate_receipt(receipt, plan)
        guard.unlink()
        return receipt
    except BaseException as exc:
        receipt.update(status="uncertain", reconciliation_required=True,
                       error=getattr(exc, "code", "dashboard-execution-interrupted"))
        foundation._persist(receipt_path, receipt)
        if remote_etag:
            try:
                persist()
            except Exception:
                pass
        if not isinstance(exc, Exception):
            raise
        return receipt
    finally:
        runtime.read_only = True
