"""Offline factory teardown: no authentication, commands, pipelines or ARM writes."""

import copy
import base64
import json
import zlib
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import fl, GROUP, COMMON, OWNER, RESOURCE, ROOT, manifest, seal, workspace, no_real_services
from .test_selective_project_deletion import prepared, PROJECT, SUBNET, SHARED_SUBNET, VNET, tagged


def factory_prepared():
    document, cloud = prepared(True, True)
    document.pop("deletion_scope")
    document.pop("reviewed_scope")
    document["route"].update(scoped_contract=1, auth_namespace="factory-stage",
                             runner={"kind": "hosted", "os": "linux", "image": "ubuntu-latest"})
    document["identity"]["deployment_object_id"] = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    cloud.enrollment["writers"]["writer-a"].update(
        auth_namespace=document["route"]["auth_namespace"], runner=document["route"]["runner"],
        deployment_object_id=document["identity"]["deployment_object_id"])
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    common_ip = COMMON + "/providers/Microsoft.Network/publicIPAddresses/common-ip"
    cloud.bodies[common_ip.lower()] = tagged(
        common_ip, "Microsoft.Network/publicIPAddresses", {key: value for key, value in OWNER.items() if key != "project_id"})
    projects = [{"project_id": PROJECT, "project_number": "017", "registered_resource_ids": [GROUP, SUBNET]}]
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    return seal(document), cloud, projects


def runtime():
    return fl.factory_deletion_module()


def row(name, kind, dependencies=()):
    identifier = GROUP + "/providers/" + kind + "/" + name
    return {"id": identifier,
            "type": fl.resource_type_from_id(identifier), "delete": True, "depends_on": list(dependencies),
            "owner": copy.deepcopy(OWNER), "api_version": "2024-05-01", "etag": None}


def test_published_capability_names_the_pipeline_contract():
    assert fl.capabilities()["factory_deletion_pipeline"] == "ordered-project-pipelines-v1"


@pytest.mark.parametrize("bad", [False, "true", "True", 1, None])
def test_all_four_flags_require_actual_booleans(bad):
    module = runtime()
    flags = dict.fromkeys(module.DELETE_FLAGS, True)
    module.validate_flags(flags)
    for name in module.DELETE_FLAGS:
        with pytest.raises(fl.Blocked, match="factory-delete-flags-must-all-be-true"):
            module.validate_flags({**flags, name: bad})


def test_order_caphost_links_managed_services_network_and_group_last():
    module = runtime()
    rows = [
        row("ip", "Microsoft.Network/publicIPAddresses"),
        row("database", "Microsoft.DocumentDB/databaseAccounts"),
        row("link", "Microsoft.Search/services/search/sharedPrivateLinkResources"),
        row("host", "Microsoft.CognitiveServices/accounts/account/capabilityHosts"),
        {"id": GROUP, "delete": True, "depends_on": [], "owner": OWNER},
    ]
    ordered = module.ordered_resources(rows)
    assert [entry["id"] for entry in ordered] == [rows[n]["id"] for n in (3, 2, 1, 0, 4)]


def test_dependency_conflicting_with_service_teardown_order_blocks():
    module = runtime()
    network = row("ip", "Microsoft.Network/publicIPAddresses")
    host = row("host", "Microsoft.CognitiveServices/accounts/account/capabilityHosts")
    network["depends_on"] = [host["id"]]
    with pytest.raises(fl.Blocked, match="factory-delete-phase-dependency-conflict"):
        module.ordered_resources([host, network])


def test_successful_provider_run_requires_bound_worker_deletion_evidence():
    module = runtime()
    document = manifest()
    document["deletion"]["inventory_mode"] = module.CONTRACT
    document["deletion"]["projects"] = [{"project_id": "logical-id", "project_number": "017"}]
    document["deletion"]["flags"] = dict.fromkeys(module.DELETE_FLAGS, True)
    document["deletion"]["resources"][0]["project_number"] = "017"
    result = {"schema": 1, "status": "succeeded", "run_id": document["run_id"],
              "manifest_hash": document["manifest_hash"], "source_commit": document["source"]["commit"],
              "target": document["target"], "deleted_resources": [RESOURCE],
              "flags": document["deletion"]["flags"], "project_numbers": ["017"]}
    result["projects"] = module.completed_projects(document)
    module.verify_worker_result(document, result)
    for field, value in (("status", "failed"), ("deleted_resources", []),
                         ("flags", {}), ("project_numbers", [])):
        with pytest.raises(fl.Blocked):
            module.verify_worker_result(document, {**result, field: value})


def test_uncertain_dispatch_must_never_be_redispatched():
    module = runtime()
    document = manifest()
    receipt = {"pending_dispatch": {"kind": "ado", "pipeline_id": 7}}
    cloud, locks = Mock(), Mock(spec=fl.BlobLocks)
    with pytest.raises(fl.Blocked, match="factory-delete-dispatch-reconciliation-required"):
        module.resume_dispatch(cloud, locks, document, receipt, Mock(), lambda _: None)
    cloud.request.assert_not_called()


def test_completed_ado_run_is_observed_not_redispatched():
    module = runtime()
    document = manifest()
    receipt = {"remote_run": {"kind": "ado", "pipeline_id": 7, "run_id": 99}}
    cloud, locks = Mock(), Mock(spec=fl.BlobLocks)
    cloud.request.return_value = (200, {}, {
        "id": 99, "pipeline": {"id": 7}, "state": "completed", "result": "succeeded",
        "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}})
    assert module.resume_dispatch(cloud, locks, document, receipt, Mock(), lambda _: None) is True
    assert all(call.args[0] == "GET" for call in cloud.request.call_args_list)
    assert receipt["remote_terminal"] is True


@pytest.mark.parametrize("state,result", [("completed", "failed"), ("completed", "canceled"),
                                         ("unknown", None)])
def test_unsuccessful_ado_run_cannot_unlock_common_deletion(state, result):
    module = runtime()
    document = manifest()
    receipt = {"remote_run": {"kind": "ado", "pipeline_id": 7, "run_id": 99}}
    cloud = Mock()
    cloud.request.return_value = (200, {}, {
        "id": 99, "pipeline": {"id": 7}, "state": state, "result": result,
        "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}})
    with pytest.raises(fl.Blocked):
        module.resume_dispatch(cloud, Mock(spec=fl.BlobLocks), document, receipt, Mock(), lambda _: None)


def test_prepare_freezes_project_flags_and_retains_shared_network():
    document, cloud, _ = factory_prepared()
    fl.validate_manifest(document)
    rows = {row["id"].lower(): row for row in document["deletion"]["resource_groups"] + document["deletion"]["resources"]}
    assert rows[GROUP.lower()]["delete"] is True
    assert rows[SUBNET.lower()]["delete"] is True
    assert all(rows[value.lower()]["delete"] is False for value in (COMMON, VNET, SHARED_SUBNET))
    assert document["deletion"]["flags"] == dict.fromkeys(runtime().DELETE_FLAGS, True)
    assert not cloud.deleted


@pytest.mark.parametrize("change", ["logical", "unregistered", "protected", "permission", "principal"])
def test_prepare_rejects_unreviewed_identity_or_protected_resources(change):
    document, cloud, projects = factory_prepared()
    if change == "logical":
        cloud.bodies[RESOURCE.lower()]["tags"]["aifactory.logical_project_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    elif change == "unregistered":
        projects[0]["registered_resource_ids"] = [SUBNET]
    elif change == "protected":
        document["protected_resource_ids"] = [GROUP]
    elif change == "permission":
        cloud.permissions = False
    else:
        cloud.bodies[RESOURCE.lower()]["identity"] = {"principalId": document["identity"]["deployment_object_id"]}
    with pytest.raises(fl.Blocked):
        fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    assert not cloud.deleted


def test_worker_then_common_barrier_and_successful_resume(workspace, monkeypatch):
    document, cloud, _ = factory_prepared()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)
    dispatches = []

    def dispatch(actual_cloud, locks, actual, source_root, receipt, persist):
        dispatches.append(actual["run_id"])
        receipt["remote_run"] = {"kind": "ado", "pipeline_id": 8, "run_id": 44}
        persist()
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(actual, locks)),
                                         source_root, actual["run_id"], actual["manifest_hash"],
                                         cloud=actual_cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        assert not any(identifier.endswith("/common-ip") for identifier in cloud.deleted)
        receipt["remote_terminal"] = True

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "succeeded", result
    assert dispatches == [document["run_id"]]
    assert cloud.deleted[-1].endswith("/common-ip")
    assert cloud.deleted.index(GROUP) > cloud.deleted.index(RESOURCE)
    assert SHARED_SUBNET.lower() in cloud.bodies and VNET.lower() in cloud.bodies
    again = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                               cloud_factory=lambda _: cloud)
    assert again["status"] == "succeeded"
    assert dispatches == [document["run_id"]]
    assert not cloud.leases


def test_failed_pipeline_retains_claim_and_never_deletes_common(workspace, monkeypatch):
    document, cloud, _ = factory_prepared()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "ado_scoped", Mock(side_effect=fl.Blocked("scoped-ado-run-failed")))
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "reconciliation-required"
    assert result["lock_retained"] is True
    assert not cloud.deleted


def test_partial_common_failure_resumes_verified_run_without_redispatch(workspace, monkeypatch):
    document, cloud, _ = factory_prepared()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)
    dispatches = []

    def dispatch(cloud, locks, document, source_root, receipt, persist):
        dispatches.append(document["run_id"])
        receipt.update(remote_run={"kind": "ado", "pipeline_id": 8, "run_id": 44}, mutation_started=True)
        persist()
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(document, locks)), source_root,
            document["run_id"], document["manifest_hash"], cloud=cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        receipt["remote_terminal"] = True

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    original_request = cloud.request

    def request(method, url, audience, *args, **kwargs):
        if "dev.azure.com" in url:
            assert method == "GET" and "/pipelines/8/runs/44?" in url
            return 200, {}, {"id": 44, "pipeline": {"id": 8}, "state": "completed", "result": "succeeded",
                             "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}}
        return original_request(method, url, audience, *args, **kwargs)

    cloud.request = request

    def fail_common(identifier):
        if identifier.endswith("/common-ip"):
            raise fl.Blocked("remote-request-failed-403")

    cloud.before_delete = fail_common
    run = workspace / "execution"
    first = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                               cloud_factory=lambda _: cloud)
    assert first["status"] == "reconciliation-required", first
    assert first["error_code"] == "remote-request-failed-403"
    assert first["lock_retained"] is True
    cloud.before_delete = lambda _: None
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "succeeded", result
    assert dispatches == [document["run_id"]]
    assert not cloud.leases


def test_already_absent_reviewed_project_resource_is_idempotent(workspace, monkeypatch):
    document, cloud, _ = factory_prepared()
    cloud.bodies.pop(RESOURCE.lower())
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)

    def dispatch(cloud, locks, document, source_root, receipt, persist):
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(document, locks)), source_root,
            document["run_id"], document["manifest_hash"], cloud=cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result


        assert RESOURCE in result["deleted_resources"]
        assert RESOURCE not in cloud.deleted
        receipt.update(remote_run={"kind": "ado", "pipeline_id": 8, "run_id": 44}, remote_terminal=True)

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "succeeded", result


def test_provider_managed_child_uses_reviewed_service_delete_not_rg_shortcut(workspace, monkeypatch):
    document, cloud, projects = factory_prepared()
    account = GROUP + "/providers/Microsoft.Storage/storageAccounts/projectstorage"
    child = account + "/blobServices/default"
    cloud.bodies[account.lower()] = tagged(account, "Microsoft.Storage/storageAccounts", OWNER)
    cloud.bodies[child.lower()] = tagged(child, "Microsoft.Storage/storageAccounts/blobServices", OWNER)
    old_schema, old_operations = cloud.provider_schema, cloud.provider_operations

    def schema(namespace):
        if namespace.lower() == "microsoft.storage":
            return {"resourceTypes": [{"resourceType": name, "apiVersions": ["2024-01-01"]}
                                      for name in ("storageAccounts", "storageAccounts/blobServices")]}
        return old_schema(namespace)

    def operations(namespace):
        if namespace.lower() == "microsoft.storage":
            return ["microsoft.storage/storageaccounts/" + action for action in ("read", "write", "delete")] + [
                "microsoft.storage/storageaccounts/blobservices/" + action for action in ("read", "write")]
        return old_operations(namespace)

    cloud.provider_schema, cloud.provider_operations = schema, operations
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    seal(document)
    metadata = next(row for row in document["deletion"]["resources"] if row["id"].lower() == child.lower())
    assert metadata["independent_delete"] is False
    assert metadata["delete_via_parent"] == account.lower()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)

    def dispatch(cloud, locks, document, source_root, receipt, persist):
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(document, locks)), source_root,
            document["run_id"], document["manifest_hash"], cloud=cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        assert child in result["deleted_resources"]
        assert child not in cloud.deleted
        assert cloud.deleted.index(account) < cloud.deleted.index(GROUP)
        receipt.update(remote_run={"kind": "ado", "pipeline_id": 8, "run_id": 44}, remote_terminal=True)

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "succeeded", json.dumps({
        "result": result, "worker": cloud.runs.get("runs/" + document["run_id"] + ".worker.json")}, indent=2)


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("success", [True, False])
def test_existing_provider_dispatch_carries_boolean_flags_and_requires_completion(provider, success):
    document, cloud, _ = factory_prepared()
    if provider == "gha":
        document["route"].update(kind="gha", repository="https://github.com/org/consumer", github_user_id=71)
        cloud.enrollment["writers"]["writer-a"].update(kind="gha", repository=document["route"]["repository"])
        document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    document["deletion"]["route_hash"] = fl.digest(document["route"])
    seal(document)
    module = runtime()
    worker = {"schema": 1, "status": "succeeded", "run_id": document["run_id"],
              "manifest_hash": document["manifest_hash"], "source_commit": document["source"]["commit"],
              "target": document["target"], "deleted_resources": [row["id"] for row in module.project_rows(document)],
              "flags": document["deletion"]["flags"], "project_numbers": document["target"]["project_ids"],
              "projects": module.completed_projects(document)}
    cloud.runs["runs/" + document["run_id"] + ".worker.json"] = worker
    locks = fl.BlobLocks(cloud, document)
    locks.acquire()
    template = (ROOT / "bootstrap" / "templates" / ("factory-lifecycle-" + provider + ".yml")).read_text().strip()
    envelopes, commands = [], []
    original_request = cloud.request

    def command(argv, cwd=None, data=None):
        commands.append((argv, data))
        if argv[:2] == ["git", "show"]:
            return template
        if argv == ["gh", "api", "user", "--hostname", "github.com"]:
            return json.dumps({"id": 71})
        if argv[:3] in (["gh", "secret", "set"], ["gh", "secret", "delete"]):
            return ""
        method, endpoint = argv[3:5]
        if "/contents/" in endpoint:
            return json.dumps({"encoding": "base64", "content": base64.b64encode(template.encode()).decode()})
        if "/git/trees/" in endpoint:
            return json.dumps({"tree": [{"path": "azure-enterprise-scale-ml", "mode": "160000", "sha": "a" * 40}]})
        if "/workflow" in endpoint and "/runs?" in endpoint:
            return json.dumps({"workflow_runs": [{"id": 42, "display_title": "factory-lifecycle [" + document["run_id"] + "]",
                                                  "head_sha": "b" * 40}]})
        if "/actions/runs/" in endpoint:
            return json.dumps({"id": 42, "display_title": "factory-lifecycle [" + document["run_id"] + "]",
                               "status": "completed", "conclusion": "success" if success else "failure", "head_sha": "b" * 40})
        if "/git/ref/tags/" in endpoint:
            return json.dumps({"object": {"sha": "b" * 40}})
        assert method in ("POST", "DELETE")
        return ""

    def request(method, url, audience, data=None, **kwargs):
        if not url.startswith("https://dev.azure.com/"):
            return original_request(method, url, audience, data, **kwargs)
        if "/serviceendpoint/endpoints?" in url:
            result = {"value": [{"name": document["route"]["auth_namespace"],
                                  "authorization": {"scheme": "WorkloadIdentityFederation",
                                                    "parameters": {"tenantid": document["target"]["tenant_id"]}},
                                  "data": {"subscriptionId": document["target"]["subscription_id"]}}]}
        elif "/items?" in url:
            result = {"content": template}
        elif "/build/definitions?" in url:
            result = {"value": [{"id": 7, "repository": {"name": "consumer"}, "process": {"yamlFilename": fl.SCOPED_ADO}}]}
        elif method == "POST":
            envelopes.append(json.loads(data["variables"]["AIFACTORY_ENVELOPE_JSON"]["value"]))
            result = {"id": 43}
        else:
            result = {"id": 43, "pipeline": {"id": 7}, "state": "completed",
                      "result": "succeeded" if success else "failed",
                      "resources": {"repositories": {"self": {"version": document["route"]["commit"]}}}}
        return 200, {}, result

    cloud.command, cloud.request = command, request
    receipt = {}
    dispatcher = fl.github_scoped if provider == "gha" else fl.ado_scoped
    if success:
        dispatcher(cloud, locks, document, ROOT, receipt, lambda: None, sleep=lambda _: None)
        assert receipt["worker_receipt"] == worker
    else:
        with pytest.raises(fl.Blocked, match="scoped-.*-run-failed"):
            dispatcher(cloud, locks, document, ROOT, receipt, lambda: None, sleep=lambda _: None)
        assert "worker_receipt" not in receipt
    if provider == "gha":
        raw = "".join(data for args, data in commands if args[:3] == ["gh", "secret", "set"])
        envelopes.append(json.loads(zlib.decompress(base64.b64decode(raw))))
    assert len(envelopes) == 1
    assert envelopes[0]["manifest"]["deletion"]["flags"] == dict.fromkeys(module.DELETE_FLAGS, True)
    assert all(value is True for value in envelopes[0]["manifest"]["deletion"]["flags"].values())
    assert envelopes[0]["manifest"]["route"] == document["route"]
    assert receipt["remote_terminal"] is True
    assert not cloud.deleted


@pytest.mark.parametrize("failed_environment", [None, "prod"])
def test_all_environments_complete_before_any_common_resource(workspace, monkeypatch, failed_environment):
    documents, clouds, timeline = [], {}, []
    for environment in ("dev", "stage", "prod"):
        document, cloud, projects = factory_prepared()

        def replace(value):
            return json.loads(json.dumps(value).replace("resourceGroups/reviewed", "resourceGroups/reviewed-" + environment)
                .replace("resourcegroups/reviewed", "resourcegroups/reviewed-" + environment)
                .replace("resourceGroups/common", "resourceGroups/common-" + environment)
                .replace("resourcegroups/common", "resourcegroups/common-" + environment))

        document, projects = replace(document), replace(projects)
        document["target"]["environment"] = environment
        cloud.bodies, cloud.enrollment = replace(cloud.bodies), replace(cloud.enrollment)
        for scope in cloud.enrollment["scopes"].values():
            scope["target"]["environment"] = environment
        document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
        document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
        documents.append(seal(document))
        clouds[document["run_id"]] = cloud
        cloud.after_delete = lambda identifier, env=environment: timeline.append((env, identifier))
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)

    def dispatch(cloud, locks, document, source_root, receipt, persist):
        environment = document["target"]["environment"]
        timeline.append((environment, "dispatch"))
        if environment == failed_environment:
            raise fl.Blocked("scoped-ado-run-failed")
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(document, locks)),
            source_root, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        receipt.update(remote_run={"kind": "ado", "pipeline_id": 7, "run_id": 42}, remote_terminal=True)
        timeline.append((environment, "provider-success"))

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort(documents, source, run, run / "receipt.json",
                                                cloud_factory=lambda document: clouds[document["run_id"]])
    common_indices = [index for index, (_, action) in enumerate(timeline) if action.endswith("/common-ip")]
    if failed_environment:
        assert result["status"] == "reconciliation-required", result
        assert not common_indices
    else:
        assert result["status"] == "succeeded", result
        assert len(common_indices) == 3
        assert min(common_indices) > max(index for index, (_, action) in enumerate(timeline) if action == "provider-success")


def test_freeze_takes_explicit_ownership_records_like_sibling_deletion_freezes():
    document, cloud, projects = factory_prepared()
    with pytest.raises(TypeError):
        fl.freeze_factory_deletion_pipeline(cloud, document, projects)
    # Manifest-embedded records are not an alternate authority; only the explicit argument is read.
    document["known_ownership"] = {RESOURCE.lower(): {"owner": OWNER}}
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    assert fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)["projects"][0]["project_id"] == PROJECT


def test_aggregate_receipt_binds_sorted_cohort_and_source_ref_for_the_catalog(workspace, monkeypatch):
    document, cloud, _ = factory_prepared()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "ado_scoped", Mock(side_effect=fl.Blocked("scoped-ado-run-failed")))
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["cohort_hash"] == fl.digest(sorted([document["manifest_hash"]]))
    assert result["source_ref"] == document["source"]["ref"]
    child, = result["children"]
    assert child["manifest_revision"] == document["manifest_revision"]
    assert child["source_ref"] == document["source"]["ref"]
    assert child["cohort_hash"] == result["cohort_hash"]