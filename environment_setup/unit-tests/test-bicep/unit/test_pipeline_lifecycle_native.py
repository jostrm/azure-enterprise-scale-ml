"""The six service routes execute native workers against offline transports.

These use the existing lifecycle inventory/lease fixtures, not a synthetic
successful adapter. Real HTTP, subprocesses, and therefore the Factory API are
rejected. Scratch files stay in the repository workspace fixture.
"""

import copy
import base64
import json
import time
import zlib
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import (
    fl, ROOT, PlanCloud, ClosureCloud, GROUP, COMMON, RESOURCE, scoped_manifest, seal,
    simple_plan_closure, owned_group_manifest, workspace, no_real_services,
)
from .test_selective_project_deletion import prepared, SUBNET, SHARED_SUBNET
from .test_selective_project_deletion import ProjectCloud, tagged
from .test_factory_deletion_pipeline import factory_prepared
from .test_pipeline_lifecycle import Store, resolved


@pytest.fixture(autouse=True)
def complete_arm_response_shapes(monkeypatch):
    def typed_arm(original):
        def arm(self, method, resource, api, *args, **kwargs):
            status, headers, body = original(self, method, resource, api, *args, **kwargs)
            if status == 404 and body is None:
                body = {"error": {"code": "ResourceGroupNotFound" if fl.RG_ID.fullmatch(resource)
                                 else "ResourceNotFound"}}
            return status, headers, body
        return arm
    for cls in (ClosureCloud, ProjectCloud, PlanCloud):
        if "arm" in cls.__dict__:
            monkeypatch.setattr(cls, "arm", typed_arm(cls.arm))
    original = PlanCloud.request
    def request(self, method, url, *args, **kwargs):
        status, headers, body = original(self, method, url, *args, **kwargs)
        if method == "GET" and "/providers/Microsoft.Resources/deployments/" in url and isinstance(body, dict):
            body = {**body, "id": url.removeprefix(fl.ARM).split("?")[0]}
        return status, headers, body
    monkeypatch.setattr(PlanCloud, "request", request)


def commands(document, observer=None):
    def run(argv, **kwargs):
        if argv == ["git", "rev-parse", "HEAD"]:
            return document["source"]["commit"]
        assert argv[:3] == ["az", "account", "get-access-token"]
        claims = {"oid": observer or document["identity"]["object_id"],
                  "tid": document["target"]["tenant_id"], "aud": fl.ARM, "exp": time.time() + 3600}
        part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return json.dumps({"accessToken": "header." + part + ".signature"})
    return Mock(side_effect=run)


@pytest.mark.parametrize("provider", ["gha", "ado"])
@pytest.mark.parametrize("scenario", [1, 2, 3])
@pytest.mark.parametrize("defect", [None, "missing-group", "wrong-group", "foreign-group", "failed-read",
                                  "missing-resource", "failed-deployment"])
def test_observe_requires_live_deployment_effects_with_real_worker_receipt(monkeypatch, provider, scenario, defect):
    import pipeline_lifecycle_adapters as adapters
    import pipeline_lifecycle_reconciliation as reconciliation
    from .test_pipeline_lifecycle_recovery import canonical_completed_case
    monkeypatch.setattr(adapters, "fl", fl)
    monkeypatch.setattr(reconciliation, "fl", fl)
    case = canonical_completed_case(reconciliation, monkeypatch, scenario, provider)
    _, store, _, prior, _, _, _, _, cloud, *_ = case
    stage = prior["plan"]["stages"][0]
    document = stage["manifests"][0]
    scope = document["locks"]["scopes"][0]
    prefix = "runs/" + document["run_id"]
    native, worker = (store.value["records"][prefix + suffix] for suffix in (".json", ".worker.json"))
    locks = Mock()
    locks.request.side_effect = lambda method, path, *args, **kwargs: (200, {}, copy.deepcopy(store.value["records"][path]))
    assert fl.verify_worker_receipt(locks, document) == worker
    arm, request = cloud.arm, cloud.request
    def read(method, resource, api, **kwargs):
        assert method == "GET"
        if resource.lower() == scope.lower():
            if defect == "missing-group":
                return 404, {}, {"error": {"code": "ResourceGroupNotFound"}}
            if defect == "failed-read":
                return 403, {}, {"error": {"code": "AuthorizationFailed"}}
            if defect == "wrong-group":
                return 200, {}, {**cloud.bodies[scope.lower()], "id": scope + "-other"}
        return arm(method, resource, api, **kwargs)
    cloud.arm = read
    if defect == "foreign-group":
        cloud.bodies[scope.lower()]["tags"][fl.TAG_KEYS["factory_id"]] = "foreign"
    elif defect == "missing-resource":
        cloud.bodies.pop(worker["ownership"][0]["resource_id"].lower())
    elif defect == "failed-deployment":
        def failed(method, url, audience, *args, **kwargs):
            if "/deployments/" in url:
                return 200, {}, {"id": url.removeprefix(fl.ARM).split("?")[0],
                                 "properties": {"provisioningState": "Failed"}}
            return request(method, url, audience, *args, **kwargs)
        cloud.request = failed
    executor = adapters.NativeExecutor(ROOT, ROOT, cloud_factory=lambda _: cloud)
    monkeypatch.setattr(executor, "_receipt", lambda *args, **kwargs: (cloud, locks, native))
    if defect:
        with pytest.raises((ValueError, fl.Blocked)):
            executor.observe(stage, prior)
        import lifecycle_admission as outer
        from pipeline_lifecycle import LifecycleService
        from pipeline_lifecycle_admission import NativeAdmission
        review = Mock()
        review.verify_finalizer.return_value = {"operation_id": prior["operation_id"], "plan_hash": prior["plan_hash"]}
        admission = NativeAdmission(store, review, executor)
        engine = LifecycleService(store=adapters.RepositoryJournal(store), planner=Mock(), executor=executor,
                                  review=review, admission=admission, configuration=admission)
        with pytest.raises(ValueError, match="finalizer-native-outcome-unverified"):
            engine.finalize(prior["operation_id"], prior["snapshot"], prior["plan_hash"])
        assert store.value["records"][outer.RECORD]["claim"] == prior["admission_claim"]
        assert engine.status(prior["operation_id"])["status"] == "reconciliation-required"
    else:
        assert executor.observe(stage, prior)["verified"] is True
        assert not store.writes
    assert not cloud.deleted and not cloud.arm_writes


@pytest.mark.parametrize("defect", [None, "agent-principal", "grant", "account", "capability-host"])
@pytest.mark.parametrize("mode", ["observation", "recovery"])
def test_full_foundry_continuation_observation_revalidates_runtime_not_only_arm_success(
        workspace, monkeypatch, defect, mode):
    import pipeline_lifecycle_adapters as adapters
    from .test_native_foundry_lifecycle import continued_native_worker
    monkeypatch.setattr(adapters, "fl", fl)
    document, cloud, locks, producer = continued_native_worker(monkeypatch)
    locks.claim_run()
    worker = fl.run_deployment_worker({"manifest": document, "lease_context": locks.held},
        ROOT, document["run_id"], document["manifest_hash"], cloud=cloud, sleep=Mock())
    assert worker["status"] == "succeeded", worker.get("error_code")
    native = cloud.runs["runs/" + document["run_id"] + ".json"]
    native.update(status="succeeded", remote_run={"kind": "ado", "run_id": 44, "pipeline_id": 8})
    locks.release()
    cloud.command = commands(document)
    cloud.state_request = lambda *_: (200, {}, {
        "id": 44, "sourceVersion": document["route"]["commit"], "status": "completed", "result": "succeeded"})
    for scope in document["locks"]["common_dependencies"]:
        cloud.bodies[scope.lower()] = {"id": scope, "properties": {"provisioningState": "Succeeded"}}
    before = copy.deepcopy(cloud.executed), copy.deepcopy(cloud.grant_writes), copy.deepcopy(cloud.source_grant_writes)
    if defect == "agent-principal":
        cloud.bodies[worker["foundry_agent_readiness"]["resource_id"]]["properties"]["principalId"] = "f" * 36
    elif defect == "grant":
        cloud.bodies.pop(worker["foundry_agent_readiness"]["grants"][0]["id"])
    elif defect == "account":
        cloud.bodies[worker["foundry_readiness"]["account_resource_id"]]["properties"]["networkInjections"] = []
    elif defect == "capability-host":
        cloud.bodies[worker["foundry_readiness"]["capability_host"]["id"].lower()]["name"] = "replacement-host"
    executor = adapters.NativeExecutor(ROOT, workspace / "foundry-observation", cloud_factory=lambda _: cloud)
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [document]}
    def observe():
        if mode == "observation":
            return executor.observe(stage, {"plan": {}})
        import pipeline_lifecycle_reconciliation as reconciliation
        monkeypatch.setattr(reconciliation, "fl", fl)
        return reconciliation.NativeReconciliationEvidence._completed_outcome(
            cloud, document, cloud.runs, cloud.bodies, set())
    if defect:
        with pytest.raises((ValueError, fl.Blocked)):
            observe()
    else:
        result = observe()
        assert result["status"] == "succeeded" and result["verified"] is True
        assert result["runtime_ready"] is True
        if mode == "observation":
            assert result["children"][0]["worker"]["foundry_identity_continuation"]["run_id"] == producer["run_id"]
    assert before == (cloud.executed, cloud.grant_writes, cloud.source_grant_writes)


@pytest.mark.parametrize("scenario", range(1, 7))
def test_six_scenarios_execute_native_engine_without_factory_api(workspace, monkeypatch, scenario):
    import pipeline_lifecycle as runtime
    import pipeline_lifecycle_adapters as adapters
    monkeypatch.setattr(adapters, "fl", fl)
    if scenario < 4:
        operation = {1: "create-factory", 2: "create-scaleset", 3: "deploy-project"}[scenario]
        document, templates = scoped_manifest(() if scenario == 2 else ("017",), operation=operation)
        document["config"] = {}
        document["deployment"]["configuration_hash"] = fl.digest({})
        cloud = PlanCloud(document, templates)
        document["locks"]["common_dependencies"] = []
        cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = []
        document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
        seal(document)
        monkeypatch.setattr(fl, "collect_resource_closure", simple_plan_closure)
    elif scenario == 4:
        document, cloud = prepared(False, True)
    elif scenario == 5:
        cloud = ClosureCloud()
        document = owned_group_manifest(cloud)
        cloud.bodies = copy.deepcopy(cloud.bodies)
        for scope in document["locks"]["common_dependencies"]:
            cloud.bodies[scope.lower()] = {"id": scope, "properties": {"provisioningState": "Succeeded"}}
    else:
        document, cloud, _ = factory_prepared()
    source = workspace / "source"
    source.mkdir()
    cloud.command = commands(document)
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)
    dispatched = []

    def dispatch(actual_cloud, locks, manifest, source_root, receipt, persist):
        dispatched.append(manifest["run_id"])
        receipt["remote_run"] = {"kind": "ado", "pipeline_id": 8, "run_id": 44}
        persist()
        worker = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(manifest, locks)),
                                         source_root, manifest["run_id"], manifest["manifest_hash"],
                                         cloud=actual_cloud, sleep=lambda _: None)
        assert worker["status"] == "succeeded", worker
        receipt["worker_receipt"] = fl.verify_worker_receipt(locks, manifest)
        receipt["remote_terminal"] = True
    monkeypatch.setattr(fl, "ado_scoped", dispatch)

    def provider_read(kind, method, endpoint, body, allowed):
        assert kind == "ado" and method == "GET" and "/_apis/build/builds/44" in endpoint
        assert dispatched
        worker = cloud.runs["runs/" + document["run_id"] + ".worker.json"]
        return 200, {}, {"id": 44, "sourceVersion": document["route"]["commit"],
                          "status": "completed", "result": "succeeded" if worker["status"] == "succeeded" else "failed"}
    cloud.state_request = provider_read
    plan = {"stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": [document]}]}
    planner = Mock()
    planner.prepare.return_value = plan
    review, admission = Mock(), Mock(spec=["acquire", "assert_owned", "release"])
    admission.acquire.return_value = {"id": "test-authenticated-claim"}
    review.verify.return_value = {"provider": "ado", "run_id": "42", "native_review_test_double": True}
    store = Store()
    service = runtime.LifecycleService(store=store, planner=planner,
                                       executor=adapters.NativeExecutor(source, workspace / "state",
                                                                       cloud_factory=lambda _: cloud),
                                       review=review, admission=admission)
    snapshot = resolved(scenario)
    record = service.prepare(snapshot)
    result = service.execute(record["operation_id"], snapshot, record["plan_hash"])
    assert result["status"] == "succeeded", (
        result.get("error_code"), [row.get("receipt", {}).get("native", {}).get("error_code")
                                   for row in result["stages"]])
    assert result["stages"][0]["receipt"]["verified"] is True
    assert not cloud.leases
    if scenario < 4:
        assert cloud.arm_writes
    else:
        assert cloud.deleted
    if scenario == 4:
        assert SUBNET.lower() in cloud.bodies
    if scenario in (4, 6):
        assert SHARED_SUBNET.lower() in cloud.bodies
    before = len(cloud.deleted)
    assert service.observe(record["operation_id"])["status"] == "succeeded"
    assert len(cloud.deleted) == before


def test_deleted_resource_reappearance_prevents_false_recovery(workspace, monkeypatch):
    import pipeline_lifecycle_adapters as adapters
    monkeypatch.setattr(adapters, "fl", fl)
    document, cloud = prepared(False, True)
    cloud.command = commands(document)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    executor = adapters.NativeExecutor(source, workspace / "state", cloud_factory=lambda _: cloud)
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [document]}
    record = {"operation_id": "11111111-1111-1111-1111-111111111111"}
    before = copy.deepcopy(cloud.bodies[RESOURCE.lower()])
    assert executor.execute(stage, record)["verified"] is True
    cloud.bodies[RESOURCE.lower()] = before
    with pytest.raises(ValueError, match="deleted-resource-reappeared"):
        executor.observe(stage, record)


@pytest.mark.parametrize("defect", ["extra-deletion", "retained-missing"])
def test_reconciliation_requires_exact_deletions_and_surviving_retention(workspace, monkeypatch, defect):
    import pipeline_lifecycle_adapters as adapters
    monkeypatch.setattr(adapters, "fl", fl)
    document, cloud = prepared(False, True)
    cloud.command = commands(document)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    executor = adapters.NativeExecutor(source, workspace / "state", cloud_factory=lambda _: cloud)
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [document]}
    record = {"operation_id": "11111111-1111-1111-1111-111111111111"}
    assert executor.execute(stage, record)["verified"] is True
    if defect == "extra-deletion":
        cloud.runs["runs/" + document["run_id"] + ".json"]["deleted_resources"].append(
            GROUP + "/providers/Microsoft.Network/publicIPAddresses/unreviewed")
        code = "native-deletion-receipt-incomplete"
    else:
        cloud.bodies.pop(COMMON.lower())
        code = "retained-resource-missing"
    with pytest.raises(ValueError, match=code):
        executor.observe(stage, record)


def test_read_only_reconciliation_authenticates_observer_without_impersonating_writer(workspace, monkeypatch):
    import pipeline_lifecycle_adapters as adapters
    monkeypatch.setattr(adapters, "fl", fl)
    document, cloud = prepared(False, True)
    cloud.command = commands(document)
    cloud.expected_object_id = document["identity"]["object_id"]
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    executor = adapters.NativeExecutor(source, workspace / "state", cloud_factory=lambda _: cloud)
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [document]}
    record = {"operation_id": "11111111-1111-1111-1111-111111111111"}
    assert executor.execute(stage, record)["verified"] is True
    original = copy.deepcopy(document["identity"])
    observer = "99999999-9999-9999-9999-999999999999"
    cloud.command = commands(document, observer)
    result = executor.observe(stage, record)
    assert result["verified"] is True
    assert cloud.expected_object_id == observer
    assert document["identity"] == original
    assert result["children"][0]["observer_object_id"] == observer


def test_new_provider_run_observes_parent_without_excluding_stale_parent_identity(workspace, monkeypatch):
    import pipeline_lifecycle_adapters as adapters
    monkeypatch.setattr(adapters, "fl", fl)
    document, cloud = prepared(False, True)
    cloud.command = commands(document)
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    review = Mock()
    current = {"provider": "ado", "run_id": "43", "attempt": 1}
    review.origin.return_value = current
    executor = adapters.NativeExecutor(source, workspace / "state", cloud_factory=lambda _: cloud, review=review)
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [document]}
    record = {"operation_id": "11111111-1111-1111-1111-111111111111", "snapshot": {},
              "plan": {"origin": {"provider": "ado", "run_id": "42", "attempt": 1}}}
    assert executor.execute(stage, record)["verified"] is True
    assert executor.observe(stage, record)["verified"] is True
    assert executor.origin == current
    assert record["plan"]["origin"]["run_id"] == "42"


def test_native_foundry_identity_is_verified_continuation_not_completion(workspace, monkeypatch):
    import pipeline_lifecycle as runtime
    import pipeline_lifecycle_adapters as adapters
    from .test_native_foundry_lifecycle import identity_source_case, IdentityProducerCloud, identity_closure, UAMI
    monkeypatch.setattr(adapters, "fl", fl)
    document, templates = identity_source_case()
    document["locks"]["common_dependencies"] = []
    cloud = IdentityProducerCloud(document, templates)
    cloud.enrollment["scopes"][GROUP.lower()]["common_dependencies"] = []
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    monkeypatch.setattr(fl, "collect_resource_closure", identity_closure)
    document["deployment"] = fl._freeze_deployment_contents(cloud, document, ROOT)
    seal(document)
    cloud.command = commands(document)
    cloud.state_request = lambda *_: (200, {}, {
        "id": 44, "sourceVersion": document["route"]["commit"], "status": "completed", "result": "succeeded"})
    monkeypatch.setattr(fl, "verify_source", lambda *args: ROOT)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: ROOT)

    def dispatch(actual, locks, manifest, source, receipt, persist):
        receipt["remote_run"] = {"kind": "ado", "run_id": 44}
        receipt["mutation_started"] = True
        persist()
        fl.run_deployment_worker({"manifest": manifest, "lease_context": locks.held}, source,
                                 manifest["run_id"], manifest["manifest_hash"], cloud=actual, sleep=Mock())
        receipt["worker_receipt"] = fl.verify_worker_receipt(locks, manifest)
        receipt["remote_terminal"] = True

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    stage = {"id": "lifecycle", "kind": "lifecycle", "manifests": [document]}
    planner, review, admission = Mock(), Mock(), Mock(spec=["acquire", "assert_owned", "release"])
    planner.prepare.return_value = {"stages": [stage]}
    admission.acquire.return_value = {"id": "test-authenticated-claim"}
    source = workspace / "source"
    source.mkdir()
    executor = adapters.NativeExecutor(source, workspace / "native", cloud_factory=lambda _: cloud)
    engine = runtime.LifecycleService(store=Store(), planner=planner, executor=executor, review=review, admission=admission)
    data = resolved()
    record = engine.prepare(data)
    result = engine.execute(record["operation_id"], data, record["plan_hash"])
    assert result["status"] == "continuation-required", (
        result.get("error_code"), result["stages"][0].get("receipt", {}).get("native", {}).get("error_code"))
    assert result["stages"][0]["receipt"]["verified"] is True
    assert UAMI in cloud.bodies
    writes = len(cloud.arm_writes)
    assert engine.reconcile(record["operation_id"])["status"] == "continuation-required"
    assert len(cloud.arm_writes) == writes
    cloud.bodies[UAMI]["properties"]["principalId"] = "99999999-9999-9999-9999-999999999999"
    assert engine.reconcile(record["operation_id"])["status"] == "reconciliation-required"


def production_fixture(monkeypatch, scenario, network_group, provider="ado"):
    import pipeline_lifecycle_adapters as adapters
    from .test_pipeline_lifecycle_adapters import snapshot, FACTORY, SCALE, PROJECT, OBJECT, SUB, TENANT
    monkeypatch.setattr(adapters, "fl", fl)
    data = snapshot(scenario)
    data["variables"][PROJECT]["dev"]["vnetResourceGroup"] = network_group
    data["request"]["provider"] = provider
    scale = data["scales"][0]
    scale["orchestrator"] = provider
    scale["owned_resource_ids"] = [GROUP, COMMON]
    binding = data["binding"]
    binding.update(orchestrator=provider, repository=(
        "https://dev.azure.com/org/project/_git/repo" if provider == "ado" else "https://github.com/org/repo"))
    binding["targets"][0]["resource_group_ids"] = [GROUP, COMMON]
    data["document"]["bindings"] = {FACTORY: {provider: binding}}
    binding["locks"] = {"account_url": "https://lockstore.blob.core.windows.net",
                        "container": "factory-locks", "coordination_blob": "coordination.json", "revision": 1}
    owner = {"factory_id": FACTORY, "scaleset_id": SCALE}
    project_owner = {**owner, "project_id": "001"}
    common_ip = COMMON + "/providers/Microsoft.Network/publicIPAddresses/common-ip"

    class PlannerCloud(ProjectCloud):
        def __init__(self):
            super().__init__()
            self.bodies = {
                GROUP.lower(): tagged(GROUP, "Microsoft.Resources/resourceGroups", project_owner),
                COMMON.lower(): tagged(COMMON, "Microsoft.Resources/resourceGroups", owner),
                RESOURCE.lower(): tagged(RESOURCE, "Microsoft.Network/publicIPAddresses", project_owner),
                common_ip.lower(): tagged(common_ip, "Microsoft.Network/publicIPAddresses", owner),
            }
            target = {**owner, "environment": "dev", "tenant_id": TENANT, "subscription_id": SUB,
                      "prefix": data["factory"]["prefix"], "region": data["factory"]["region"], "suffix": "001"}
            self.enrollment = {
                "schema": 1, "protocol": "aifactory-physical-lock-v1", "enforcement": "all-writers-exclusive",
                "revision": 1, "writers": {"writer": {
                    "kind": provider, "repository": binding["repository"], "shared_remote": False,
                    "auth_namespace": binding["auth_namespace"], "runner": binding["runner"],
                    "deployment_object_id": OBJECT}},
                "scopes": {group.lower(): {"writers": ["writer"], "scope_kind": "aifactory-owned",
                                            "allow_delete": True, "target": target, "common_dependencies": []}
                           for group in (GROUP, COMMON)}}
            self.compilations = []
            self.arm_writes = []

        def command(self, argv, **kwargs):
            if argv[:2] == ["git", "ls-remote"]:
                return "b" * 40 + "\trefs/heads/main"
            if argv == ["git", "rev-parse", "HEAD"]:
                return "a" * 40
            if argv[:3] == ["gh", "api", "user"]:
                return json.dumps({"id": 71})
            assert argv[:3] == ["az", "account", "get-access-token"]
            return commands({"source": data["source"], "identity": {"object_id": OBJECT},
                             "target": {"tenant_id": TENANT}})(argv)

        def compile_template(self, root, path):
            self.compilations.append(path)
            parameters = {name: {"type": "string"} for name in
                          ("env", "location", "commonRGNamePrefix", "aifactorySuffixRG")}
            parameters["tagsProject" if path.endswith("/09-ai-foundry-2025-v4.bicep") else "tags"] = {"type": "object"}
            if path.endswith("/09-ai-foundry-2025-v4.bicep"):
                parameters["enableAIFoundry"] = {"type": "bool", "defaultValue": False}
            if path in fl.PROJECT_TEMPLATES:
                parameters["projectNumber"] = {"type": "string"}
            scope = "subscription"
            if path.endswith("/31-network.bicep"):
                parameters["vnetResourceGroup"] = {"type": "string"}
                scope = "resourceGroup"
            return {"$schema": "https://schema.management.azure.com/schemas/2018-05-01/" + scope + "DeploymentTemplate.json#",
                    "parameters": parameters, "resources": []}

        def request(self, method, url, audience, data=None, headers=None, allowed=(200,)):
            assert url.startswith((fl.ARM + "/", "https://lockstore.blob.core.windows.net/")), (
                "Factory API and unreviewed HTTP endpoints are forbidden: " + url)
            if url.startswith(fl.ARM) and "/whatIf?" in url:
                assert method == "POST"
                selected = ([common_ip] if scenario == 2 else [RESOURCE] if scenario == 3 else [common_ip, RESOURCE])
                return 200, {}, {"properties": {"changes": [
                    {"resourceId": resource, "changeType": "Modify", "before": self.bodies[resource.lower()],
                     "after": self.bodies[resource.lower()]} for resource in selected]}}
            if url.startswith(fl.ARM) and "/providers/Microsoft.Resources/deployments/" in url:
                if method == "PUT":
                    self.arm_writes.append((url, copy.deepcopy(data)))
                    return 201, {}, {"properties": {"provisioningState": "Succeeded"}}
                assert method == "GET"
                return 200, {}, {"id": url.removeprefix(fl.ARM).split("?")[0],
                                 "properties": {"provisioningState": "Succeeded"}}
            return super().request(method, url, audience, data, headers, allowed)

    cloud = PlannerCloud()
    binding["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    review = Mock()
    review.origin.return_value = {"provider": provider, "run_id": "42", "attempt": 1, "commit": "b" * 40}
    monkeypatch.setattr(fl, "verify_source", lambda cloud, root, source: root)
    planner = adapters.NativePlanner(ROOT, ROOT, cloud_factory=lambda _: cloud, review=review)
    return data, cloud, review, planner, common_ip


@pytest.mark.parametrize("scenario,network_group", [
    *((scenario, COMMON.rsplit("/", 1)[1]) for scenario in range(1, 7)), (1, "foreign"), (3, "foreign")])
def test_production_planner_derives_all_six_native_plans_from_configuration_and_transports(
        monkeypatch, scenario, network_group):
    data, cloud, _, planner, _ = production_fixture(monkeypatch, scenario, network_group)
    if network_group == "foreign":
        with pytest.raises(ValueError, match="project-network-resource-group-not-enrolled"):
            planner.prepare(data, "11111111-1111-1111-1111-111111111111")
        assert not cloud.deleted
        return
    plan = planner.prepare(data, "11111111-1111-1111-1111-111111111111")
    document = plan["stages"][0]["manifests"][0]
    fl.validate_manifest(document)
    assert not cloud.deleted
    if scenario < 4:
        assert document["deployment"]["changes"]
        assert cloud.compilations
        assert all(step["template"] in fl.PROJECT_TEMPLATES | set(fl.COMMON_TEMPLATES.values())
                   for step in document["deployment"]["steps"])
    else:
        assert document["deletion"]["inventory_complete"] is True
        assert document["deletion"]["resources"]


@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_authorization_evidence_uses_native_inventory_without_enabling_or_deleting(workspace, monkeypatch, provider):
    import pipeline_lifecycle_adapters as adapters
    data, cloud, _, planner, _ = production_fixture(monkeypatch, 5, COMMON.rsplit("/", 1)[1], provider)
    for row in cloud.enrollment["scopes"].values():
        row["allow_delete"] = False
    data["binding"]["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    plan = planner.prepare(data, "11111111-1111-1111-1111-111111111111", coordination_only=True)
    manifests = plan["stages"][0]["manifests"]
    assert all("operation" not in row and "deletion" not in row and "manifest_hash" not in row for row in manifests)
    proposal = {"repository": data["binding"]["repository"], "factory_id": data["factory"]["id"],
                "scopes": sorted([GROUP.lower(), COMMON.lower()]), "common_dependencies": [],
                "canonical": {"before": {"document": data["document"]}}}
    stage = {"kind": "deletion-authorization", "manifests": manifests, "deletion_authorization": proposal}
    journal = Mock()
    journal.ownership.return_value = {}
    executor = adapters.NativeExecutor(ROOT, workspace / "native", cloud_factory=lambda _: cloud)
    evidence = adapters.NativeAuthorizationEvidence(executor, journal)
    observed = evidence(stage, {"plan": plan})
    assert observed["inventory_complete"] is True and observed["active_operations"] == []
    assert not cloud.deleted and not cloud.arm_writes
    assert all(row["allow_delete"] is False for row in cloud.enrollment["scopes"].values())
    cloud.bodies[GROUP.lower()]["tags"]["aifactory.factory_id"] = "99999999-9999-9999-9999-999999999999"
    with pytest.raises(ValueError):
        evidence(stage, {"plan": plan})
    assert not cloud.deleted and not cloud.arm_writes


def test_project_authorization_inventory_keeps_unselected_common_resources(workspace, monkeypatch):
    import pipeline_lifecycle_adapters as adapters
    data, cloud, _, planner, common_ip = production_fixture(monkeypatch, 4, COMMON.rsplit("/", 1)[1])
    cloud.bodies[common_ip.lower()]["tags"]["aifactory.shared"] = "true"
    plan = planner.prepare(data, "11111111-1111-1111-1111-111111111111", coordination_only=True)
    proposal = {"repository": data["binding"]["repository"], "factory_id": data["factory"]["id"],
                "scopes": sorted([GROUP.lower(), COMMON.lower()]), "common_dependencies": [],
                "canonical": {"before": {"document": data["document"]}}, "request": data["request"],
                "selected_projects": data["projects"], "selected_scales": data["scales"]}
    stage = {"kind": "deletion-authorization", "manifests": plan["stages"][0]["manifests"],
             "deletion_authorization": proposal}
    journal = Mock()
    journal.ownership.return_value = {}
    executor = adapters.NativeExecutor(ROOT, workspace / "native", cloud_factory=lambda _: cloud)
    result = adapters.NativeAuthorizationEvidence(executor, journal)(stage, {"plan": plan})
    assert result["inventory_complete"]
    assert not cloud.deleted and not cloud.arm_writes


@pytest.mark.parametrize("scenario", range(1, 7))
@pytest.mark.parametrize("provider", ["gha", "ado"])
def test_native_prepare_execute_persist_reconcile_matrix_without_factory_api(workspace, monkeypatch, scenario, provider):
    import socket
    import pipeline_lifecycle as runtime
    import pipeline_lifecycle_adapters as adapters
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("Factory API HTTP forbidden")))
    data, cloud, review, planner, common_ip = production_fixture(
        monkeypatch, scenario, COMMON.rsplit("/", 1)[1], provider)
    platform_group = "/subscriptions/99999999-9999-9999-9999-999999999999/resourceGroups/platform-survives"
    platform = {
        platform_group.lower(): tagged(platform_group, "Microsoft.Resources/resourceGroups", {}),
        (platform_group + "/providers/Microsoft.Compute/virtualMachines/runner").lower():
            tagged(platform_group + "/providers/Microsoft.Compute/virtualMachines/runner", "Microsoft.Compute/virtualMachines", {}),
        (platform_group + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/platform").lower():
            tagged(platform_group + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/platform",
                   "Microsoft.ManagedIdentity/userAssignedIdentities", {}),
    }
    cloud.bodies.update(copy.deepcopy(platform))
    common_before = copy.deepcopy(cloud.bodies[common_ip.lower()])
    with pytest.raises(AssertionError, match="Factory API"):
        cloud.request("GET", "http://localhost:8000/api/factory", "factory-api")
    source = workspace / "source"
    source.mkdir()
    planner.source_root = source
    monkeypatch.setattr(fl, "verify_source", lambda cloud, root, source: root)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    provider_runs = {}
    protected_chunks, refs = {}, {}
    source_template = (ROOT / ("bootstrap/templates/factory-lifecycle-" + provider + ".yml")).read_text(encoding="utf-8").strip()
    original_request, original_command = cloud.request, cloud.command

    def run_worker(envelope):
        manifest = envelope["manifest"]
        run_id = len(provider_runs) + 1
        worker = fl.run_deployment_worker(envelope, source, manifest["run_id"], manifest["manifest_hash"],
                                         cloud=cloud, sleep=lambda _: None)
        provider_runs[run_id] = {"manifest": manifest, "worker": worker}
        if scenario == 6:
            assert common_ip.lower() in cloud.bodies, "Common teardown crossed the project-worker barrier"
        return run_id

    def run_status(run_id):
        completed = provider_runs[run_id]
        assert completed["worker"] == cloud.runs["runs/" + completed["manifest"]["run_id"] + ".worker.json"]
        succeeded = completed["worker"]["status"] == "succeeded"
        commit = completed["manifest"]["route"]["commit"]
        return {"id": run_id, "pipeline": {"id": 8}, "sourceVersion": commit, "head_sha": commit,
                "display_title": "factory-lifecycle [" + completed["manifest"]["run_id"] + "]",
                "resources": {"repositories": {"self": {"version": commit}}},
                "state": "completed", "status": "completed", "result": "succeeded" if succeeded else "failed",
                "conclusion": "success" if succeeded else "failure"}

    def github(method, endpoint, body):
        assert endpoint.startswith("repos/org/repo/"), "Unreviewed provider endpoint"
        path = endpoint.removeprefix("repos/org/repo")
        if method == "GET" and path.startswith("/contents/"):
            return {"encoding": "base64", "content": base64.b64encode(source_template.encode()).decode()}
        if method == "GET" and path.startswith("/git/trees/"):
            return {"tree": [{"path": "azure-enterprise-scale-ml", "mode": "160000", "sha": data["source"]["commit"]}]}
        if method == "POST" and path == "/git/refs":
            refs[body["ref"]] = body["sha"]
            return {}
        if method == "POST" and path == "/actions/workflows/factory-lifecycle.yml/dispatches":
            inputs = body["inputs"]
            encoded = "".join(protected_chunks[inputs["secret_prefix"] + "_" + str(index)]
                              for index in range(int(inputs["secret_chunks"])))
            run_worker(json.loads(zlib.decompress(base64.b64decode(encoded))))
            return None
        if method == "GET" and path.startswith("/actions/workflows/factory-lifecycle.yml/runs"):
            return {"workflow_runs": [run_status(run_id) for run_id in provider_runs]}
        if method == "GET" and path.startswith("/actions/runs/"):
            return run_status(int(path.rsplit("/", 1)[1]))
        if method == "GET" and path.startswith("/git/ref/tags/"):
            return {"object": {"sha": refs["refs/tags/" + path.removeprefix("/git/ref/tags/")]}}
        if method == "DELETE" and path.startswith("/git/refs/tags/"):
            del refs["refs/tags/" + path.removeprefix("/git/refs/tags/")]
            return None
        raise AssertionError((method, path))

    def command(argv, cwd=None, data=None):
        if argv[:2] == ["git", "show"]:
            assert argv[2] == "a" * 40 + ":bootstrap/templates/factory-lifecycle-" + provider + ".yml"
            return source_template
        if argv[:2] == ["gh", "secret"]:
            assert argv[4:] == ["--repo", "github.com/org/repo", "--env", "factory"]
            if argv[2] == "set":
                protected_chunks[argv[3]] = data
            else:
                assert argv[2] == "delete"
                del protected_chunks[argv[3]]
            return ""
        if argv[:2] == ["gh", "api"] and "user" not in argv:
            method = argv[argv.index("--method") + 1]
            endpoint = next(value for value in argv if value.startswith("repos/"))
            response = github(method, endpoint, json.loads(data) if data else None)
            return json.dumps(response) if response is not None else ""
        return original_command(argv, cwd=cwd)

    def request(method, url, audience, data=None, headers=None, allowed=(200,)):
        base = "https://dev.azure.com/org/project/_apis"
        if not url.startswith(base):
            return original_request(method, url, audience, data, headers, allowed)
        path = url.removeprefix(base)
        if method == "GET" and path.startswith("/serviceendpoint/endpoints?"):
            body = {"value": [{"name": "factory", "authorization": {"scheme": "WorkloadIdentityFederation",
                     "parameters": {"tenantid": data_snapshot["scales"][0]["tenant_id"]}},
                     "data": {"subscriptionId": data_snapshot["scales"][0]["subscription_id"]}}]}
        elif method == "GET" and path.startswith("/git/repositories/repo/items?"):
            body = {"content": source_template}
        elif method == "GET" and path.startswith("/build/definitions?"):
            body = {"value": [{"id": 8, "repository": {"name": "repo"},
                                "process": {"yamlFilename": fl.SCOPED_ADO}, "queueStatus": "enabled"}]}
        elif method == "POST" and path.startswith("/pipelines/8/runs?"):
            assert data["variables"]["AIFACTORY_ENVELOPE_JSON"]["isSecret"] is True
            body = {"id": run_worker(json.loads(data["variables"]["AIFACTORY_ENVELOPE_JSON"]["value"]))}
        elif method == "GET" and (path.startswith("/pipelines/8/runs/") or path.startswith("/build/builds/")):
            body = run_status(int(path.split("?", 1)[0].rsplit("/", 1)[1]))
        else:
            raise AssertionError(("Factory API/unreviewed HTTP forbidden", method, path))
        return 200, {}, body

    def provider_read(kind, method, endpoint, body, allowed):
        assert kind == provider and method == "GET"
        if kind == "gha":
            return 200, {}, github(method, endpoint, body)
        return request(method, endpoint, "https://app.vssps.visualstudio.com/", data=body, allowed=allowed)

    data_snapshot = data
    cloud.command, cloud.request, cloud.state_request = command, request, provider_read
    review.verify.return_value = {"provider": provider, "run_id": "42", "attempt": 1}
    admission = Mock(spec=["acquire", "assert_owned", "release"])
    admission.acquire.return_value = {"id": "test-authenticated-claim"}
    store = Store()
    executor = adapters.NativeExecutor(source, workspace / "native", cloud_factory=lambda _: cloud)
    service = runtime.LifecycleService(store=store, planner=planner, executor=executor, review=review, admission=admission)
    prepared_operation = service.prepare(data)
    manifest = prepared_operation["plan"]["stages"][0]["manifests"][0]
    assert not cloud.arm_writes and not cloud.deleted
    assert fl.validate_manifest(manifest)
    completed = service.execute(prepared_operation["operation_id"], data, prepared_operation["plan_hash"])
    assert completed["status"] == "succeeded", completed["stages"][0].get("receipt", completed.get("error_code"))
    proof = completed["stages"][0]["receipt"]
    assert proof["verified"] is True and proof["children"]
    assert store.records[completed["operation_id"]]["stages"][0]["receipt"] == proof
    assert not cloud.leases
    if scenario < 4:
        assert cloud.arm_writes and proof["children"][0]["worker"]["resource_groups"]
        assert proof["children"][0]["worker"]["ownership"]
    else:
        deleted = {row["id"].lower() for row in
                   manifest["deletion"]["resources"] + manifest["deletion"]["resource_groups"] if row["delete"]}
        native = proof["children"][0]["native"]
        assert deleted == {item.lower() for item in
                           native.get("deleted_resources", []) + native.get("deleted_resource_groups", [])}
        delete_requests = {item.lower() for item in cloud.deleted}
        assert delete_requests <= deleted
        assert all(any(item == root or item.startswith(root + "/") for root in delete_requests) for item in deleted)
        assert all(resource not in cloud.bodies for resource in deleted)
        retained = {row["id"].lower() for row in
                    manifest["deletion"]["resources"] + manifest["deletion"]["resource_groups"] if not row["delete"]}
        assert retained <= set(cloud.bodies)
        if scenario == 4:
            assert COMMON.lower() in retained and cloud.bodies[common_ip.lower()] == common_before
        if scenario == 6:
            order = [item.lower() for item in cloud.deleted]
            assert order.index(GROUP.lower()) < order.index(common_ip.lower())
    assert all(cloud.bodies.get(key) == value for key, value in platform.items())
    assert "runs/" + manifest["run_id"] + ".json" in cloud.runs
    assert not protected_chunks and not refs
    counts = len(provider_runs), len(cloud.arm_writes), len(cloud.deleted)
    assert service.reconcile(completed["operation_id"])["status"] == "succeeded"
    assert counts == (len(provider_runs), len(cloud.arm_writes), len(cloud.deleted))
