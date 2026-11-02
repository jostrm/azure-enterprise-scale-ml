"""Function-safe facade contracts, using only in-memory API doubles."""

import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from azurefactory import esaf
from azurefactory.client import AzureFactoryClient, canonical_json_hash
from azurefactory.errors import APIError, BlockedError, ConfigError, FailureError
from azurefactory.scale_set_enrollment import BLOB_BLOCKER


FOLDER = r"C:\consumer\azurefactory"
WORKFLOW = "33333333-3333-4333-8333-333333333333"
CONFIRMATION = "11111111-1111-4111-8111-111111111111"
DEV_SUB = "44444444-4444-4444-8444-444444444444"
TEST_SUB = "55555555-5555-4555-8555-555555555555"
OK = {"can_execute": True, "blockers": [], "confirmation_id": CONFIRMATION,
      "preview_hash": "a" * 64, "confirmation_phrase": "APPROVE"}
CREATION = {
    "contract_version": 1, "mode": "full-bootstrap", "folder": r"C:\consumer", "orchestrator": "gha",
    "config": {"factory_prefix": "unit", "location": "swedencentral", "scale_set_number": "002",
               "coordination_mode": "single-writer", "github_repository": "example/consumer"},
    "region_short_name": "sdc",
}


def catalog():
    return {"revision": "revision-1", "factories": [{
        "id": "factory", "key": "unit-sdc", "prefix": "unit", "region": "swedencentral",
        "aifactory_version": "125",
        "scale_sets": [
            {"id": "dev-scale", "suffix": "002", "environment": "dev", "subscription_id": DEV_SUB,
             "tenant_id": "tenant", "orchestrator": "gha"},
            {"id": "test-scale", "suffix": "002", "environment": "test", "subscription_id": TEST_SUB,
             "tenant_id": "tenant", "orchestrator": "gha"},
        ],
        "projects": [
            {"id": "dev-project", "number": "001",
             "placements": [{"environment": "dev", "scale_set_id": "dev-scale"}]},
            {"id": "test-project", "number": "001",
             "placements": [{"environment": "test", "scale_set_id": "test-scale"}]},
        ],
    }]}


def workflow_review(body):
    expires = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    authorization = {
        "contract": "bounded-full-bootstrap-v1", "approval_mode": "whole-workflow", "workflow_id": WORKFLOW,
        "scope": body["scope"], "source_revision": body["expected_revision"],
        "stages": [{"stage": "common-deployment"}, {"stage": "project-deployment"}],
        "target": {"subscription_id": "dev-sub"}, "template_fingerprint": "b" * 64,
        "program_fingerprint": "c" * 64, "expires_at": expires,
    }
    authorization["authorization_hash"] = canonical_json_hash(authorization)
    return {**OK, "contract_version": 1, "workflow_id": WORKFLOW, "scope": body["scope"],
            "stage": "repository-initialization", "source_revision": body["expected_revision"],
            "input_hash": "d" * 64, "effects": ["Create the reviewed factory"], "expires_at": expires,
            "review": {"workflow_authorization": authorization}}


class Client:
    def __init__(self):
        self.document = catalog()
        self.calls = []
        self.pending = None
        self.after_authorization = None
        self.confirmed = {"job": {"id": "job", "status": "queued"}}

    def record(self, name, *args, **kwargs):
        self.calls.append((name, copy.deepcopy(args), copy.deepcopy(kwargs)))
        return copy.deepcopy(OK)

    def catalog_list(self, folder):
        self.record("catalog_list", folder)
        return copy.deepcopy(self.document)

    def catalog_prepare(self, body):
        review = self.record("catalog_prepare", body)
        if body.get("project_id") is not None:
            review["runtime_scope_authorization"] = self.runtime_proof(
                body["factory_id"], body["scale_set_id"], body["project_id"])
        return review

    def runtime_proof(self, factory_id, scale_id, project_id):
        factory = next(f for f in self.document["factories"] if f["id"] == factory_id)
        scale = next(s for s in factory["scale_sets"] if s["id"] == scale_id)
        project = next(p for p in factory["projects"] if p["id"] == project_id)
        assert {"environment": scale["environment"], "scale_set_id": scale_id} in project["placements"]
        group = f"unit-esml-project{project['number']}-sdc-{scale['environment']}-{scale['suffix']}-rg"
        return {"factory_id": factory_id, "scale_set_id": scale_id, "project_id": project_id,
                "resource_group_id": f"/subscriptions/{scale['subscription_id']}/resourcegroups/{group}",
                "enrolled": True, "delete_authorized": True}

    def catalog_confirm(self, folder, confirmation_id):
        self.record("catalog_confirm", folder, confirmation_id)
        if self.pending:
            collection, value = self.pending
            self.document["factories"][0][collection].append(value)
            self.pending = None
        self.document["revision"] += "+"
        return copy.deepcopy(self.confirmed)

    def project_add_prepare(self, folder, factory_id, **kwargs):
        self.pending = ("projects", {"id": "new-project", "number": kwargs["number"],
                                     "placements": kwargs["placements"]})
        return self.record("project_add_prepare", folder, factory_id, **kwargs)

    def catalog_settings_prepare(self, folder, factory_id, settings, **kwargs):
        return self.record("catalog_settings_prepare", folder, factory_id, settings, **kwargs)

    def project_delete_prepare(self, *args, **kwargs):
        return {**self.record("project_delete_prepare", *args, **kwargs),
                "runtime_scope_authorization": self.runtime_proof(args[1], kwargs["scale_set_id"], args[2])}

    def scaleset_delete_prepare(self, *args, **kwargs):
        return self.record("scaleset_delete_prepare", *args, **kwargs)

    def authorize_deletion_prepare(self, body):
        return self.record("authorize_deletion_prepare", body)

    def authorize_deletion_confirm(self, **kwargs):
        self.record("authorize_deletion_confirm", **kwargs)
        self.document["revision"] = "authorized-revision"
        if self.after_authorization:
            self.after_authorization(self.document)
        return {"status": "authorized"}

    def scaleset_add_prepare(self, folder, factory_id, scales, **kwargs):
        self.pending = ("scale_sets", {**scales[0], "id": "new-scale"})
        return self.record("scaleset_add_prepare", folder, factory_id, scales, **kwargs)

    def enroll_scale_set_prepare(self, body):
        return self.record("enroll_scale_set_prepare", body)

    def enroll_scale_set_confirm(self, **kwargs):
        self.record("enroll_scale_set_confirm", **kwargs)
        self.document["revision"] += "+"
        return {"status": "enrolled"}

    def delete_aifactory_prepare(self, body):
        return self.record("delete_aifactory_prepare", body)

    def delete_aifactory_confirm(self, **kwargs):
        self.record("delete_aifactory_confirm", **kwargs)
        return self.confirmed


class BootstrapClient(AzureFactoryClient):
    """Use real public client methods, replacing only the HTTP transport."""

    def __init__(self, *, fallback=False, change=None):
        super().__init__("https://factory.invalid", "unit-test-key")
        self.calls = []
        self.document = catalog()
        self.fallback = fallback
        self.change = change
        self.review = None

    def request(self, method, path, *, body=None, query=None, **kwargs):
        self.calls.append((method, path, copy.deepcopy(body), query))
        if path.endswith("/creation/prepare"):
            result = {**OK, "folder": FOLDER}
            if self.change == "creation-blocked":
                result.update(can_execute=False, blockers=["creation denied"])
            elif self.change == "creation-contradiction":
                result["blockers"] = ["creation denied"]
            elif self.change == "creation-folder":
                result["folder"] = r"C:\different\azurefactory"
            return result
        if path.endswith("/creation/confirm"):
            if self.change == "confirm-error":
                raise APIError("save failed")
            return {} if self.fallback else {"catalog": copy.deepcopy(self.document)}
        if method == "GET" and path == "/api/v1/factory-catalog":
            return copy.deepcopy(self.document)
        if path.endswith("/workflows/prepare"):
            self.review = workflow_review(body)
            if self.change == "workflow-blocked":
                self.review.update(can_execute=False, blockers=["workflow denied"])
            elif self.change == "workflow-contradiction":
                self.review["blockers"] = ["workflow denied"]
            elif self.change == "missing-authorization":
                self.review["review"] = {}
            elif self.change == "tampered-authorization":
                self.review["review"]["workflow_authorization"]["authorization_hash"] = "f" * 64
            elif self.change == "scope":
                self.review["scope"] = {**body["scope"], "scale_set_id": "wrong"}
            elif self.change == "missing-workflow-id":
                del self.review["workflow_id"]
            return copy.deepcopy(self.review)
        if path.endswith("/workflows/start"):
            if self.change == "start-error":
                raise APIError("dispatch failed")
            if self.change == "start-failed":
                return {"workflow_id": WORKFLOW, "status": "failed", "message": "provider denied"}
            if self.change == "start-wrong-id":
                return {"workflow_id": CONFIRMATION, "status": "queued"}
            return {"workflow_id": WORKFLOW, "status": "queued", "requires_review": False}
        raise AssertionError(f"Unexpected API call: {method} {path}")


def session(client):
    return esaf.Session(FOLDER, client, "unit-sdc")


def call(client, name):
    return next(row for row in client.calls if row[0] == name)


@pytest.mark.parametrize("fallback,initial_project", [(False, True), (True, True), (False, False)])
def test_fresh_bootstrap_submits_one_server_owned_workflow(monkeypatch, fallback, initial_project):
    monkeypatch.setattr(esaf.threading, "Thread", Mock(side_effect=AssertionError("No Function daemon")))
    monkeypatch.setattr(esaf.time, "sleep", Mock(side_effect=AssertionError("No Function polling")))
    client = BootstrapClient(fallback=fallback)
    if not initial_project:
        client.document["factories"][0]["projects"] = []
    request = copy.deepcopy(CREATION)
    if not initial_project:
        request["initial_project"] = None
    expected_request = copy.deepcopy(request)
    s = session(client)
    job = esaf.init_factory(creation_request=request, poll=1, session=s)
    assert request == expected_request
    assert (job.kind, job.id, job.session, job._thread) == ("workflow", WORKFLOW, s, None)
    assert client.calls[0][2] == expected_request
    assert client.calls[1][2] == {"contract_version": 1, "folder": FOLDER, "confirmation_id": CONFIRMATION}
    body = next(row[2] for row in client.calls if row[1].endswith("/workflows/prepare"))
    scope = {"folder": FOLDER, "factory_id": "factory", "scale_set_id": "dev-scale", "project_id": None}
    if initial_project:
        scope["project_id"] = "dev-project"
    assert body == {"contract_version": 1, "operation": "create-factory",
                    "execution_mode": "privileged-bootstrap", "creation_mode": "full-bootstrap",
                    "scope": scope, "expected_revision": "revision-1", "bootstrap_config": CREATION["config"],
                    "approval_mode": "whole-workflow", "authorization_valid_for_seconds": 21600}
    starts = [row for row in client.calls if row[1].endswith("/workflows/start")]
    assert [row[2] for row in starts] == [
        {"folder": FOLDER, "workflow_id": WORKFLOW, "confirmation_id": CONFIRMATION,
         "authorization_hash": client.review["review"]["workflow_authorization"]["authorization_hash"]}]


@pytest.mark.parametrize("change,error,message", [
    ("creation-blocked", BlockedError, "creation denied"),
    ("creation-contradiction", BlockedError, "creation denied"),
    ("creation-folder", ConfigError, "folder"),
    ("confirm-error", APIError, "save failed"),
    ("workflow-blocked", BlockedError, "workflow denied"),
    ("workflow-contradiction", BlockedError, "workflow denied"),
    ("missing-authorization", ConfigError, "review|authorization"),
    ("tampered-authorization", ConfigError, "hash"),
    ("scope", ConfigError, "scope"),
    ("missing-workflow-id", ConfigError, "ID"),
    ("start-error", APIError, "dispatch failed"),
    ("start-failed", FailureError, "provider denied"),
    ("start-wrong-id", FailureError, "workflow"),
])
def test_fresh_bootstrap_fails_closed_and_surfaces_errors(change, error, message):
    client = BootstrapClient(change=change)
    with pytest.raises(error, match=message):
        esaf.init_factory(creation_request=copy.deepcopy(CREATION), session=session(client))
    if change.startswith("creation-"):
        assert not any(row[1].endswith("/confirm") for row in client.calls)
    if not change.startswith("start-"):
        assert not any(row[1].endswith("/workflows/start") for row in client.calls)


@pytest.mark.parametrize("change", ["missing-factory", "ambiguous-factory", "missing-scale", "ambiguous-project"])
def test_fresh_bootstrap_requires_exact_created_scope(change):
    client = BootstrapClient()
    factory = client.document["factories"][0]
    if change == "missing-factory":
        factory["prefix"] = "other"
    elif change == "ambiguous-factory":
        client.document["factories"].append(copy.deepcopy(factory))
    elif change == "missing-scale":
        factory["scale_sets"] = factory["scale_sets"][1:]
    else:
        factory["projects"].append(copy.deepcopy(factory["projects"][0]))
    with pytest.raises(ConfigError):
        esaf.init_factory(creation_request=copy.deepcopy(CREATION), session=session(client))
    assert not any("/workflows/" in row[1] for row in client.calls)


@pytest.mark.parametrize("extra", [{"workflow_id": WORKFLOW}, {"request": {"scope": {}}},
                                  {"creation_request": {"mode": "other"}}])
def test_bootstrap_input_conflicts_fail_before_writes(extra):
    client = BootstrapClient()
    kwargs = {"creation_request": copy.deepcopy(CREATION), **extra}
    with pytest.raises(ConfigError):
        esaf.init_factory(**kwargs, session=session(client))
    assert not client.calls


def test_bootstrap_wait_uses_the_returned_job(monkeypatch):
    wait = Mock(return_value={"status": "succeeded"})
    monkeypatch.setattr(esaf.EsafJob, "wait", wait)
    monkeypatch.setattr(esaf.threading, "Thread", Mock(side_effect=AssertionError("No daemon")))
    client = BootstrapClient()
    job = esaf.init_factory(creation_request=copy.deepcopy(CREATION), wait=True, poll=1, session=session(client))
    wait.assert_called_once_with(poll=1)
    assert job.id == WORKFLOW


def test_workflow_wait_follows_server_owned_between_stage_state(monkeypatch):
    client = Mock()
    client.creation_workflow_status.side_effect = [
        {"status": "awaiting-review", "requires_review": False},
        {"status": "running"}, {"status": "succeeded"}]
    monkeypatch.setattr(esaf.time, "sleep", Mock())
    job = esaf.EsafJob("init_factory", "workflow", WORKFLOW, session(client))
    assert job.wait(poll=0)["status"] == "succeeded"


@pytest.mark.parametrize("method", ["apply_project", "upsert_project", "delete_project"])
@pytest.mark.parametrize("shared_project", [False, True])
def test_project_calls_select_exact_project_and_placement(method, shared_project):
    client = Client()
    factory = client.document["factories"][0]
    if shared_project:
        factory["projects"][0]["placements"] += factory["projects"][1]["placements"]
        factory["projects"] = factory["projects"][:1]
    expected_project = "dev-project" if shared_project else "test-project"
    options = {} if method == "delete_project" else {"settings": {"tag_costcenter": "unit"}}
    job = getattr(esaf, method)("001", scale_set="002", environment="test", session=session(client), **options)
    assert job.id == "job" and job.kind == "catalog"
    if method == "delete_project":
        _, args, kwargs = call(client, "project_delete_prepare")
        assert args == (FOLDER, "factory", expected_project)
        assert kwargs["environments"] == ["test"] and kwargs["scale_set_id"] == "test-scale"
        assert kwargs["expected_revision"] == "authorized-revision"
    else:
        _, args, kwargs = call(client, "catalog_settings_prepare")
        assert args == (FOLDER, "factory", {"tag_costcenter": "unit"})
        assert kwargs["project_id"] == expected_project and kwargs["scale_set_id"] == "test-scale"
        body = call(client, "catalog_prepare")[1][0]
        assert body["project_id"] == expected_project and body["scale_set_id"] == "test-scale"
        assert body["expected_revision"] == "revision-1++"
        assert not any(row[0] == "project_add_prepare" for row in client.calls)


@pytest.mark.parametrize("method", ["apply_project", "upsert_project", "delete_project", "delete_scale_set"])
def test_unambiguous_legacy_scope_still_works(method):
    client = Client()
    factory = client.document["factories"][0]
    factory["scale_sets"] = factory["scale_sets"][:1]
    factory["projects"] = factory["projects"][:1]
    number = "002" if method == "delete_scale_set" else "001"
    assert getattr(esaf, method)(number, session=session(client)).id == "job"
    assert "apply_project" in esaf.__all__ and "upsert_project" in esaf.__all__


@pytest.mark.parametrize("number", ["001", "003"])
def test_apply_project_creates_on_exact_scope_before_settings_and_deploy(number):
    client = Client()
    client.document["factories"][0]["projects"] = client.document["factories"][0]["projects"][:1]
    job = esaf.apply_project(number, scale_set="002", environment="test", settings={"tag_costcenter": "unit"},
                             display_name=f"Project {number}", session=session(client))
    _, _, added = call(client, "project_add_prepare")
    assert added["placements"] == [{"environment": "test", "scale_set_id": "test-scale"}]
    assert added["display_name"] == f"Project {number}"
    assert call(client, "catalog_settings_prepare")[2]["project_id"] == "new-project"
    deployed = call(client, "catalog_prepare")[1][0]
    assert deployed["project_id"] == "new-project" and deployed["scale_set_id"] == "test-scale"
    assert deployed["expected_revision"] == "revision-1+++" and job.id == "job"


@pytest.mark.parametrize("exists", [False, True])
def test_add_scale_set_matches_environment_not_only_suffix(exists):
    client = Client()
    if not exists:
        client.document["factories"][0]["scale_sets"] = client.document["factories"][0]["scale_sets"][:1]
    esaf.add_scale_set("002", cidr="10.142.0.0/16", environment="test", session=session(client))
    expected = "test-scale" if exists else "new-scale"
    assert call(client, "enroll_scale_set_prepare")[1][0]["scale_set_id"] == expected
    assert call(client, "catalog_prepare")[1][0]["scale_set_id"] == expected
    if not exists:
        assert call(client, "scaleset_add_prepare")[1][2][0]["environment"] == "test"


@pytest.mark.parametrize("method,number,options", [
    ("upsert_project", "001", {}),
    ("apply_project", "001", {"scale_set": "002"}),
    ("delete_project", "001", {}),
    ("delete_project", "999", {"scale_set": "002", "environment": "test"}),
    ("delete_project", "001", {"scale_set": "999", "environment": "test"}),
    ("delete_scale_set", "002", {}),
    ("delete_scale_set", "999", {"environment": "test"}),
    ("apply_project", "003", {}),
    ("apply_project", "003", {"scale_set": "999", "environment": "test"}),
])
def test_ambiguous_or_missing_scope_refuses_before_mutation(method, number, options):
    client = Client()
    with pytest.raises(ConfigError):
        getattr(esaf, method)(number, session=session(client), **options)
    assert [row[0] for row in client.calls] == ["catalog_list"]


@pytest.mark.parametrize("method", ["delete_project", "delete_scale_set"])
@pytest.mark.parametrize("remove_target", [False, True])
def test_deletion_refreshes_after_authorization_without_retargeting(method, remove_target):
    client = Client()
    if remove_target:
        def remove(document):
            document["factories"][0]["scale_sets"].pop()
        client.after_authorization = remove
    options = {"environment": "test"}
    if method == "delete_project":
        options["scale_set"] = "002"
    number = "001" if method == "delete_project" else "002"
    if remove_target:
        with pytest.raises(ConfigError):
            getattr(esaf, method)(number, session=session(client), **options)
        assert not any(row[0] in ("project_delete_prepare", "scaleset_delete_prepare") for row in client.calls)
    else:
        getattr(esaf, method)(number, session=session(client), **options)
        name = "project_delete_prepare" if method == "delete_project" else "scaleset_delete_prepare"
        assert call(client, name)[2]["expected_revision"] == "authorized-revision"


@pytest.mark.parametrize("method", ["upsert_project", "delete_project", "delete_scale_set", "delete_factory"])
@pytest.mark.parametrize("confirmed", [{}, {"job": {"id": None}}, {"job": {"id": " "}}])
def test_async_submission_requires_a_persistable_job_id(method, confirmed):
    client = Client()
    client.confirmed = confirmed
    factory = client.document["factories"][0]
    factory["scale_sets"] = factory["scale_sets"][:1]
    factory["projects"] = factory["projects"][:1]
    args = () if method == "delete_factory" else ("002" if method == "delete_scale_set" else "001",)
    with pytest.raises(FailureError, match="job"):
        getattr(esaf, method)(*args, session=session(client))


@pytest.mark.parametrize("prepare", [False, True])
def test_legacy_workflow_inputs_keep_the_stage_driver(prepare):
    client = Mock()
    client.creation_workflow_prepare.return_value = {"workflow_id": WORKFLOW}
    client.creation_workflow_status.side_effect = [{"status": "awaiting-review"}, {"status": "succeeded"}]
    client.creation_workflow_next.return_value = OK
    kwargs = {"request": {"scope": {"folder": FOLDER}}} if prepare else {"workflow_id": WORKFLOW}
    job = esaf.init_factory(**kwargs, wait=True, poll=0, session=session(client))
    assert job.result == {"status": "succeeded"}
    client.creation_workflow_start.assert_called_once_with(FOLDER, WORKFLOW, CONFIRMATION)


@pytest.mark.parametrize("method", ["apply_project", "delete_project"])
def test_ambiguous_suffix_is_not_inferred_from_an_existing_project(method):
    client = Client()
    client.document["factories"][0]["projects"] = client.document["factories"][0]["projects"][:1]
    with pytest.raises(ConfigError, match="Ambiguous"):
        getattr(esaf, method)("001", scale_set="002", session=session(client))
    assert [row[0] for row in client.calls] == ["catalog_list"]


@pytest.mark.parametrize("method", ["apply_project", "delete_project"])
def test_repeated_project_number_in_one_environment_uses_selected_scale(method):
    client = Client()
    factory = client.document["factories"][0]
    factory["scale_sets"][1].update(environment="dev", suffix="003")
    factory["projects"][1]["placements"][0]["environment"] = "dev"
    getattr(esaf, method)("001", environment="dev", scale_set="003", session=session(client))
    if method == "apply_project":
        body = call(client, "catalog_prepare")[1][0]
        assert body["project_id"] == "test-project" and body["scale_set_id"] == "test-scale"
    else:
        _, args, kwargs = call(client, "project_delete_prepare")
        assert args[2] == "test-project" and kwargs["scale_set_id"] == "test-scale"
        assert kwargs["environments"] == ["dev"]


def test_settings_refresh_cannot_substitute_another_project(monkeypatch):
    client = Client()
    original = client.catalog_confirm

    def replace_project(*args):
        result = original(*args)
        client.document["factories"][0]["projects"][1]["id"] = "replacement"
        return result

    monkeypatch.setattr(client, "catalog_confirm", replace_project)
    with pytest.raises(ConfigError, match="changed"):
        esaf.apply_project("001", environment="test", scale_set="002",
                           settings={"tag_costcenter": "unit"}, session=session(client))
    assert not any(row[0] == "catalog_prepare" for row in client.calls)


@pytest.mark.parametrize("existing", [False, True])
def test_apply_project_enrolls_registered_project_before_deploy_including_resume(existing, monkeypatch):
    client = Client()
    enrolled = set()
    prepare = client.catalog_prepare
    confirm = client.enroll_scale_set_confirm

    def require_enrollment(body):
        if body["project_id"] not in enrolled:
            raise BlockedError("The live enrollment does not cover the new project resource group.")
        return prepare(body)

    def enroll(**kwargs):
        result = confirm(**kwargs)
        enrolled.update(p["id"] for p in client.document["factories"][0]["projects"]
                        if any(pl["scale_set_id"] == "test-scale" for pl in p["placements"]))
        return result

    monkeypatch.setattr(client, "catalog_prepare", require_enrollment)
    monkeypatch.setattr(client, "enroll_scale_set_confirm", enroll)
    number = "001" if existing else "003"
    job = esaf.apply_project(number, environment="test", scale_set="002",
                             settings={"tag_costcenter": "unit"}, session=session(client))
    assert job.id == "job"
    names = [row[0] for row in client.calls]
    assert names.index("catalog_settings_prepare") < names.index("enroll_scale_set_prepare")
    assert names.index("enroll_scale_set_confirm") < names.index("catalog_prepare")
    assert call(client, "enroll_scale_set_prepare")[1][0] == {
        "contract_version": 1, "folder": FOLDER, "factory_id": "factory", "scale_set_id": "test-scale"}
    assert call(client, "catalog_prepare")[1][0]["expected_revision"] == client.document["revision"][:-1]


@pytest.mark.parametrize("method", ["apply_project", "add_scale_set"])
@pytest.mark.parametrize("blockers,skip", [
    ([BLOB_BLOCKER], True),
    ([BLOB_BLOCKER, "Permission denied"], False),
    (["The selected scale set already has a binding target.", "Permission denied"], False),
    (["Permission denied"], False),
])
def test_project_and_scale_enrollment_skip_only_documented_noops(method, blockers, skip, monkeypatch):
    client = Client()

    def review(body):
        client.record("enroll_scale_set_prepare", body)
        return {**OK, "can_execute": False, "blockers": blockers}

    monkeypatch.setattr(client, "enroll_scale_set_prepare", review)
    if method == "apply_project":
        args, kwargs = ("001",), {"scale_set": "002", "environment": "test"}
    else:
        args, kwargs = ("002",), {"cidr": "10.142.0.0/16", "environment": "test"}
    if skip:
        assert getattr(esaf, method)(*args, **kwargs, session=session(client)).id == "job"
    else:
        with pytest.raises(BlockedError, match="Permission denied"):
            getattr(esaf, method)(*args, **kwargs, session=session(client))
        assert not any(row[0] == "catalog_prepare" for row in client.calls)
    assert not any(row[0] == "enroll_scale_set_confirm" for row in client.calls)


@pytest.mark.parametrize("result", [APIError("enrollment dispatch failed"), {"status": "failed", "message": "no grant"}])
def test_project_enrollment_failure_stops_deployment(result, monkeypatch):
    client = Client()

    def fail(**kwargs):
        client.record("enroll_scale_set_confirm", **kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(client, "enroll_scale_set_confirm", fail)
    with pytest.raises(APIError, match="enrollment dispatch failed|no grant"):
        esaf.apply_project("003", environment="test", scale_set="002", session=session(client))
    assert not any(row[0] == "catalog_prepare" for row in client.calls)


@pytest.mark.parametrize("initial,expected", [
    ("config", "requested-project"),
    ({"number": "003"}, "override-project"),
    ({}, "dev-project"),
    (None, None),
])
def test_bootstrap_uses_requested_initial_project_and_explicit_null(initial, expected):
    client = BootstrapClient()
    request = copy.deepcopy(CREATION)
    request["config"]["project_number"] = "002"
    if initial != "config":
        request["initial_project"] = initial
    client.document["factories"][0]["projects"] += [
        {"id": "requested-project", "number": "002",
         "placements": [{"environment": "dev", "scale_set_id": "dev-scale"}]},
        {"id": "override-project", "number": "003",
         "placements": [{"environment": "dev", "scale_set_id": "dev-scale"}]},
        {"id": "other-placement-project", "number": "002",
         "placements": [{"environment": "test", "scale_set_id": "test-scale"}]},
    ]
    job = esaf.init_factory(creation_request=request, session=session(client))
    body = next(row[2] for row in client.calls if row[1].endswith("/workflows/prepare"))
    assert "project_id" in body["scope"] and body["scope"]["project_id"] == expected
    assert body["bootstrap_config"] == request["config"]
    assert job.id == WORKFLOW


def test_bootstrap_missing_requested_initial_project_stops_before_workflow():
    client = BootstrapClient()
    request = copy.deepcopy(CREATION)
    request["config"]["project_number"] = "002"
    with pytest.raises(ConfigError, match="project"):
        esaf.init_factory(creation_request=request, session=session(client))
    assert not any("/workflows/" in row[1] for row in client.calls)


@pytest.mark.parametrize("preview_null,authorization_null", [(True, True), (False, True), (True, False), (False, False)])
def test_bootstrap_nullable_project_scope_is_semantic_without_rehashing(preview_null, authorization_null, monkeypatch):
    client = BootstrapClient()
    original = client.request
    sent_hash = None

    def request(method, path, **kwargs):
        nonlocal sent_hash
        response = original(method, path, **kwargs)
        if path.endswith("/workflows/prepare"):
            response["scope"] = {key: value for key, value in response["scope"].items() if key != "project_id"}
            if preview_null:
                response["scope"]["project_id"] = None
            authorization = response["review"]["workflow_authorization"]
            authorization["scope"] = {key: value for key, value in authorization["scope"].items()
                                      if key != "project_id"}
            if authorization_null:
                authorization["scope"]["project_id"] = None
            authorization["authorization_hash"] = canonical_json_hash(
                {key: value for key, value in authorization.items() if key != "authorization_hash"})
            sent_hash = authorization["authorization_hash"]
        return response

    monkeypatch.setattr(client, "request", request)
    body = {**copy.deepcopy(CREATION), "initial_project": None}
    job = esaf.init_factory(creation_request=body, session=session(client))
    prepare = next(row[2] for row in client.calls if row[1].endswith("/workflows/prepare"))
    start = next(row[2] for row in client.calls if row[1].endswith("/workflows/start"))
    assert prepare["scope"]["project_id"] is None
    assert start["authorization_hash"] == sent_hash and job.id == WORKFLOW


@pytest.mark.parametrize("method,prepare", [
    ("delete_project", "project_delete_prepare"),
    ("delete_scale_set", "scaleset_delete_prepare"),
    ("delete_factory", "delete_aifactory_prepare"),
])
@pytest.mark.parametrize("preauthorized", [True, False])
def test_blob_deletion_skips_only_grant_and_keeps_protected_review(method, prepare, preauthorized, monkeypatch):
    client = Client()

    def authorization(body):
        client.record("authorize_deletion_prepare", body)
        return {**OK, "can_execute": False, "blockers": [BLOB_BLOCKER]}

    def protected(*args, **kwargs):
        client.record(prepare, *args, **kwargs)
        review = {**OK, "can_execute": preauthorized,
                  "blockers": [] if preauthorized else ["The enrolled scope does not allow deletion."]}
        if method == "delete_project" and preauthorized:
            review["runtime_scope_authorization"] = client.runtime_proof(
                args[1], kwargs["scale_set_id"], args[2])
        return review

    monkeypatch.setattr(client, "authorize_deletion_prepare", authorization)
    monkeypatch.setattr(client, prepare, protected)
    args = () if method == "delete_factory" else ("001" if method == "delete_project" else "002",)
    kwargs = {} if method == "delete_factory" else {"environment": "test"}
    if method == "delete_project":
        kwargs["scale_set"] = "002"
    if preauthorized:
        assert getattr(esaf, method)(*args, **kwargs, session=session(client)).id == "job"
    else:
        with pytest.raises(BlockedError, match="does not allow deletion"):
            getattr(esaf, method)(*args, **kwargs, session=session(client))
        assert not any(row[0] in ("catalog_confirm", "delete_aifactory_confirm") for row in client.calls)
    assert any(row[0] == prepare for row in client.calls)
    assert not any(row[0] == "authorize_deletion_confirm" for row in client.calls)


@pytest.mark.parametrize("outcome", [
    {"can_execute": False, "blockers": [BLOB_BLOCKER, "Permission denied"]},
    {"can_execute": False, "blockers": [BLOB_BLOCKER, "Nothing to change: deletion is already allowed"]},
    {"can_execute": False, "blockers": [BLOB_BLOCKER + " Extra failure."]},
    {"can_execute": True, "blockers": [BLOB_BLOCKER]},
    APIError(BLOB_BLOCKER, status=500),
])
def test_blob_authorization_exception_is_exact_not_a_general_bypass(outcome, monkeypatch):
    client = Client()

    def authorization(body):
        client.record("authorize_deletion_prepare", body)
        if isinstance(outcome, Exception):
            raise outcome
        return {**OK, **outcome}

    monkeypatch.setattr(client, "authorize_deletion_prepare", authorization)
    with pytest.raises(APIError):
        esaf.delete_scale_set("002", environment="test", session=session(client))
    assert not any(row[0] in ("authorize_deletion_confirm", "scaleset_delete_prepare") for row in client.calls)


@pytest.mark.parametrize("covered", [True, False])
def test_current_enrollment_noop_still_requires_exact_runtime_coverage(covered, monkeypatch):
    client = Client()
    noop = "The scale set already has a binding target; it is enrolled. Nothing was changed."

    def enrollment(body):
        client.record("enroll_scale_set_prepare", body)
        return {**OK, "can_execute": False, "blockers": [noop]}

    def protected(body):
        client.record("catalog_prepare", body)
        review = {**OK, "can_execute": covered,
                  "blockers": [] if covered else ["Live enrollment does not cover this project."]}
        if covered:
            review["runtime_scope_authorization"] = client.runtime_proof(
                body["factory_id"], body["scale_set_id"], body["project_id"])
        return review

    monkeypatch.setattr(client, "enroll_scale_set_prepare", enrollment)
    monkeypatch.setattr(client, "catalog_prepare", protected)
    number = "001" if covered else "003"
    if covered:
        assert esaf.apply_project(number, scale_set="002", environment="test", session=session(client)).id == "job"
    else:
        with pytest.raises(BlockedError, match="Live enrollment does not cover"):
            esaf.apply_project(number, scale_set="002", environment="test", session=session(client))
    assert any(row[0] == "catalog_prepare" for row in client.calls)
    assert not any(row[0] == "enroll_scale_set_confirm" for row in client.calls)


def test_current_enrollment_noop_with_another_blocker_is_refused(monkeypatch):
    client = Client()
    monkeypatch.setattr(client, "enroll_scale_set_prepare", lambda body: {
        **OK, "can_execute": False,
        "blockers": ["The scale set already has a binding target; it is enrolled. Nothing was changed.",
                     "Permission denied"]})
    with pytest.raises(BlockedError, match="Permission denied"):
        esaf.add_scale_set("002", cidr="10.142.0.0/16", environment="test", session=session(client))
    assert not any(row[0] in ("catalog_prepare", "enroll_scale_set_confirm") for row in client.calls)


@pytest.mark.parametrize("change", ["hash", "factory", "scale", "project", "extra-scope"])
def test_nullable_workflow_scope_does_not_weaken_authorization(change, monkeypatch):
    client = BootstrapClient()
    original = client.request

    def request(method, path, **kwargs):
        response = original(method, path, **kwargs)
        if path.endswith("/workflows/prepare"):
            authorization = response["review"]["workflow_authorization"]
            authorization["scope"] = dict(authorization["scope"])
            authorization["scope"].pop("project_id", None)
            if change == "hash":
                authorization["authorization_hash"] = "0" * 64
            else:
                field = {"factory": "factory_id", "scale": "scale_set_id", "project": "project_id",
                         "extra-scope": "unrequested"}[change]
                authorization["scope"][field] = "different"
                authorization["authorization_hash"] = canonical_json_hash(
                    {key: value for key, value in authorization.items() if key != "authorization_hash"})
        return response

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(ConfigError):
        esaf.init_factory(creation_request={**copy.deepcopy(CREATION), "initial_project": None},
                          session=session(client))
    assert not any(row[1].endswith("/workflows/start") for row in client.calls)


@pytest.mark.parametrize("method", ["apply_project", "delete_project"])
@pytest.mark.parametrize("coordination", ["single-writer", "blob"])
@pytest.mark.parametrize("change", [
    "missing", "not-object", "factory", "scale", "project", "null-project", "not-enrolled", "truthy-enrolled",
    "missing-delete-permission", "truthy-delete-permission", "missing-rg", "relative-rg", "wrong-subscription",
    "resource-not-group", "uppercase-rg", "invalid-subscription", "trailing-slash",
])
def test_project_runtime_requires_matching_live_scope_proof_before_confirm(method, coordination, change, monkeypatch):
    client = Client()
    if coordination == "blob":
        monkeypatch.setattr(client, "authorize_deletion_prepare", lambda body: {
            **OK, "can_execute": False, "blockers": [BLOB_BLOCKER]})
        monkeypatch.setattr(client, "enroll_scale_set_prepare", lambda body: {
            **OK, "can_execute": False, "blockers": [BLOB_BLOCKER]})
    prepare = "catalog_prepare" if method == "apply_project" else "project_delete_prepare"
    original = getattr(client, prepare)

    def unsafe(*args, **kwargs):
        review = original(*args, **kwargs)
        proof = review["runtime_scope_authorization"]
        if change == "missing":
            del review["runtime_scope_authorization"]
        elif change == "not-object":
            review["runtime_scope_authorization"] = True
        elif change in ("factory", "scale", "project"):
            proof[{"factory": "factory_id", "scale": "scale_set_id", "project": "project_id"}[change]] = "other"
        elif change == "null-project":
            proof["project_id"] = None
        elif change == "not-enrolled":
            proof["enrolled"] = False
        elif change == "truthy-enrolled":
            proof["enrolled"] = 1
        elif change == "missing-delete-permission":
            del proof["delete_authorized"]
        elif change == "truthy-delete-permission":
            proof["delete_authorized"] = "true"
        elif change == "missing-rg":
            del proof["resource_group_id"]
        elif change == "relative-rg":
            proof["resource_group_id"] = "unit-esml-project001-sdc-test-002-rg"
        elif change == "wrong-subscription":
            proof["resource_group_id"] = proof["resource_group_id"].replace(TEST_SUB, DEV_SUB)
        elif change == "resource-not-group":
            proof["resource_group_id"] += "/providers/microsoft.storage/storageaccounts/example"
        elif change == "uppercase-rg":
            proof["resource_group_id"] = proof["resource_group_id"].upper()
        elif change == "invalid-subscription":
            proof["resource_group_id"] = proof["resource_group_id"].replace(TEST_SUB, "not-a-subscription")
        else:
            proof["resource_group_id"] += "/"
        return review

    monkeypatch.setattr(client, prepare, unsafe)
    with pytest.raises((BlockedError, ConfigError)):
        getattr(esaf, method)("001", scale_set="002", environment="test", session=session(client))
    assert [row[0] for row in client.calls].count(prepare) == 1
    assert not any(row[0] == "catalog_confirm" for row in client.calls)


@pytest.mark.parametrize("method", ["apply_project", "delete_project"])
@pytest.mark.parametrize("coordination", ["single-writer", "blob"])
@pytest.mark.parametrize("delete_authorized", [True, False])
def test_project_runtime_proof_requires_delete_permission_only_for_delete(
        method, coordination, delete_authorized, monkeypatch):
    client = Client()
    if coordination == "blob":
        monkeypatch.setattr(client, "authorize_deletion_prepare", lambda body: {
            **OK, "can_execute": False, "blockers": [BLOB_BLOCKER]})
        monkeypatch.setattr(client, "enroll_scale_set_prepare", lambda body: {
            **OK, "can_execute": False, "blockers": [BLOB_BLOCKER]})
    prepare = "catalog_prepare" if method == "apply_project" else "project_delete_prepare"
    original = getattr(client, prepare)

    def reviewed(*args, **kwargs):
        review = original(*args, **kwargs)
        review["runtime_scope_authorization"]["delete_authorized"] = delete_authorized
        return review

    monkeypatch.setattr(client, prepare, reviewed)
    if method == "delete_project" and not delete_authorized:
        with pytest.raises(BlockedError, match="deletion|delete"):
            esaf.delete_project("001", scale_set="002", environment="test", session=session(client))
        assert not any(row[0] == "catalog_confirm" for row in client.calls)
    else:
        assert getattr(esaf, method)("001", scale_set="002", environment="test", session=session(client)).id == "job"


def test_project_enrollment_noop_on_guardless_server_cannot_confirm(monkeypatch):
    client = Client()
    monkeypatch.setattr(client, "enroll_scale_set_prepare", lambda body: {
        **OK, "can_execute": False,
        "blockers": ["The scale set already has a binding target; it is enrolled. Nothing was changed."]})

    def guardless(body):
        return client.record("catalog_prepare", body)

    monkeypatch.setattr(client, "catalog_prepare", guardless)
    with pytest.raises(BlockedError, match="authorization|scope"):
        esaf.apply_project("001", scale_set="002", environment="test", session=session(client))
    assert not any(row[0] == "catalog_confirm" for row in client.calls)


@pytest.mark.parametrize("method", ["add_scale_set", "delete_scale_set", "delete_factory"])
def test_nonproject_runtime_operations_do_not_require_project_scope_proof(method):
    client = Client()
    kwargs = {} if method == "delete_factory" else {"environment": "test"}
    if method == "add_scale_set":
        kwargs["cidr"] = "10.142.0.0/16"
    args = () if method == "delete_factory" else ("002",)
    assert getattr(esaf, method)(*args, **kwargs, session=session(client)).id == "job"
