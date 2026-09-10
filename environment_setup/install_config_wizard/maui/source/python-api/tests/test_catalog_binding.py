import copy
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src import catalog_protocol as protocol, factory_catalog as catalog
from src.catalog_storage import CatalogError
from src.factory_catalog_models import RuntimeBinding
from tests.test_factory_catalog import root, service, migrate, SUB, TENANT
from tests.test_factory_catalog_setup import binding_for


class Cli:
    def __init__(self, enrollment, actor=12345):
        self.enrollment, self.actor = enrollment, actor
        self.calls = []

    def read(self, tool, arguments, **kwargs):
        self.calls.append((tool, arguments))
        if tool == "git":
            return "c" * 40 + "\trefs/heads/main\n"
        if tool == "gh":
            assert arguments == ["api", "user", "--hostname", "github.com", "--method", "GET"]
            return {"id": self.actor}
        if tool == "az":
            return copy.deepcopy(self.enrollment)
        pytest.fail("Unexpected CLI tool")


def write_binding(root, service, kind, runner):
    migrate(root, service)
    document = catalog.load_document(root)
    factory = document["factories"][0]
    scale = factory["scale_sets"][0]
    scale["orchestrator"] = kind
    catalog.commit_document(root, document)
    binding = binding_for(factory)
    binding["repository"] = ("https://github.com/org/catalog" if kind == "gha" else
                             "https://dev.azure.com/org/project/_git/repository")
    binding["runner"] = runner
    target = {"factory_id": factory["id"], "scaleset_id": scale["id"], "prefix": factory["prefix"],
              "region": factory["region"], "environment": scale["environment"], "suffix": scale["suffix"],
              "tenant_id": TENANT, "subscription_id": SUB}
    writer = {"kind": kind, **{key: binding[key] for key in (
        "repository", "shared_remote", "auth_namespace", "deployment_object_id", "runner")}}
    enrollment = {"schema": 1, "protocol": "aifactory-physical-lock-v1", "enforcement": "all-writers-exclusive",
                  "revision": 1, "writers": {binding["writer_id"]: writer}, "scopes": {
                      binding["targets"][0]["resource_group_ids"][0].lower(): {
                          "writers": [binding["writer_id"]], "target": target, "common_dependencies": [],
                          "scope_kind": "aifactory-owned", "allow_delete": True}}}
    binding["locks"]["coordination_hash"] = protocol.fingerprint(enrollment)
    path = catalog.binding_path(root, factory, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(binding), encoding="utf-8")
    return factory, scale, binding, path, enrollment


@pytest.mark.parametrize("kind,runner", [
    ("gha", {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"}),
    ("ado", {"kind": "hosted", "os": "linux", "image": "ubuntu-22.04"}),
    ("gha", {"kind": "self-hosted", "os": "linux", "labels": ["self-hosted", "linux", "private-network"]}),
    ("ado", {"kind": "self-hosted", "os": "linux", "pool": "Private Linux"}),
])
def test_explicit_runner_and_current_github_identity_are_bound(root, service, kind, runner):
    factory, scale, _, _, enrollment = write_binding(root, service, kind, runner)
    cli = Cli(enrollment)
    result = protocol.load_binding(root, factory, scale, cli)
    assert result["route"]["runner"] == runner
    assert result["_delete_authorized"] is True
    if kind == "gha":
        assert result["route"]["github_user_id"] == 12345
        cli.actor = 67890
        assert protocol.load_binding(root, factory, scale, cli)["route"]["github_user_id"] == 67890
    else:
        assert all(tool != "gh" for tool, _ in cli.calls)


def test_namespaced_binding_never_infers_a_runner(root, service):
    factory, scale, binding, path, enrollment = write_binding(
        root, service, "gha", {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"})
    binding.pop("runner")
    path.write_text(json.dumps(binding), encoding="utf-8")
    cli = Cli(enrollment)
    with pytest.raises(CatalogError, match="explicit.*runner"):
        protocol.load_binding(root, factory, scale, cli)
    assert not cli.calls


@pytest.mark.parametrize("actor", [None, "12345", True, 0])
def test_github_identity_must_be_verified_numeric_account(root, service, actor):
    factory, scale, _, _, enrollment = write_binding(
        root, service, "gha", {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"})
    with pytest.raises(CatalogError, match="GitHub account"):
        protocol.load_binding(root, factory, scale, Cli(enrollment, actor))


def test_runner_is_part_of_exact_live_writer_enrollment(root, service):
    factory, scale, binding, path, enrollment = write_binding(
        root, service, "gha", {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"})
    enrollment["writers"][binding["writer_id"]]["runner"] = {
        "kind": "hosted", "os": "linux", "image": "ubuntu-22.04"}
    binding["locks"]["coordination_hash"] = protocol.fingerprint(enrollment)
    path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(CatalogError, match="exact writer"):
        protocol.load_binding(root, factory, scale, Cli(enrollment))


@pytest.mark.parametrize("runner", [
    {"kind": "hosted", "os": "windows", "image": "windows-latest"},
    {"kind": "self-hosted", "os": "linux", "labels": ["private"]},
    {"kind": "self-hosted", "os": "linux", "pool": "wrong-orchestrator"},
    {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04", "command": "unsupported"},
])
def test_runner_schema_rejects_unsupported_or_ambiguous_selection(root, service, runner):
    factory = migrate(root, service)
    binding = {**binding_for(factory), "runner": runner}
    with pytest.raises(ValidationError):
        RuntimeBinding.model_validate(binding)


def test_per_target_execution_binds_distinct_tenant_principal_and_runner(root, service):
    factory, _, binding, path, enrollment = write_binding(
        root, service, "gha", {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"})
    document = catalog.load_document(root)
    factory = document["factories"][0]
    stage = factory["scale_sets"][1]
    stage.update(subscription_id=str(uuid4()), tenant_id=str(uuid4()))
    catalog.commit_document(root, document)
    execution = {"writer_id": "stage-writer", "auth_namespace": "stage-auth", "deployment_object_id": str(uuid4()),
                 "runner": {"kind": "self-hosted", "os": "linux", "labels": ["self-hosted", "linux", "stage-private"]}}
    group = f"/subscriptions/{stage['subscription_id']}/resourceGroups/stage-owned"
    binding["targets"].append({"scale_set_id": stage["id"], "resource_group_ids": [group],
                               "common_dependency_ids": [], "execution": execution})
    enrollment["writers"][execution["writer_id"]] = {
        "kind": "gha", "repository": binding["repository"], "shared_remote": True,
        **{key: execution[key] for key in ("auth_namespace", "deployment_object_id", "runner")}}
    enrollment["scopes"][group.lower()] = {
        "writers": [execution["writer_id"]], "scope_kind": "aifactory-owned", "allow_delete": True, "common_dependencies": [],
        "target": {"factory_id": factory["id"], "scaleset_id": stage["id"], "prefix": factory["prefix"],
                   "region": factory["region"], **{key: stage[key] for key in
                       ("environment", "suffix", "subscription_id", "tenant_id")}}}
    binding["locks"]["coordination_hash"] = protocol.fingerprint(enrollment)
    path.write_text(json.dumps(binding), encoding="utf-8")
    before = path.read_bytes()
    selected = protocol.load_binding(root, factory, stage, Cli(enrollment))
    assert selected["route"]["writer_id"] == execution["writer_id"]
    assert selected["route"]["auth_namespace"] == execution["auth_namespace"]
    assert selected["route"]["runner"] == execution["runner"]
    assert selected["_deployment_object_id"] == execution["deployment_object_id"]
    assert selected["locks"]["scopes"] == [group]
    default = protocol.load_binding(root, factory, factory["scale_sets"][0], Cli(enrollment))
    assert default["route"]["writer_id"] == binding["writer_id"]
    assert path.read_bytes() == before
