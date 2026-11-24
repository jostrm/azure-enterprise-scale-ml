"""Purple gap #18: system-created children that ARM what-if reports as Ignore (2026-11-24).

Pipelines-only Scenario 1 on aif67 (ADO run 2520) deployed COMMON, then the project001 continuation stopped in
Prepare with ignored-resource-requires-exact-instance-proof: the per-step what-if reports children no step
template declares (private DNS SOA/@ and zone-group A records, built-in Log Analytics tables, Key Vault secrets)
as Ignore. Prepare now proves each such instance inside the plan's own step resource groups by its body hash;
Execute re-reads it before the re-preview. Anything outside the plan's groups still blocks.
"""

import copy
import json
import sys
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import (
    fl, ROOT, GROUP, COMMON, RESOURCE, RESOURCE_BODY, SUB, PlanCloud, scoped_manifest, seal, simple_plan_closure,
)

sys.path.insert(0, str(ROOT / "bootstrap" / "lib"))

ZONE = GROUP + "/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
SOA = ZONE + "/SOA/@"
SOA_BODY = {"id": SOA, "name": "@", "type": "Microsoft.Network/privateDnsZones/SOA", "etag": "soa-1",
            "properties": {"ttl": 3600, "fqdn": "privatelink.vaultcore.azure.net.",
                           "soaRecord": {"host": "azureprivatedns.net", "serialNumber": 1}}}
WORKSPACE = GROUP + "/providers/Microsoft.OperationalInsights/workspaces/law-common"
TABLES = [WORKSPACE + "/tables/AzureActivity", WORKSPACE + "/tables/AzureDiagnostics"]
OUTSIDE_SOA = COMMON + "/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net/SOA/@"
FOREIGN_SOA = ("/subscriptions/" + SUB + "/resourceGroups/someone-else/providers/Microsoft.Network/privateDnsZones/"
               "privatelink.blob.core.windows.net/SOA/@")
SCHEMAS = {
    "microsoft.network": [{"resourceType": "privateDnsZones", "apiVersions": ["2024-06-01", "2020-06-01"]},
                          {"resourceType": "privateDnsZones/SOA",
                           "apiVersions": ["2025-01-01-preview", "2024-06-01", "2020-06-01"]}],
    "microsoft.operationalinsights": [{"resourceType": "workspaces/tables",
                                       "apiVersions": ["2023-09-01", "2022-10-01"]}],
}


@pytest.fixture(autouse=True)
def no_real_services(monkeypatch):
    monkeypatch.setattr(fl.subprocess, "run", Mock(side_effect=AssertionError("Real commands forbidden")))
    monkeypatch.setattr(fl, "build_opener", Mock(side_effect=AssertionError("Real HTTP forbidden")))


def ignore_row(identifier, body=None):
    return {"resourceId": identifier, "changeType": "Ignore", "before": copy.deepcopy(body), "after": None}


class IgnoreCloud(PlanCloud):
    """A what-if that also reports system children as Ignore; they live outside the inventory closure."""

    def __init__(self, document, templates, rows=(), children=None, schemas=None):
        super().__init__(document, templates)
        self.rows = list(rows)
        self.children = {key.lower(): copy.deepcopy(value) for key, value in (children or {}).items()}
        self.schemas = copy.deepcopy(SCHEMAS if schemas is None else schemas)
        self.child_reads, self.collections, self.schema_reads = [], [], []
        self.unserved = set()

    def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
        if url.startswith(fl.ARM) and "/whatIf?" in url:
            status, response_headers, body = super().request(method, url, audience, data, headers, allowed)
            body["properties"]["changes"] += copy.deepcopy(self.rows)
            return status, response_headers, body
        return super().request(method, url, audience, data, headers, allowed)

    def provider_schema(self, namespace):
        self.schema_reads.append(namespace.lower())
        return {"resourceTypes": copy.deepcopy(self.schemas.get(namespace.lower(), []))}

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        key = resource_id.lower()
        if method == "GET" and (key in self.children or "/privatednszones/" in key):
            self.child_reads.append((key, api_version))
            if api_version in self.unserved:
                raise fl.ApiVersionNotServed("remote-request-failed-400")
            if key not in self.children:
                assert 404 in allowed
                return 404, {}, None
            return 200, {}, copy.deepcopy(self.children[key])
        return super().arm(method, resource_id, api_version, allowed, headers)

    def collection(self, path, api_version, *, extension=False):
        self.collections.append((path.lower(), api_version))
        prefix = path.lower().rstrip("/") + "/"
        return sorted((copy.deepcopy(body) for key, body in self.children.items()
                       if key.startswith(prefix) and "/" not in key[len(prefix):]),
                      key=lambda row: row["id"].lower()), None


def table_body(identifier, retention=30, schema_version=1):
    return {"id": identifier, "name": identifier.rsplit("/", 1)[-1],
            "properties": {"retentionInDays": retention, "plan": "Analytics",
                           "schema": {"name": identifier.rsplit("/", 1)[-1], "version": schema_version}}}


def frozen(cloud, document):
    document["deployment"] = fl._freeze_deployment_contents(cloud, document, ROOT)
    return seal(document)


def soa_case(rows=None, children=None, schemas=None):
    document, templates = scoped_manifest()
    cloud = IgnoreCloud(document, templates, [ignore_row(SOA, SOA_BODY)] if rows is None else rows,
                        {SOA: SOA_BODY} if children is None else children, schemas)
    return document, cloud


def test_ignore_row_under_the_plans_own_group_is_proven_at_prepare_and_passes_review():
    document, cloud = soa_case()
    frozen(cloud, document)
    kind = "microsoft.network/privatednszones/soa"
    proof = {"api_version": "2024-06-01", "body_hash": fl.resource_digest(SOA_BODY, kind)}
    assert document["deployment"]["ignored_instances"] == {SOA.lower(): proof}
    # Newest stable version from the provider schema, never the preview.
    assert cloud.child_reads == [(SOA.lower(), "2024-06-01")]
    assert {"resource_id": SOA.lower(), "change_type": "NoChange", "before_hash": proof["body_hash"],
            "after_hash": proof["body_hash"]} in document["deployment"]["changes"]
    assert fl.validate_manifest(document) == document
    # The proof is what arm_changes accepts, exactly like the existing body-hash proofs.
    rows = fl.arm_changes({"properties": {"changes": [ignore_row(SOA, SOA_BODY)]}},
                          document["deployment"]["ignored_instances"])
    assert rows == [{"resource_id": SOA.lower(), "change_type": "NoChange",
                     "before_hash": proof["body_hash"], "after_hash": proof["body_hash"]}]


@pytest.mark.parametrize("outside", [OUTSIDE_SOA, FOREIGN_SOA], ids=["common-dependency", "foreign-group"])
def test_ignore_row_outside_the_plans_own_groups_still_blocks_and_is_never_read(outside):
    document, cloud = soa_case(rows=[ignore_row(outside, SOA_BODY)], children={outside: SOA_BODY})
    with pytest.raises(fl.Blocked, match="ignored-resource-requires-exact-instance-proof"):
        fl._freeze_deployment_contents(cloud, document, ROOT)
    assert cloud.child_reads == []


def test_ignore_row_that_cannot_be_read_still_blocks():
    document, cloud = soa_case(children={})
    with pytest.raises(fl.Blocked, match="ignored-resource-requires-exact-instance-proof"):
        fl._freeze_deployment_contents(cloud, document, ROOT)
    assert cloud.child_reads == [(SOA.lower(), "2024-06-01")]


@pytest.mark.parametrize("schemas,expected", [
    ({"microsoft.network": [{"resourceType": "privateDnsZones/SOA", "apiVersions": ["2025-01-01-preview"]}]},
     "2025-01-01-preview"),
    ({"microsoft.network": [{"resourceType": "privateDnsZones", "apiVersions": ["2024-06-01", "2020-06-01"]}]},
     "2024-06-01"),
], ids=["preview-fallback", "parent-type-fallback"])
def test_ignored_instance_api_version_falls_back_to_preview_then_to_the_parent_type(schemas, expected):
    document, cloud = soa_case(schemas=schemas)
    frozen(cloud, document)
    assert cloud.child_reads == [(SOA.lower(), expected)]
    assert document["deployment"]["ignored_instances"][SOA.lower()]["api_version"] == expected


def test_an_unserved_schema_api_version_falls_back_to_older_stable_ones_and_freezes_the_served_one():
    # aif-128 2026-10-26: swedencentral answered a schema-advertised Microsoft.Network version with a 400.
    document, cloud = soa_case()
    cloud.unserved = {"2024-06-01"}
    frozen(cloud, document)
    assert cloud.child_reads == [(SOA.lower(), "2024-06-01"), (SOA.lower(), "2020-06-01")]
    assert document["deployment"]["ignored_instances"][SOA.lower()]["api_version"] == "2020-06-01"


def test_a_frozen_api_version_never_falls_back_at_execute():
    document, cloud = soa_case()
    frozen(cloud, document)
    cloud.child_reads.clear()
    cloud.unserved = {"2024-06-01"}
    with pytest.raises(fl.Blocked, match="remote-request-failed-400"):
        fl.verify_ignored_instances(cloud, document)
    assert cloud.child_reads == [(SOA.lower(), "2024-06-01")]


def test_listed_only_log_analytics_tables_are_proven_from_one_list_of_their_workspace():
    tables = {identifier: table_body(identifier) for identifier in TABLES}
    document, cloud = soa_case(rows=[ignore_row(identifier, body) for identifier, body in tables.items()],
                               children=tables)
    frozen(cloud, document)
    kind = "microsoft.operationalinsights/workspaces/tables"
    assert cloud.collections == [((WORKSPACE + "/tables").lower(), "2023-09-01")]
    assert document["deployment"]["ignored_instances"] == {
        identifier.lower(): {"api_version": "2023-09-01", "body_hash": fl.resource_digest(body, kind)}
        for identifier, body in tables.items()}


def test_plan_without_ignore_rows_freezes_no_ignored_instances_key():
    document, cloud = soa_case(rows=[], children={})
    frozen(cloud, document)
    assert "ignored_instances" not in document["deployment"]
    assert cloud.child_reads == [] and cloud.schema_reads == []


def test_plan_without_ignored_instances_keeps_todays_review_and_reads_nothing():
    document, cloud = soa_case(rows=[], children={})
    frozen(cloud, document)
    assert fl.validate_manifest(document) == document
    # Outside Prepare an unproven Ignore row blocks exactly as before, and nothing is read to prove it.
    cloud.rows = [ignore_row(SOA, SOA_BODY)]
    cloud.children = {SOA.lower(): copy.deepcopy(SOA_BODY)}
    with pytest.raises(fl.Blocked, match="ignored-resource-requires-exact-instance-proof"):
        fl.plan_what_if(cloud, document, ROOT, {"id": "factory", "scope": "subscription"})
    assert cloud.child_reads == []
    fl.verify_ignored_instances(cloud, document)
    assert cloud.child_reads == []


@pytest.mark.parametrize("change", [
    lambda proofs: "not-a-dict",
    lambda proofs: {key.upper().replace("/SUBSCRIPTIONS/", "/subscriptions/"): value for key, value in proofs.items()},
    lambda proofs: {key: {**value, "body_hash": "f" * 63} for key, value in proofs.items()},
    lambda proofs: {key: {**value, "body_hash": value["body_hash"].upper()} for key, value in proofs.items()},
    lambda proofs: {key: {**value, "api_version": 20240601} for key, value in proofs.items()},
    lambda proofs: {key: {"body_hash": value["body_hash"]} for key, value in proofs.items()},
    lambda proofs: {key: {**value, "owner": "factory-a"} for key, value in proofs.items()},
    lambda proofs: {key: "f" * 64 for key in proofs},
    lambda proofs: {OUTSIDE_SOA.lower(): value for value in proofs.values()},
    lambda proofs: {GROUP.lower(): value for value in proofs.values()},
], ids=["not-dict", "uppercase-id", "short-hash", "uppercase-hash", "api-not-str", "api-missing", "extra-field",
        "proof-not-dict", "outside-step-groups", "resource-group-id"])
def test_malformed_ignored_instances_fail_plan_validation(change):
    document, cloud = soa_case()
    frozen(cloud, document)
    document["deployment"]["ignored_instances"] = change(document["deployment"]["ignored_instances"])
    with pytest.raises(fl.Blocked, match="invalid-ignored-instance-proof"):
        fl.validate_manifest(seal(document))


def run_worker(document, cloud):
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    seal(document)
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    locks.claim_run()
    return fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
                                    ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())


@pytest.fixture
def offline_worker(monkeypatch):
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)


def test_unchanged_ignored_instance_is_reread_at_execute_and_the_run_deploys(offline_worker):
    document, cloud = soa_case()
    frozen(cloud, document)
    cloud.child_reads.clear()
    result = run_worker(document, cloud)
    assert result["status"] == "succeeded", result.get("error_code")
    # Re-read with the api-version frozen at Prepare, before the re-preview.
    assert cloud.child_reads == [(SOA.lower(), "2024-06-01")]
    assert len(cloud.arm_writes) == 1


@pytest.mark.parametrize("drift", ["changed", "deleted"])
def test_ignored_instance_changed_since_prepare_fails_before_any_write(offline_worker, drift):
    document, cloud = soa_case()
    frozen(cloud, document)
    if drift == "changed":
        cloud.children[SOA.lower()]["properties"]["ttl"] = 60
    else:
        del cloud.children[SOA.lower()]
    result = run_worker(document, cloud)
    assert result["status"] == "reconciliation-required"
    assert result["error_code"] == "ignored-instance-changed-since-prepare"
    assert not cloud.arm_writes


def test_changed_listed_only_table_fails_at_execute(offline_worker):
    tables = {identifier: table_body(identifier) for identifier in TABLES}
    document, cloud = soa_case(rows=[ignore_row(identifier, body) for identifier, body in tables.items()],
                               children=tables)
    frozen(cloud, document)
    # A centrally updated table schema is volatile and never counts; a retention change does.
    cloud.children[TABLES[0].lower()]["properties"]["schema"]["version"] = 2
    fl.verify_ignored_instances(cloud, document)
    cloud.children[TABLES[1].lower()]["properties"]["retentionInDays"] = 90
    with pytest.raises(fl.Blocked, match="ignored-instance-changed-since-prepare"):
        fl.verify_ignored_instances(cloud, document)


# Purple gap #19 (aif68, ADO run 2526, 2026-11-24): the project001 continuation's per-step what-if lists the plan's own
# common resource group itself as Ignore (its subscription-scope steps deploy into it, none declares it); its 72
# nested Ignore rows were all proven, the group was not. The group is proven by its own body hash under a separate
# `ignored_groups` key, so an RG id among the instance proofs stays invalid.
GROUP_KIND = "microsoft.resources/resourcegroups"


class GroupIgnoreCloud(IgnoreCloud):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_reads = []

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "GET" and fl.RG_ID.fullmatch(resource_id):
            self.group_reads.append((resource_id.lower(), api_version))
        return super().arm(method, resource_id, api_version, allowed, headers)


def group_case():
    document, templates = scoped_manifest()
    cloud = GroupIgnoreCloud(document, templates, [], {})
    body = copy.deepcopy(cloud.bodies[GROUP.lower()])
    cloud.rows = [ignore_row(GROUP, body), ignore_row(SOA, SOA_BODY)]
    cloud.children = {SOA.lower(): copy.deepcopy(SOA_BODY)}
    return document, cloud, body


def test_ignore_row_of_the_plans_own_resource_group_is_proven_by_its_body_at_prepare():
    document, cloud, body = group_case()
    frozen(cloud, document)
    proof = {"api_version": fl.RG_API, "body_hash": fl.resource_digest(body, GROUP_KIND)}
    assert document["deployment"]["ignored_groups"] == {GROUP.lower(): proof}
    # The nested row keeps its instance proof; the group never joins the instance proofs.
    assert set(document["deployment"]["ignored_instances"]) == {SOA.lower()}
    assert cloud.group_reads.count((GROUP.lower(), fl.RG_API)) >= 1
    assert {"resource_id": GROUP.lower(), "change_type": "NoChange", "before_hash": proof["body_hash"],
            "after_hash": proof["body_hash"]} in document["deployment"]["changes"]
    assert fl.validate_manifest(document) == document


@pytest.mark.parametrize("outside", [COMMON, "/subscriptions/" + SUB + "/resourceGroups/someone-else"],
                         ids=["common-dependency", "foreign-group"])
def test_ignore_row_of_a_group_outside_the_plans_own_groups_still_blocks_and_is_never_read(outside):
    document, cloud, body = group_case()
    cloud.rows = [ignore_row(outside, {**body, "id": outside})]
    with pytest.raises(fl.Blocked, match="ignored-resource-requires-exact-instance-proof"):
        fl._freeze_deployment_contents(cloud, document, ROOT)
    assert (outside.lower(), fl.RG_API) not in cloud.group_reads


def test_changed_ignored_group_fails_at_execute_and_unchanged_passes():
    document, cloud, _ = group_case()
    frozen(cloud, document)
    cloud.group_reads.clear()
    fl.verify_ignored_instances(cloud, document)
    # Re-read at the frozen api-version, before the re-preview.
    assert cloud.group_reads == [(GROUP.lower(), fl.RG_API)]
    cloud.bodies[GROUP.lower()]["tags"] = {"changed": "yes"}
    with pytest.raises(fl.Blocked, match="ignored-instance-changed-since-prepare"):
        fl.verify_ignored_instances(cloud, document)


def test_proven_ignored_group_passes_the_execute_re_preview(offline_worker):
    document, cloud, _ = group_case()
    frozen(cloud, document)
    result = run_worker(document, cloud)
    assert result["status"] == "succeeded", result.get("error_code")
    assert len(cloud.arm_writes) == 1


@pytest.mark.parametrize("change", [
    lambda proofs: "not-a-dict",
    lambda proofs: {SOA.lower(): value for value in proofs.values()},
    lambda proofs: {COMMON.lower(): value for value in proofs.values()},
    lambda proofs: {GROUP: value for value in proofs.values()},
    lambda proofs: {key: {**value, "api_version": "2024-06-01"} for key, value in proofs.items()},
    lambda proofs: {key: {**value, "body_hash": "f" * 63} for key, value in proofs.items()},
    lambda proofs: {key: {**value, "owner": "factory-a"} for key, value in proofs.items()},
], ids=["not-dict", "nested-id", "outside-step-groups", "not-lowercase", "other-api-version", "short-hash",
        "extra-field"])
def test_malformed_ignored_groups_fail_plan_validation(change):
    document, cloud, _ = group_case()
    frozen(cloud, document)
    document["deployment"]["ignored_groups"] = change(document["deployment"]["ignored_groups"])
    with pytest.raises(fl.Blocked, match="invalid-ignored-instance-proof"):
        fl.validate_manifest(seal(document))


def test_unproven_ignore_rows_are_named_with_their_types_in_the_refusal_and_the_log(capsys):
    # Every failed continuation forces a fresh factory (bug #16): the refusal must say which rows were unproven.
    foreign = "/subscriptions/" + SUB + "/resourceGroups/someone-else"
    rows = [ignore_row(OUTSIDE_SOA, SOA_BODY), ignore_row(foreign), ignore_row(SOA, SOA_BODY),
            {"resourceId": "not-an-arm-id", "changeType": "Ignore"}]
    with pytest.raises(fl.Blocked, match="ignored-resource-requires-exact-instance-proof") as raised:
        fl.arm_changes({"properties": {"changes": rows}}, {})
    expected = {"unproven_ignored": {OUTSIDE_SOA.lower(): "microsoft.network/privatednszones/soa",
                                     SOA.lower(): "microsoft.network/privatednszones/soa",
                                     foreign.lower(): GROUP_KIND},
                "count": 4}
    assert raised.value.error_diagnostic == expected
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")]
    assert {"event": "ignored-resource-unproven", **expected} in events


def test_unproven_ignore_diagnostic_is_bounded_and_drops_unsafe_values():
    many = [ignore_row(GROUP + "/providers/Microsoft.KeyVault/vaults/kv/secrets/s" + str(index)) for index in range(40)]
    with pytest.raises(fl.Blocked) as raised:
        fl.arm_changes({"properties": {"changes": many}}, {})
    detail = raised.value.error_diagnostic
    assert detail["count"] == 40 and len(detail["unproven_ignored"]) == 32
    assert set(detail["unproven_ignored"].values()) == {"microsoft.keyvault/vaults/secrets"}
    assert fl.safe_instance_diagnostic("ignored-resource-requires-exact-instance-proof",
                                       {"unproven_ignored": {"https://evil": "x"}, "count": 1}) is None
    assert fl.safe_instance_diagnostic("other-code", detail) is None


def test_a_proven_ignore_row_never_reaches_the_refusal_and_order_of_checks_is_kept():
    proofs = {SOA.lower(): {"body_hash": fl.resource_digest(SOA_BODY)}}
    unsupported = {"resourceId": RESOURCE, "changeType": "Unsupported", "unsupportedReason": "unknown"}
    # A destructive or unresolved row before an unproven Ignore row still answers with its own code.
    with pytest.raises(fl.Blocked, match="unresolved-or-destructive-arm-what-if"):
        fl.arm_changes({"properties": {"changes": [unsupported, ignore_row(OUTSIDE_SOA)]}}, proofs)
    assert fl.arm_changes({"properties": {"changes": [ignore_row(SOA, SOA_BODY)]}}, proofs)[0]["change_type"] == "NoChange"
