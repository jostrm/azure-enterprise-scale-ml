"""The Function approves one scope and calls one SDK facade method, including on the runner."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azurefactory import esaf
from azurefactory.errors import BlockedError, RequestTimeout

from aif_lifecycle import runner
from aif_lifecycle.adapters.runner_backend import RunnerBackend
from aif_lifecycle.adapters.mock_backend import MockFactoryBackend
from aif_lifecycle.adapters.sdk_backend import SdkFactoryBackend
from aif_lifecycle.adapters.simulated_deletes import CatalogMirror, DeleteRoutingTracker, DeleteSimulation
from aif_lifecycle.adapters.stores import MemoryStore
from aif_lifecycle.adapters.trackers import ApiJobTracker, InstantTracker, RunnerJobTracker
from aif_lifecycle.application.guard import SelfProtection
from aif_lifecycle.application.runner_protocol import decode_request
from aif_lifecycle.application.service import LifecycleService
from aif_lifecycle.domain.errors import InvalidState, ProtectedTarget
from aif_lifecycle.http_api import ApiRequest, LifecycleHttpApi

from support import FakeGitHub, confirm_current, sequential_ids

FOLDER = r"C:\repos\consumer\azurefactory"
FACTORY = "11111111-1111-4111-8111-111111111111"
SCALE = "22222222-2222-4222-8222-222222222222"
PROJECT = "33333333-3333-4333-8333-333333333333"
METHODS = ("init_factory", "add_scale_set", "apply_project", "delete_project", "delete_scale_set", "delete_factory")
CATALOG = {
    "revision": "revision-1",
    "factories": [{
        "id": FACTORY, "key": "sample-swedencentral", "prefix": "sample-", "region": "swedencentral",
        "region_short_name": "sdc",
        "scale_sets": [{"id": SCALE, "suffix": "001", "environment": "dev"}],
        "projects": [{"id": PROJECT, "number": "001", "key": "project001",
                      "placements": [{"environment": "dev", "scale_set_id": SCALE}]}],
    }],
}
CASES = (
    ("init-factory", {"factoryId": "new-sdc-dev", "bootstrapConfig": {"subscription_id": "subscription"}},
     "init_factory", (), "workflow"),
    ("add-scaleset", {"scalesetId": "sample-sdc-dev-002", "scaleSet": {"vnetCidr": "10.20.0.0/16"}},
     "add_scale_set", ("002",), "catalog"),
    ("add-or-update-project", {"projectId": "sample-esml-project001-sdc-dev-001-rg",
                               "settings": {"enableAISearch": "true"}},
     "apply_project", ("001",), "catalog"),
    ("delete-project", {"projectId": "sample-esml-project001-sdc-dev-001-rg", "includeProjectSubnets": False},
     "delete_project", ("001",), "catalog"),
    ("delete-scaleset", {"scalesetId": "sample-sdc-dev-001"}, "delete_scale_set", ("001",), "catalog"),
    ("delete-factory", {"factoryId": "sample-sdc-dev"}, "delete_factory", (), "factory-deletion"),
)


class ReadClient:
    def __init__(self):
        self.payload = copy.deepcopy(CATALOG)
        self.reads = []
        self.state = {"status": "succeeded"}

    def catalog_list(self, folder):
        self.reads.append(("catalog", folder))
        return copy.deepcopy(self.payload)

    def catalog_job(self, folder, identifier):
        self.reads.append(("catalog-job", folder, identifier))
        return {"job": dict(self.state)}

    def creation_workflow_status(self, folder, identifier):
        self.reads.append(("workflow", folder, identifier))
        return dict(self.state)

    def delete_aifactory_status(self, folder, identifier):
        self.reads.append(("factory-deletion", folder, identifier))
        return {"job": dict(self.state)}


def fake_facade():
    facade = SimpleNamespace(Session=esaf.Session, EsafJob=esaf.EsafJob)
    for method in METHODS:
        kind = "workflow" if method == "init_factory" else "factory-deletion" if method == "delete_factory" else "catalog"

        def start(*args, _method=method, _kind=kind, **kwargs):
            return esaf.EsafJob(_method, _kind, "job-" + _method, kwargs["session"])

        setattr(facade, method, Mock(side_effect=start))
    return facade


def harness(clock, monkeypatch, *, executor="inprocess", deletes=True, protected=()):
    client, facade, store, github = ReadClient(), fake_facade(), MemoryStore(), FakeGitHub()
    sdk = SdkFactoryBackend("http://127.0.0.1:8765", None, FOLDER, client=client, facade=facade,
                            clock=clock, allow_deletes=deletes, review_ttl_seconds=90)
    backend = sdk
    tracker = ApiJobTracker(sdk)
    if executor == "github-runner":
        backend = RunnerBackend(github, store, clock, workflow="aif-ops.yml", ref="main", backend="sdk",
                                secret=b"local-test-secret", request_ttl_seconds=4200, allow_deletes=deletes)
        backend.accept_catalog(client.catalog_list(FOLDER))
        tracker = RunnerJobTracker(backend, github)
        monkeypatch.setattr(runner, "factory_api_backend", lambda *args, **kwargs: sdk)
    service = LifecycleService(backend=backend, tracker=tracker, store=store, guard=SelfProtection(protected),
                               clock=clock, ids=sequential_ids(), poll_after_seconds=1, runner_timeout_seconds=4200)
    return SimpleNamespace(service=service, sdk=sdk, client=client, facade=facade, store=store, github=github,
                           api=LifecycleHttpApi(service, event_secrets=[b"local-test-secret"]))


def finish_handoff(h, clock):
    wire = h.github.dispatches[-1]["inputs"]["request"]
    request = decode_request(wire, [b"local-test-secret"], now=clock.now().timestamp())
    result = runner.execute(request, {"AIF_FACTORY_FOLDER": FOLDER, "AIF_ALLOW_REAL_DELETES": "true"}, None)
    h.service.apply_runner_result(result)
    return request


@pytest.mark.parametrize("executor", ["inprocess", "github-runner"])
@pytest.mark.parametrize("slug,body,method,args,kind", CASES)
def test_scenario_routes_invoke_one_facade_method_and_persist_job(clock, monkeypatch, executor, slug, body,
                                                               method, args, kind):
    h = harness(clock, monkeypatch, executor=executor)
    response = h.api.prepare(ApiRequest("POST", f"/api/v1/lifecycle/{slug}/prepare",
                                       route_params={"scenario": slug}, body=json.dumps(body).encode()))
    assert response.status == 202
    public = json.loads(response.body)
    assert len(public["steps"]) == 1
    if executor == "github-runner":
        finish_handoff(h, clock)
    operation = h.service.get(public["operationId"])
    assert operation.status.value == "awaiting_confirmation"
    assert all(getattr(h.facade, name).call_count == 0 for name in METHODS)
    assert "scope" in " ".join(operation.step.preview.warnings).lower()
    assert operation.step.preview.expires_at == clock.now().timestamp() + 90
    operation = confirm_current(h.service, operation)
    if executor == "github-runner":
        request = finish_handoff(h, clock)
        assert request.request.kind.value == "scenario"
        operation = h.service.get(operation.id)
    assert operation.status.value == "running"
    assert operation.step.job["job_id"] == "job-" + method
    assert operation.step.job["job_kind"] == kind
    call = getattr(h.facade, method)
    assert call.call_count == 1
    assert call.call_args.args == args
    kwargs = call.call_args.kwargs
    assert kwargs["session"].folder == FOLDER
    assert kwargs["session"].factory == (None if method == "init_factory" else FACTORY)
    assert not kwargs.get("wait", False)
    assert all(getattr(h.facade, name).call_count == (1 if name == method else 0) for name in METHODS)
    if method == "init_factory":
        assert kwargs["creation_request"]["folder"] == r"C:\repos\consumer"
        assert kwargs["creation_request"]["config"]["factory_prefix"] == "new-"
        assert kwargs["creation_request"]["config"]["location"] == "swedencentral"
        assert kwargs["poll"] == 1
    if method == "add_scale_set":
        assert kwargs["cidr"] == "10.20.0.0/16"
        assert kwargs["environment"] == "dev"
    if method in ("apply_project", "delete_project"):
        assert kwargs["scale_set"] == "001"
        assert kwargs["environment"] == "dev"
    if method == "apply_project":
        assert kwargs["settings"] == body["settings"]
    if method == "delete_project":
        assert kwargs["include_project_subnets"] is False
        assert kwargs["include_keyvault_and_resource_group"] is True
    if method == "delete_scale_set":
        assert kwargs["environment"] == "dev"
    # A fresh adapter can follow a persisted handle without a background thread or in-memory job registry.
    restarted = SdkFactoryBackend("http://127.0.0.1:8765", None, FOLDER, client=h.client, facade=h.facade, clock=clock)
    assert restarted.job_status(operation.step.job)["status"] == "succeeded"
    clock.advance(1)
    h.service.reconcile()
    if executor == "github-runner":
        finish_handoff(h, clock)
    assert h.service.get(operation.id).status.value == "succeeded"
    with pytest.raises(InvalidState):
        confirm_current(h.service, operation)
    assert call.call_count == 1


@pytest.mark.parametrize("slug,body,method,args,kind", CASES[3:])
def test_facade_deletes_require_opt_in_before_catalog_or_dispatch(clock, monkeypatch, slug, body, method, args, kind):
    h = harness(clock, monkeypatch, deletes=False)
    response = h.api.prepare(ApiRequest("POST", "/prepare", route_params={"scenario": slug},
                                       body=json.dumps(body).encode()))
    assert response.status == 403
    assert json.loads(response.body)["code"] == "deletes-disabled"
    assert h.client.reads == []
    assert h.service.list() == []
    assert all(getattr(h.facade, name).call_count == 0 for name in METHODS)


def test_facade_preserves_self_protection(clock, monkeypatch):
    h = harness(clock, monkeypatch, protected=["sample-esml-project001-sdc-dev-001-rg"])
    with pytest.raises(ProtectedTarget):
        h.service.prepare("delete-factory", {"factoryId": "sample-sdc-dev"})
    assert h.client.reads == []


@pytest.mark.parametrize("error", [BlockedError("deployment blocked after configuration"), RequestTimeout("timeout")])
def test_facade_partial_failures_are_uncertain_and_never_retried(clock, monkeypatch, error):
    h = harness(clock, monkeypatch)
    h.facade.apply_project.side_effect = error
    operation = h.service.prepare(CASES[2][0], CASES[2][1])
    operation = confirm_current(h.service, operation)
    assert operation.status.value == "uncertain"
    clock.advance(1)
    h.service.reconcile()
    assert h.facade.apply_project.call_count == 1


def test_facade_refuses_scope_changes_but_not_revision_drift(clock, monkeypatch):
    h = harness(clock, monkeypatch)
    operation = h.service.prepare(CASES[2][0], CASES[2][1])
    h.client.payload["revision"] = "unrelated-revision"
    assert confirm_current(h.service, operation).status.value == "running"
    assert h.facade.apply_project.call_count == 1
    h = harness(clock, monkeypatch)
    operation = h.service.prepare(CASES[2][0], CASES[2][1])
    h.client.payload["factories"][0]["id"] = "different-factory"
    operation = confirm_current(h.service, operation)
    assert operation.status.value == "failed"
    assert operation.step.failure["code"] == "scope-changed"
    h.facade.apply_project.assert_not_called()


@pytest.mark.parametrize("body", [
    {"scalesetId": "sample-sdc-dev-002"},
    {"scalesetId": "sample-sdc-dev-002", "scaleSet": {"vnetCidr": "invalid"}},
    {"scalesetId": "sample-sdc-dev-002", "scaleSet": {"vnetCidr": "10.20.0.0/16", "commonSubnets": {"x": "y"}}},
    {"factoryId": "new-sdc-prod", "bootstrapConfig": {}},
    {"factoryId": "new-sdc-dev"},
])
def test_facade_invalid_inputs_fail_before_execution(clock, monkeypatch, body):
    h = harness(clock, monkeypatch)
    slug = "add-scaleset" if "scalesetId" in body else "init-factory"
    operation = h.service.prepare(slug, body)
    assert operation.status.value == "failed"
    assert all(getattr(h.facade, name).call_count == 0 for name in METHODS)


def test_facade_missing_job_handle_is_not_reported_as_success(clock, monkeypatch):
    h = harness(clock, monkeypatch)
    h.facade.apply_project.side_effect = None
    h.facade.apply_project.return_value = esaf.EsafJob("apply_project", "catalog", None,
                                                     esaf.Session(FOLDER, h.client, FACTORY))
    operation = confirm_current(h.service, h.service.prepare(CASES[2][0], CASES[2][1]))
    assert operation.status.value == "uncertain"


@pytest.mark.parametrize("slug,body,expected", [
    ("add-or-update-project", {"projectId": "aif-121-esml-project001-sdc-dev-001-rg",
                               "settings": {"enableAISearch": "true"}}, ["configure-settings", "deploy"]),
    ("add-or-update-project", {"projectId": "aif-121-esml-project002-sdc-dev-001-rg"}, ["add-project", "deploy"]),
    ("add-scaleset", {"scalesetId": "aif-121-sdc-dev-002", "scaleSet": {"vnetCidr": "10.121.64.0/18",
                      "subscriptionId": "f0fe8b33-73bf-41e4-9997-e3920d793c06",
                      "tenantId": "c157e61b-4a1e-488c-9a0c-d9a23e864a65", "orchestrator": "gha"}},
     ["create-scale-set", "deploy"]),
])
def test_sdk_scenario_uses_real_facade_and_http_client(clock, slug, body, expected):
    from fake_factory_api import FakeFactoryApi

    with FakeFactoryApi(stateful=True) as upstream:
        backend = SdkFactoryBackend(upstream.url, upstream.api_key, FOLDER, clock=clock)
        service = LifecycleService(backend=backend, tracker=ApiJobTracker(backend), store=MemoryStore(),
                                   guard=SelfProtection(()), clock=clock, runner_timeout_seconds=4200)
        operation = service.prepare(slug, body)
        assert operation.status.value == "awaiting_confirmation"
        assert not any(call["method"] == "POST" for call in upstream.calls)
        operation = confirm_current(service, operation)
        assert operation.status.value == "running", operation.step.failure
        bodies = [call["body"] for call in upstream.calls if call["path"] == "/api/v1/factory-catalog/prepare"]
        assert [body["action"] for body in bodies] == expected
        assert backend.job_status(operation.step.job)["status"] == "succeeded"
        if body.get("settings"):
            assert upstream.state.document["configurations"][PROJECT] == body["settings"]
        if slug == "add-scaleset":
            new_scale = next(s for s in upstream.state.factory["scale_sets"] if s["suffix"] == "002")
            assert bodies[-1]["scale_set_id"] == new_scale["id"]
            assert bodies[-1].get("project_id") is None


def test_sdk_simulated_deletion_does_not_invoke_facade(clock, monkeypatch):
    h = harness(clock, monkeypatch, deletes=False)
    simulator = MockFactoryBackend(CatalogMirror(h.sdk.catalog_payload), clock=clock)
    backend = DeleteSimulation(h.sdk, simulator)
    service = LifecycleService(backend=backend, tracker=DeleteRoutingTracker(ApiJobTracker(h.sdk), InstantTracker()),
                               store=h.store, guard=SelfProtection(()), clock=clock, runner_timeout_seconds=4200)
    operation = confirm_current(service, service.prepare("delete-factory", {"factoryId": "sample-sdc-dev"}))
    assert operation.status.value == "succeeded"
    assert operation.step.job["simulated"] is True
    assert all(getattr(h.facade, name).call_count == 0 for name in METHODS)
    assert h.client.payload == CATALOG


def test_enrollment_noop_does_not_override_a_runtime_coverage_refusal(clock, monkeypatch):
    from fake_factory_api import ENROLLED_BLOCKER, FakeFactoryApi

    with FakeFactoryApi(stateful=True) as upstream:
        original = upstream.state.enroll_prepare
        monkeypatch.setattr(upstream.state, "enroll_prepare", lambda body: {
            **original(body), "can_execute": False, "blockers": [ENROLLED_BLOCKER]})
        backend = SdkFactoryBackend(upstream.url, upstream.api_key, FOLDER, clock=clock)
        service = LifecycleService(backend=backend, tracker=ApiJobTracker(backend), store=MemoryStore(),
                                   guard=SelfProtection(()), clock=clock, runner_timeout_seconds=4200)
        operation = service.prepare("add-or-update-project",
                                    {"projectId": "aif-121-esml-project002-sdc-dev-001-rg"})
        operation = confirm_current(service, operation)
        assert operation.status.value == "uncertain"
        assert any(p["number"] == "002" for p in upstream.state.factory["projects"])
        assert all(body["action"] != "deploy" for body in upstream.state.pending.values()
                   if "action" in body)
        assert "do not cover" in operation.step.failure["detail"]


def test_guardless_server_cannot_dispatch_project_through_function(clock, monkeypatch):
    from fake_factory_api import FakeFactoryApi

    with FakeFactoryApi(stateful=True) as upstream:
        original = upstream.state.prepare

        def guardless(body):
            preview = original(body)
            preview.pop("runtime_scope_authorization", None)
            return preview

        monkeypatch.setattr(upstream.state, "prepare", guardless)
        backend = SdkFactoryBackend(upstream.url, upstream.api_key, FOLDER, clock=clock)
        service = LifecycleService(backend=backend, tracker=ApiJobTracker(backend), store=MemoryStore(),
                                   guard=SelfProtection(()), clock=clock, runner_timeout_seconds=4200)
        operation = service.prepare("add-or-update-project",
                                    {"projectId": "aif-121-esml-project001-sdc-dev-001-rg"})
        operation = confirm_current(service, operation)
        assert operation.status.value == "uncertain"
        assert "missing live scope authorization" in operation.step.failure["detail"]
        assert upstream.state.jobs == 0
        assert not any(call["path"] == "/api/v1/factory-catalog/confirm" for call in upstream.calls)
