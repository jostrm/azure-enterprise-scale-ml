"""Offline provider transports; real Git CAS tests use only a new local bare repo."""

import base64
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import yaml

def load_test_module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


te = load_test_module("test_factory_enrollment")
tl = load_test_module("test_factory_lifecycle")


en, fl, ROOT = te.en, tl.fl, te.ROOT
ps = en._single_writer_module()
REAL_RUN = subprocess.run


@pytest.fixture
def workspace():
    path = ROOT / ".validation-work" / ("current7f0382-single-writer-" + str(uuid4()))
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        for item in path.rglob("*"):
            if item.is_file():
                item.chmod(0o600)
        shutil.rmtree(path)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("No live commands, auth, cloud or provider writes")
    monkeypatch.setattr(en.subprocess, "run", fail)
    monkeypatch.setattr(en, "build_opener", fail)
    monkeypatch.setattr(fl, "build_opener", fail)


class Provider:
    def __init__(self, repository):
        self.repository, self.head = repository, None
        self.objects, self.parents, self.calls = {}, {}, []
        self.public, self.deny, self.uncertain, self.contender = False, False, False, None

    def add(self, body):
        key = hashlib.sha1(ps.canonical(body)).hexdigest()
        self.objects[key] = copy.deepcopy(body)
        return key

    def state(self):
        commit = self.objects[self.head]
        tree = self.objects[commit["tree"]["sha"]]
        return json.loads(base64.b64decode(self.objects[tree["tree"][0]["sha"]]["content"]))

    def set_state(self, value):
        blob = self.add({"encoding": "base64", "content": base64.b64encode(ps.canonical(value)).decode()})
        tree = self.add({"tree": [{"path": "state.json", "type": "blob", "sha": blob}]})
        head = self.add({"tree": {"sha": tree}, "parents": [self.head] if self.head else []})
        self.parents[head] = self.head
        self.head = head
        return head

    def call(self, kind, method, endpoint, body, allowed):
        self.calls.append((method, endpoint, copy.deepcopy(body)))
        if self.dy(method):
            raise en.EnrollmentError("provider-denied")
        if kind == "ado":
            return self.ado(method, endpoint, body, allowed)
        path = endpoint.removeprefix("repos/" + urlsplit(self.repository).path.strip("/"))
        if not path:
            return 200, {}, {"private": not self.public, "full_name": urlsplit(self.repository).path.strip("/")}
        if path.startswith("/git/ref/"):
            return (200, {}, {"ref": ps.STATE_REF, "object": {"type": "commit", "sha": self.head}}) if self.head else (404, {}, {})
        for kind_name in ("blobs", "trees", "commits"):
            if path.startswith("/git/" + kind_name + "/"):
                return 200, {}, copy.deepcopy(self.objects[path.rsplit("/", 1)[1]])
        if path == "/git/blobs":
            return 201, {}, {"sha": self.add(body)}
        if path == "/git/trees":
            return 201, {}, {"sha": self.add(body)}
        if path == "/git/commits":
            stored = {**body, "tree": {"sha": body["tree"]}}
            key = self.add(stored)
            self.parents[key] = body["parents"][0] if body["parents"] else None
            return 201, {}, {"sha": key}
        if path == "/git/refs" or path.startswith("/git/refs/"):
            if self.contender:
                callback, self.contender = self.contender, None
                callback()
            if method == "POST":
                en.require(self.head is None, "provider-create-conflict")
            else:
                assert method == "PATCH" and body["force"] is False
                en.require(self.parents[body["sha"]] == self.head, "provider-non-fast-forward")
            self.head = body["sha"]
            if self.uncertain:
                raise en.EnrollmentError("provider-write-uncertain")
            return 201 if method == "POST" else 200, {}, {}
        raise AssertionError((method, endpoint, body))

    def dy(self, method):
        return self.deny and method not in ("GET", "HEAD")

    def ado(self, method, endpoint, body, allowed):
        parsed = urlsplit(endpoint)
        query = parse_qs(parsed.query)
        if "/refs" in parsed.path:
            return 200, {}, {"value": [{"name": ps.STATE_REF, "objectId": self.head}] if self.head else []}
        if "/items" in parsed.path:
            assert query["versionDescriptor.version"] == [self.head]
            return 200, {}, {"content": ps.canonical(self.state()).decode()}
        if "/pushes" in parsed.path:
            if self.contender:
                callback, self.contender = self.contender, None
                callback()
            en.require(body["refUpdates"][0]["oldObjectId"] == (self.head or "0" * 40), "provider-cas-conflict")
            self.set_state(json.loads(body["commits"][0]["changes"][0]["newContent"]["content"]))
            if self.uncertain:
                raise en.EnrollmentError("provider-write-uncertain")
            return 201, {}, {"refUpdates": [{"name": ps.STATE_REF, "newObjectId": self.head}]}
        return 200, {}, {"name": "repo", "remoteUrl": self.repository,
                         "project": {"visibility": "public" if self.public else "private", "id": te.PROJECT}}


def registered_request(path, kind="gha", **overrides):
    (path / "azurefactory").mkdir(exist_ok=True)
    te.save(path, {"schema_version": 2, "factories": [
        {"id": te.FACTORY, "kind": "ai", "prefix": "acme-ai", "region": "swedencentral", "scale_sets": [
            {"id": te.SCALE, "environment": "stage", "suffix": "001", "tenant_id": te.TENANT,
             "subscription_id": te.SUB, "orchestrator": kind}]}], "bindings": {}})
    options = te.options(kind)
    options.pop("public_network_access")
    return en.load_request(path, te.FACTORY, te.SCALE, "stage",
                           options | {"coordination_mode": "single-writer"} | overrides)


class EnrollmentTransport(te.Fake):
    def __init__(self, request, provider):
        stub = request | {"account_id": te.GROUP + "/providers/microsoft.storage/storageaccounts/unused"}
        self.provider = provider
        super().__init__(stub, provisioned=False)
        self.request = request
        self.cloud = en.Cloud(request, command_runner=self.run, opener=self)

    def run(self, argv, **kwargs):
        if argv[:2] == ["gh", "api"]:
            method = argv[argv.index("--method") + 1]
            endpoint = argv[argv.index("--method") + 2]
            if endpoint == "repos/org/repo" or "/git/" in endpoint:
                body = json.loads(kwargs["input"]) if kwargs.get("input") else None
                status, _, value = self.provider.call("gha", method, endpoint, body, (200, 201, 404))
                self.commands.append((copy.deepcopy(argv), kwargs.get("input")))
                return SimpleNamespace(returncode=1 if status >= 400 else 0,
                                       stdout=f"HTTP/2 {status}\n\n{json.dumps(value)}".encode(), stderr=b"")
        assert not ("--resource" in argv and argv[argv.index("--resource") + 1] == en.STORAGE)
        assert argv[1:4] != ["storage", "account", "check-name"]
        return super().run(argv, **kwargs)

    def open(self, req, timeout):
        assert ".blob.core.windows.net" not in req.full_url
        assert "microsoft.storage" not in req.full_url.lower()
        assert en.DATA_ROLE not in req.full_url
        if "/_apis/git/repositories/" in req.full_url:
            status, headers, body = self.provider.call("ado", req.get_method(), req.full_url,
                                                      json.loads(req.data) if req.data else None, (200, 201, 404))
            return te.Response(status, body, headers)
        return super().open(req, timeout)


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_actual_enrollment_request_plan_ensure_without_storage(workspace, kind):
    req = registered_request(workspace, kind)
    assert "account_id" not in req and "public_network_access" not in req
    provider = Provider(req["route"]["repository"])
    transport = EnrollmentTransport(req, provider)
    review = en.plan(req, cloud=transport.cloud, acknowledge_exclusive_writer_governance=True)
    assert review["can_ensure"], review
    assert ps.WARNING in review["warnings"] and ps.HUB_WARNING in review["warnings"]
    assert any("requires a private repository" in warning for warning in review["warnings"])
    assert all(method == "GET" for method, _, _ in provider.calls)
    result = en.ensure(req, review["plan_hash"], yes=True, cloud=transport.cloud,
                       acknowledge_exclusive_writer_governance=True)
    assert result["enrollment_complete"], result
    binding = result["binding_candidate"]
    assert binding["locks"] == ps.coordinates(req["route"]["repository"]) | {
        "coordination_hash": en.digest(provider.state()["enrollment"]), "revision": 1}
    assert provider.state()["active"] is None
    assert provider.state()["enrollment"]["protocol"] == "aifactory-single-writer-v1"
    assert len([row for row in transport.writes if "/roleassignments/" in row[2]]) == 1
    assert not any("storage" in row[2].lower() for row in transport.writes)
    assert result["runtime_ready"] is False
    before = copy.deepcopy(provider.calls)
    again = te.enroll(req, transport)
    assert again["status"] == "unchanged"
    assert all(method == "GET" for method, _, _ in provider.calls[len(before):])
    doc = te.document(workspace)
    doc["bindings"] = {te.FACTORY: {kind: binding}}
    te.save(workspace, doc)
    loaded = en.load_request(workspace, te.FACTORY, te.SCALE, "stage", req["options"])
    assert loaded["coordinates"] == req["coordinates"]
    provider.head = None
    with pytest.raises(en.EnrollmentError, match="enrollment-state-missing"):
        en.plan(loaded, cloud=EnrollmentTransport(loaded, provider).cloud)


@pytest.mark.parametrize("failure", ["public", "denied", "uncertain", "active", "cas"])
def test_enrollment_fails_closed_before_azure_provisioning(workspace, failure):
    req = registered_request(workspace)
    provider = Provider(req["route"]["repository"])
    transport = EnrollmentTransport(req, provider)
    if failure in ("public", "active"):
        provider.public = failure == "public"
        if failure == "active":
            provider.set_state({"schema": 1, "repository": provider.repository, "enrollment": None,
                                "active": {"kind": "enrollment", "id": "existing"}, "records": {}})
        with pytest.raises(en.EnrollmentError):
            en.plan(req, cloud=transport.cloud, acknowledge_exclusive_writer_governance=True)
    else:
        review = en.plan(req, cloud=transport.cloud, acknowledge_exclusive_writer_governance=True)
        provider.deny = failure == "denied"
        provider.uncertain = failure == "uncertain"
        if failure == "cas":
            provider.contender = lambda: provider.set_state(ps.ProviderState(transport.cloud, req["route"], en.EnrollmentError).empty())
        result = en.ensure(req, review["plan_hash"], yes=True, cloud=transport.cloud,
                           acknowledge_exclusive_writer_governance=True)
        assert not result["enrollment_complete"] and result["reconciliation_required"]
        assert result["binding_candidate"] is None
        if failure == "uncertain":
            assert provider.state()["active"]["kind"] == "enrollment"
            provider.uncertain = False
            with pytest.raises(en.EnrollmentError, match="active-claim"):
                en.plan(req, cloud=transport.cloud)
    assert not transport.writes


@pytest.mark.parametrize("key,value", [
    ("coordination_mode", "auto"), ("public_network_access", "Disabled"),
    ("coordination_storage_mode", "dedicated"), ("coordination_account_id", "unused"),
])
def test_mode_is_explicit_and_storage_inputs_are_not_ignored(workspace, key, value):
    with pytest.raises(en.EnrollmentError):
        registered_request(workspace, **{key: value})


def lifecycle_setup(kind="gha", projects=(), operation="create-scaleset"):
    document, templates = tl.scoped_manifest(projects, route=kind, operation=operation)
    enrolled = tl.scoped_enrollment(document)
    enrolled.update(protocol="aifactory-single-writer-v1", enforcement="repository-exclusive-writer")
    document["locks"] = ps.coordinates(document["route"]["repository"]) | {
        "coordination_hash": fl.digest(enrolled), "revision": enrolled["revision"],
        "scopes": [tl.GROUP], "common_dependencies": [tl.COMMON]}
    tl.seal(document)
    provider = Provider(document["route"]["repository"])
    provider.set_state({"schema": 1, "repository": provider.repository, "enrollment": enrolled, "active": None, "records": {}})
    cloud = tl.PlanCloud(document, templates)
    cloud.state_request = provider.call
    original_request = cloud.request

    def request(method, url, audience, *args, **kwargs):
        assert audience not in (en.STORAGE, en.STORAGE.rstrip("/"))
        assert ".blob.core.windows.net" not in url
        return original_request(method, url, audience, *args, **kwargs)
    cloud.request = request
    return document, provider, cloud


@pytest.mark.parametrize("kind", ["gha", "ado"])
@pytest.mark.parametrize("projects,operation", [((), "create-scaleset"), (("017",), "deploy-project")])
def test_native_prepare_claim_worker_receipts_persist_across_coordinators(monkeypatch, kind, projects, operation):
    document, provider, cloud = lifecycle_setup(kind, projects, operation)
    monkeypatch.setattr(fl, "verify_source", lambda cloud, root, source: root)
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", tl.simple_plan_closure)
    prepared = fl.freeze_deployment_plan(cloud, document, ROOT)
    document["deployment"] = prepared
    tl.seal(document)
    assert all(method == "GET" for method, _, _ in provider.calls)
    locks = fl.coordination(cloud, document)
    assert isinstance(locks, fl.RepositoryCoordination)
    locks.acquire()
    locks.claim_run()
    proof = locks.read_claim()
    envelope = json.loads(fl.protected_worker_envelope(document, locks))
    worker = fl.run_deployment_worker(envelope, ROOT, document["run_id"], document["manifest_hash"], cloud=cloud)
    assert worker["status"] == "succeeded", worker
    assert len(cloud.arm_writes) == 1
    assert not cloud.leases and not cloud.runs
    fresh_reader = fl.coordination(cloud, document)
    assert fl.verify_worker_receipt(fresh_reader, document) == worker
    assert fresh_reader.read_claim() == proof
    assert "synthetic-not-a-credential" not in json.dumps(provider.state())
    with pytest.raises(fl.Blocked, match="active-claim"):
        fresh_reader.acquire()
    locks.store_receipt({"schema": 1, "run_id": document["run_id"], "manifest_hash": document["manifest_hash"],
                         "status": "succeeded"})
    locks.release()
    assert provider.state()["active"] is None
    with pytest.raises(fl.Blocked, match="already-submitted"):
        fresh_reader.acquire()


@pytest.mark.parametrize("defect", ["missing", "changed", "claim", "expired", "duplicate", "ownership", "what-if"])
def test_worker_errors_preserve_claim_and_block_before_arm_write(monkeypatch, defect):
    document, provider, cloud = lifecycle_setup()
    locks = fl.coordination(cloud, document)
    locks.acquire()
    locks.claim_run()
    monkeypatch.setattr(fl, "_verify_source", lambda cloud, root, source, **kwargs: root)
    monkeypatch.setattr(fl, "collect_resource_closure", tl.simple_plan_closure)
    state = provider.state()
    if defect == "missing":
        provider.head = None
    if defect == "changed":
        state["enrollment"]["revision"] += 1
        provider.set_state(state)
    if defect == "claim":
        state["active"] = None
        provider.set_state(state)
    if defect == "expired":
        proof = state["records"]["runs/" + document["run_id"] + ".claim.json"]
        proof["accepted_at"] = "2000-01-01T00:00:00+00:00"
        state["records"]["runs/" + document["run_id"] + ".json"]["execution_claim"] = proof
        provider.set_state(state)
    if defect == "duplicate":
        state["records"]["runs/" + document["run_id"] + ".worker.json"] = {
            "run_id": document["run_id"], "manifest_hash": document["manifest_hash"], "status": "running"}
        provider.set_state(state)
    if defect == "ownership":
        cloud.bodies[tl.GROUP.lower()]["tags"]["aifactory.factory_id"] = "someone-else"
    if defect == "what-if":
        cloud.what_if_changed = True
    if defect in ("ownership", "what-if"):
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(document, locks)), ROOT,
                                          document["run_id"], document["manifest_hash"], cloud=cloud)
        assert result["status"] == "reconciliation-required"
        with pytest.raises(fl.Blocked, match="retained"):
            locks.release()
        assert provider.state()["active"]
    else:
        with pytest.raises(fl.Blocked):
            fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(document, locks)), ROOT,
                                     document["run_id"], document["manifest_hash"], cloud=cloud)
    assert not cloud.arm_writes


def test_non_blob_mode_is_reviewed_and_unsupported_operations_block(monkeypatch):
    document, provider, cloud = lifecycle_setup()
    monkeypatch.setenv("AIFACTORY_COORDINATION_MODE", "blob")
    assert fl.single_writer(document)
    document["locks"]["inherited_leases"] = {}
    with pytest.raises(fl.Blocked, match="coordinates"):
        fl.validate_manifest(tl.seal(document))
    document["locks"].pop("inherited_leases")
    document["operation"] = "delete"
    with pytest.raises(fl.Blocked, match="scoped-deployment"):
        fl.validate_manifest(tl.seal(document))
    with pytest.raises(fl.Blocked, match="cohort-not-supported"):
        fl.execute_cohort([document], "unread", "unread", "unread")
    assert not provider.calls and not cloud.arm_writes


def test_distinct_templates_scope_provider_credentials_and_keep_blob_permissions():
    directory = ROOT / "bootstrap" / "templates"
    gha = yaml.safe_load((directory / "factory-lifecycle-single-writer-gha.yml").read_text())
    blob = yaml.safe_load((directory / "factory-lifecycle-gha.yml").read_text())
    assert gha["permissions"]["contents"] == "write"
    assert blob["permissions"]["contents"] == "read"
    steps = gha["jobs"]["scoped-deployment"]["steps"]
    worker = next(step for step in steps if step.get("name") == "Execute only the protected reviewed plan")
    assert worker["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert sum("GH_TOKEN" in step.get("env", {}) for step in steps) == 1
    assert next(step for step in steps if step.get("uses") == "actions/checkout@v4")["with"]["persist-credentials"] is False
    ado = yaml.safe_load((directory / "factory-lifecycle-single-writer-ado.yml").read_text())
    assert ado["steps"][0]["persistCredentials"] is False
    assert ado["steps"][-1]["env"]["AIFACTORY_STATE_TOKEN"] == "$(System.AccessToken)"


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_real_worker_provider_transport_uses_only_scoped_provider_token(monkeypatch, kind):
    document, provider, cloud = lifecycle_setup(kind)
    sent = []

    class Opener:
        def open(self, request, timeout):
            headers = dict((key.lower(), value) for key, value in request.header_items())
            sent.append((request.full_url, headers))
            assert headers["authorization"] == "Bearer private-offline-test-token"
            endpoint = request.full_url.removeprefix("https://api.github.com/") if kind == "gha" else request.full_url
            status, incoming, body = provider.call(kind, request.get_method(), endpoint,
                                                   json.loads(request.data) if request.data else None, (200, 201, 404))
            response = te.Response(status, body, incoming)
            response.code = status
            return response

    monkeypatch.setenv("GH_TOKEN" if kind == "gha" else "AIFACTORY_STATE_TOKEN", "private-offline-test-token")
    actual = fl.Cloud(document, command_runner=lambda *a, **k: pytest.fail("No Azure/Git CLI token acquisition"),
                      opener=Opener(), expected_object_id=document["identity"]["deployment_object_id"])
    cloud.state_request = actual.state_request
    locks = fl.coordination(cloud, document)
    locks.acquire()
    locks.claim_run()
    assert locks.read_claim()["manifest_hash"] == document["manifest_hash"]
    assert not actual.tokens
    assert all(".blob.core.windows.net" not in url and "storage.azure.com" not in url for url, _ in sent)
    assert "private-offline-test-token" not in json.dumps(provider.state())
    with pytest.raises(fl.Blocked, match="storage-access-forbidden"):
        actual.token(en.STORAGE)


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_provider_cas_losing_write_is_not_retried_or_overwritten(kind):
    document, provider, cloud = lifecycle_setup(kind)
    store = ps.ProviderState(cloud, document["route"], fl.Blocked)
    old, value = store.read()
    winner = copy.deepcopy(value)
    winner["active"] = {"kind": "run", "run_id": "winner"}
    provider.contender = lambda: provider.set_state(winner)
    candidate = copy.deepcopy(value)
    candidate["active"] = {"kind": "run", "run_id": "loser"}
    with pytest.raises(en.EnrollmentError, match="conflict|fast-forward"):
        store.replace(old, candidate)
    assert provider.state() == winner
    writes = [(method, path) for method, path, _ in provider.calls if method != "GET"]
    assert sum("/pushes" in path or "/git/refs" in path for _, path in writes) == 1
    before = len(provider.calls)
    with pytest.raises(fl.Blocked, match="write-reconciliation-required"):
        store.replace(provider.head, candidate)
    assert len(provider.calls) == before


def test_second_writer_and_changed_registered_ownership_block_enrollment(workspace):
    req = registered_request(workspace)
    provider = Provider(req["route"]["repository"])
    transport = EnrollmentTransport(req, provider)
    assert te.enroll(req, transport)["enrollment_complete"]
    changed = en.load_request(workspace, te.FACTORY, te.SCALE, "stage",
                              req["options"] | {"writer_id": "different", "auth_namespace": "different"})
    new = EnrollmentTransport(changed, provider)
    review = en.plan(changed, cloud=new.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"]
    assert "single-writer-repository-writer-conflict" in review["blockers"]
    assert not new.writes
    transport.resources[te.GROUP]["tags"]["aifactory.factory_id"] = "other"
    review = en.plan(req, cloud=transport.cloud, acknowledge_exclusive_writer_governance=True)
    assert any("ownership-not-proven" in item for item in review["blockers"])


@pytest.mark.parametrize("module_name", ["factory_enrollment_source_fallback", "azurefactory._vendor.factory_enrollment"])
def test_enrollment_helper_loads_only_from_its_vendor_or_source_sibling(workspace, module_name):
    directory = workspace / "isolated-vendor"
    directory.mkdir()
    for name in ("factory_enrollment.py", "provider_repository_state.py"):
        shutil.copyfile(ROOT / "bootstrap" / "lib" / name, directory / name)
    spec = importlib.util.spec_from_file_location(module_name, directory / "factory_enrollment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    helper = module._single_writer_module()
    assert Path(helper.__file__).resolve() == (directory / "provider_repository_state.py").resolve()
    assert helper.coordinates("https://github.com/org/repo") == ps.coordinates("https://github.com/org/repo")
    (directory / "provider_repository_state.py").unlink()
    with pytest.raises(FileNotFoundError):
        module._single_writer_module()


def test_real_local_git_ref_cas_rejects_sibling_contention_and_preserves_receipt(workspace):
    repo = workspace / "state.git"
    env = os.environ | {"GIT_AUTHOR_NAME": "Offline test", "GIT_AUTHOR_EMAIL": "offline@example.invalid",
                        "GIT_COMMITTER_NAME": "Offline test", "GIT_COMMITTER_EMAIL": "offline@example.invalid"}

    def git(*args, data=None, success=True):
        result = REAL_RUN(["git", "--git-dir", str(repo), *args], input=data, text=True, capture_output=True,
                          check=False, env=env, timeout=30, shell=False)
        if success:
            assert result.returncode == 0, result.stderr
        return result

    result = REAL_RUN(["git", "init", "--bare", str(repo)], text=True, capture_output=True, shell=False, timeout=30)
    assert result.returncode == 0

    def commit(value, parent=None):
        blob = git("hash-object", "-w", "--stdin", data=json.dumps(value)).stdout.strip()
        tree = git("mktree", "-z", data=f"100644 blob {blob}\tstate.json\0").stdout.strip()
        return git("commit-tree", tree, *("-p", parent) if parent else (), data="State\n").stdout.strip()

    first = commit({"active": None, "receipts": []})
    git("update-ref", ps.STATE_REF, first, "0" * 40)
    winner = commit({"active": "run-A", "receipts": ["reviewed"]}, first)
    loser = commit({"active": "run-B", "receipts": []}, first)
    git("update-ref", ps.STATE_REF, winner, first)
    assert git("merge-base", "--is-ancestor", winner, loser, success=False).returncode == 1
    assert git("update-ref", ps.STATE_REF, loser, first, success=False).returncode != 0
    assert git("rev-parse", ps.STATE_REF).stdout.strip() == winner
    assert json.loads(git("show", ps.STATE_REF + ":state.json").stdout)["receipts"] == ["reviewed"]
