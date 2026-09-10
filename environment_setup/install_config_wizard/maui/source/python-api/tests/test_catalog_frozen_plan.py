import copy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src import catalog_protocol as protocol, factory_catalog as catalog
from src.catalog_frozen_plan import FrozenPlanner
from src.catalog_storage import CatalogError, catalog_lock, database, encode, read_json
from tests.test_catalog_runtime import OWNER, SUB, TENANT, RG, VERSION, Pty, root, harness, deploy_request, request


class Planner:
    changed = False

    def prepare(self, root, request, document, version, bindings, evidence, config, now, expires):
        factory = catalog.select_factory(document, request["factory_id"])
        scales = [catalog.select_scale(factory, request["scale_set_id"])] if request["scale_set_id"] else factory["scale_sets"]
        manifests = []
        for scale, binding in zip(scales, bindings):
            manifest = protocol.manifest(str(uuid4()), factory, scale, request, version, config, binding,
                                         evidence, [], now, expires, frozen=True)
            owner = {"factory_id": factory["id"], "scaleset_id": scale["id"]}
            group = binding["locks"]["scopes"][0]
            if request["action"].startswith("delete"):
                manifest["deletion"] = {
                    "inventory_mode": "arm-provider-closure-v1", "inventory_complete": True,
                    "resource_groups": [{"id": group, "delete": True, "owner": owner}],
                    "resources": [{"id": group + "/providers/Microsoft.Network/publicIPAddresses/ownedip",
                                   "delete": True, "owner": owner, "depends_on": []}],
                }
            else:
                manifest["config"] = {"credential": "secret-profile-value"}
                manifest["deployment"] = {"contract": 1, "changes": [{"resource_id": group, "change_type": "Create"}],
                                          "steps": [{"id": "common", "parameters": {"credential": "secret-profile-value"}}]}
            manifest.pop("manifest_hash")
            manifest["manifest_hash"] = protocol.fingerprint(manifest)
            manifests.append(manifest)
        return manifests

    def refresh(self, *args):
        if self.changed:
            raise CatalogError("Frozen what-if changed; prepare again.", 409)


def scoped(runtime, kind="ado", groups=None, dependencies=None):
    original = runtime.binding
    def binding(root, factory, scale):
        value = original(root, factory, scale)
        value["_deployment_object_id"] = TENANT
        value["route"].update(kind=kind, scoped_contract=1, auth_namespace="catalog-auth", shared_remote=True)
        value["route"]["repository"] = ("https://github.com/org/catalog" if kind == "gha" else
                                        "https://dev.azure.com/org/project/_git/repo")
        value["route"]["runner"] = {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"}
        if kind == "gha":
            value["route"]["github_user_id"] = 12345
        if groups:
            value["locks"]["scopes"] = [groups[scale["id"]]]
        value["locks"]["common_dependencies"] = (dependencies or {}).get(scale["id"], [])
        return value
    runtime.binding = binding
    runtime.planner = Planner()


def worker_result(manifest):
    return {"worker_receipt": {
        "schema": 1, "status": "succeeded", "run_id": manifest["run_id"],
        "manifest_hash": manifest["manifest_hash"], "source_commit": manifest["source"]["commit"],
        "deployments": [{"step_id": step["id"], "status": "succeeded"} for step in manifest["deployment"]["steps"]],
        "inventory_closure_hash": "a" * 64,
        "target": manifest["target"], "ownership": [
            {"resource_id": scope + "/providers/Microsoft.Network/publicIPAddresses/ownedip", "owner": {
                **{key: manifest["target"][key] for key in ("factory_id", "scaleset_id")},
                **({"project_id": manifest["target"]["project_ids"][0]} if manifest["target"]["project_ids"] else {})}}
            for scope in manifest["locks"]["scopes"]],
        "resource_groups": [
            {"resource_id": scope, "owner": {key: manifest["target"][key] for key in ("factory_id", "scaleset_id")},
             "body_hash": "b" * 64, "etag": None} for scope in manifest["locks"]["scopes"]]}}


class CohortPty(Pty):
    def __init__(self, argv, cwd, env, result, *, fail_second=False, transform=None):
        self.closed = False
        self.argv, self.cwd, self.env = argv, cwd, env
        self.output = ["safe cohort output\r\n", ""]
        self.exit_code = 1 if fail_second else 0
        assert "--cohort" in argv
        protected = Path(argv[argv.index("--protected-manifest") + 1])
        documents = json.loads(protected.read_bytes().removeprefix(b"protected:"))
        assert isinstance(documents, list)
        cohort_hash = protocol.fingerprint(sorted(item["manifest_hash"] for item in documents))
        assert argv[argv.index("--expected-hash") + 1] == cohort_hash
        children = []
        for index, manifest in enumerate(documents):
            child = {"schema": 1, "operation": "delete", "run_id": manifest["run_id"],
                     "manifest_revision": manifest["manifest_revision"], "manifest_hash": manifest["manifest_hash"],
                     "cohort_hash": cohort_hash, "target": manifest["target"],
                     "source_commit": manifest["source"]["commit"], "source_ref": manifest["source"]["ref"],
                     "status": "reconciliation-required" if fail_second and index >= 1 else "succeeded",
                     "lock_retained": fail_second, "locks_retained": manifest["locks"]["scopes"] if fail_second else [],
                     "deleted_resources": []}
            if not fail_second or index <= 1:
                child.update(result(manifest))
            children.append(child)
        first = documents[0]
        aggregate = {"schema": 1, "operation": "delete-factory", "factory_id": first["target"]["factory_id"],
                     "source_commit": first["source"]["commit"], "source_ref": first["source"]["ref"],
                     "cohort_hash": cohort_hash, "status": "reconciliation-required" if fail_second else "succeeded",
                     "lock_retained": fail_second, "locks_retained": first["locks"]["scopes"] if fail_second else [],
                     "children": children}
        if transform:
            transform(aggregate)
        receipt = Path(argv[argv.index("--receipt") + 1])
        receipt.parent.mkdir(parents=True)
        for child in aggregate["children"]:
            (receipt.parent / (child["run_id"] + ".receipt.json")).write_text(json.dumps(child), encoding="utf-8")
        receipt.write_text(json.dumps(aggregate), encoding="utf-8")


@pytest.mark.parametrize("route", ["ado", "gha"])
def test_common_only_scoped_deploy_protects_parameters_and_records_receipt(root, harness, route):
    service, runtime, factory, queue, _ = harness
    scoped(runtime, route)
    runtime.pty_factory = lambda argv, cwd, env: Pty(argv, cwd, env, worker_result)
    command = deploy_request(root, factory)
    command.pop("project_id")
    preview = service.prepare(command, OWNER)
    assert preview["can_execute"], preview["blockers"]
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    run = root / "config-wizard" / "catalog-runs" / job["id"]
    public = read_json(run / "manifest.json")
    child = public["manifests"][0]
    assert child["target"]["project_ids"] == []
    assert child["operation"] == "create-scaleset"
    assert "parameters" not in child["deployment"]["steps"][0]
    assert "secret-profile-value" not in json.dumps(public)
    with database(root) as db:
        for row in db.execute("SELECT payload FROM confirmations"):
            assert "secret-profile-value" not in row["payload"]
            payload = json.loads(row["payload"])
            if payload["runtime"]:
                assert payload["runtime"]["sealed_manifests"] is None
    queue.pop()()
    assert runtime.job(root, job["id"], OWNER)["status"] == "succeeded"
    assert not (run / "configuration.dpapi").exists()
    stored = catalog.load_document(root)
    assert stored["ownership_evidence"][RG.lower()]["ownership_source"] == "deployment-receipt"
    assert RG in stored["factories"][0]["scale_sets"][0]["owned_resource_ids"]


def test_changed_frozen_plan_blocks_confirmation(root, harness):
    service, runtime, factory, queue, _ = harness
    scoped(runtime)
    preview = service.prepare(deploy_request(root, factory), OWNER)
    assert preview["can_execute"], preview["blockers"]
    runtime.planner.changed = True
    with pytest.raises(CatalogError, match="what-if changed"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)
    assert not queue


@pytest.mark.parametrize("defect", ["hash", "schema", "missing-steps", "step-status", "step-id", "closure", "project-owner",
                                   "missing-groups", "foreign-group", "group-hash"])
def test_scoped_receipt_mismatch_retains_catalog(root, harness, defect):
    service, runtime, factory, queue, _ = harness
    scoped(runtime)
    def result(manifest):
        value = worker_result(manifest)
        worker = value["worker_receipt"]
        if defect == "hash":
            worker["manifest_hash"] = "0" * 64
        elif defect == "schema":
            worker["schema"] = 2
        elif defect == "missing-steps":
            worker.pop("deployments")
        elif defect == "step-status":
            worker["deployments"][0]["status"] = "running"
        elif defect == "step-id":
            worker["deployments"][0]["step_id"] = "unreviewed"
        elif defect == "closure":
            worker["inventory_closure_hash"] = ""
        elif defect == "project-owner":
            worker["ownership"][0]["owner"].pop("project_id")
        elif defect == "missing-groups":
            worker.pop("resource_groups")
        elif defect == "foreign-group":
            worker["resource_groups"][0]["owner"]["factory_id"] = "foreign"
        elif defect == "group-hash":
            worker["resource_groups"][0]["body_hash"] = ""
        return value
    runtime.pty_factory = lambda argv, cwd, env: Pty(argv, cwd, env, result)
    revision = catalog.source_revision(root)
    preview = service.prepare(deploy_request(root, factory), OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    queue.pop()()
    assert runtime.job(root, job["id"], OWNER)["status"] == "failed"
    assert catalog.source_revision(root) == revision


@pytest.mark.parametrize("fail_second", [False, True])
def test_factory_delete_defers_catalog_commit_until_all_children_verified(root, harness, fail_second):
    service, runtime, factory, queue, records = harness
    document = catalog.load_document(root)
    groups = {}
    for scale in document["factories"][0]["scale_sets"]:
        group = f"/subscriptions/{SUB}/resourceGroups/owned-{scale['environment']}"
        groups[scale["id"]] = group
        scale["owned_resource_ids"] = [group]
        records.append({"resource_id": group, "factory_id": factory["id"], "scale_set_id": scale["id"], "shared": False})
    catalog.commit_document(root, document)
    # Stage depends on Dev common: its removal must finish before Dev.
    dev, stage = factory["scale_sets"][:2]
    scoped(runtime, groups=groups, dependencies={stage["id"]: [groups[dev["id"]]]})
    seen = []
    def result(manifest):
        seen.append(manifest["target"]["scaleset_id"])
        assert len(catalog.load_document(root)["factories"][0]["scale_sets"]) == 3
        return {"deleted_resources": [item["id"] for item in [
            *manifest["deletion"]["resources"], *manifest["deletion"]["resource_groups"]]]}
    def pty(argv, cwd, env):
        return CohortPty(argv, cwd, env, result, fail_second=fail_second)
    runtime.pty_factory = pty
    revision = catalog.source_revision(root)
    preview = service.prepare(request(root, "delete-factory", factory_id=factory["id"], version_ref="124"), OWNER)
    assert preview["can_execute"], preview["blockers"]
    assert len(preview["inventory"]) == 6
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    queue.pop()()
    final = runtime.job(root, job["id"], OWNER)
    if fail_second:
        assert final["status"] == "failed"
        assert catalog.source_revision(root) == revision
        run = root / "config-wizard" / "catalog-runs" / job["id"]
        assert len(list((run / "execution").glob("*.receipt.json"))) == 3
        assert (run / "configuration.dpapi").exists()
    else:
        assert final["status"] == "succeeded", final["message"]
        assert catalog.load_document(root)["factories"] == []
        assert seen.index(stage["id"]) < seen.index(dev["id"])
        assert not (root / "config-wizard" / "catalog-runs" / job["id"] / "configuration.dpapi").exists()


def test_profile_ciphertext_participates_in_both_revision_checks(root, harness):
    service, runtime, factory, _, _ = harness
    scoped(runtime)
    scale = factory["scale_sets"][0]
    path = FrozenPlanner.profile_path(root, factory, scale)
    path.write_bytes(b"protected-profile-one")
    target = catalog.target_revision(root, factory["id"])
    preview = service.prepare(deploy_request(root, factory), OWNER)
    assert preview["can_execute"]
    path.write_bytes(b"protected-profile-two")
    assert catalog.target_revision(root, factory["id"]) != target
    with pytest.raises(CatalogError, match="changed"):
        service.confirm(str(root), preview["confirmation_id"], OWNER)


TARGET = {"environment": "stage", "region": "swedencentral", "prefix": "factory", "suffix": "002",
          "factory_id": str(uuid4()), "scaleset_id": str(uuid4()), "project_ids": []}


def test_parameter_mapper_resolves_typed_values_and_forces_common_only():
    schema = {name: {"type": kind} for name, kind in (
        ("env", "string"), ("location", "string"), ("commonRGNamePrefix", "string"), ("aifactorySuffixRG", "string"),
        ("tags", "object"), ("enabled", "bool"), ("capacity", "int"), ("items", "array"),
        ("enableAIFactoryCreatedDefaultProjectForAIFv2", "bool"))}
    variables = {"enabled": "true", "capacity": "$(size)", "size": "7", "items": '["$(region)"]',
                 "region": "swedencentral", "enableAIFactoryCreatedDefaultProjectForAIFv2": "true"}
    values = FrozenPlanner.parameters(schema, variables, {}, TARGET)
    assert values["env"] == "test" and values["aifactorySuffixRG"] == "-002"
    assert values["enabled"] is True and values["capacity"] == 7
    assert values["items"] == ["swedencentral"]
    assert values["enableAIFactoryCreatedDefaultProjectForAIFv2"] is False
    assert "projectNumber" not in values
    assert values["tags"]["aifactory.factory_id"] == TARGET["factory_id"]


@pytest.mark.parametrize("schema,variables,overrides", [
    ({"value": {"type": "string"}}, {}, {}),
    ({"value": {"type": "string"}}, {"value": "$(cycle)", "cycle": "$(value)"}, {}),
    ({"value": {"type": "object"}}, {"value": {"secret": "$(missing)"}}, {}),
    ({"value": {"type": "object"}}, {"value": {"secret": "[parameters('secret')]"}}, {}),
    ({"value": {"type": "object"}}, {"value": '{"secret": "[parameters(\'secret\')]"}'}, {}),
    ({"value": {"type": "bool"}}, {"value": 1}, {}),
    ({"value": {"type": "string", "allowedValues": ["safe"]}}, {"value": "other"}, {}),
    ({"env": {"type": "string"}}, {}, {"env": "prod"}),
    ({"value": {"type": "string"}}, {}, {"unpublished": "secret"}),
])
def test_parameter_mapper_rejects_incomplete_or_conflicting_profiles(schema, variables, overrides):
    with pytest.raises(CatalogError):
        FrozenPlanner.parameters(schema, variables, overrides, TARGET)


def test_protected_profile_rejects_other_source_and_unknown_fields(root, harness):
    _, runtime, factory, _, _ = harness
    planner = FrozenPlanner(runtime)
    scale = factory["scale_sets"][0]
    path = planner.profile_path(root, factory, scale)
    module = SimpleNamespace(unprotect=lambda data: data)
    for value in ({"schema": 1, "source_commit": "c" * 40}, {"schema": 1, "arbitrary-command": "no"}):
        path.write_bytes(encode(value))
        with pytest.raises(CatalogError, match="malformed"):
            planner._profile(module, root, factory, scale, VERSION)


def test_full_group_deletion_cannot_promote_leaf_ownership(root, harness):
    _, runtime, factory, _, _ = harness
    document = catalog.load_document(root)
    document["factories"][0]["scale_sets"][0]["owned_resource_ids"] = [RG + "/providers/Microsoft.Network/publicIPAddresses/ownedip"]
    command = request(root, "delete-scale-set", factory_id=factory["id"], scale_set_id=factory["scale_sets"][0]["id"], project_id=None)
    class Blocked(ValueError):
        pass
    module = SimpleNamespace(Blocked=Blocked, verify_source=lambda *args: None,
                             capabilities=lambda: {"contract": 1, "delete_owned_resource_groups": "arm-provider-closure-v1"},
                             freeze_deletion_inventory=lambda *args: pytest.fail("No cascade authority"))
    planner = FrozenPlanner(runtime, cloud_factory=lambda *args: object())
    planner.module = lambda *args: (module, root)
    evidence = runtime.inventory(root, factory, factory["scale_sets"])
    config = runtime._configuration(factory, factory["scale_sets"], document, command)
    with pytest.raises(CatalogError, match="leaf ownership"):
        planner.prepare(root, command, document, VERSION, [runtime.binding(root, factory, factory["scale_sets"][0])],
                        evidence, config, catalog.utc(100), catalog.utc(700))


@pytest.mark.parametrize("previous_ownership", [False, True])
def test_compiled_common_plan_has_complete_steps_and_no_default_project(root, harness, previous_ownership):
    _, runtime, factory, _, _ = harness
    document = catalog.load_document(root)
    scale = factory["scale_sets"][0]
    command = deploy_request(root, factory)
    command.pop("project_id")
    command.setdefault("project_id", None)
    scoped(runtime)
    binding = runtime.binding(root, factory, scale)
    binding["route"]["runner"] = {"kind": "self-hosted", "os": "linux", "pool": "Private Linux", "agent_name": "worker-1"}
    config = runtime._configuration(factory, [scale], document, command)
    config["targets"][scale["id"]]["dev"].update(
        useSelfHostedBuildAgent="true", adminVMBuildAgentPool="Private Linux", adminVMBuildAgentName="worker-1",
        BYO_subnets="false")
    manifest = protocol.manifest(str(uuid4()), factory, scale, command, VERSION, config, binding,
                                 runtime.inventory(root, factory, [scale]), [], catalog.utc(100), catalog.utc(700), frozen=True)
    manifest["identity"]["deployment_object_id"] = TENANT
    templates = {name: "environment_setup/aifactory/bicep/esml-common/main/" + name + ".bicep"
                 for name in ("11-rgCommon", "12-networkCommon", "13-rgLevel")}
    schema = {name: {"type": kind} for name, kind in (
        ("env", "string"), ("location", "string"), ("commonRGNamePrefix", "string"),
        ("aifactorySuffixRG", "string"), ("tags", "object"), ("enableAIFactoryCreatedDefaultProjectForAIFv2", "bool"))}
    def compile_template(source, path):
        return {"$schema": "subscriptionDeploymentTemplate.json" if "11-rgCommon" in path else "deploymentTemplate.json",
                "parameters": schema}
    observed = []
    module = SimpleNamespace(COMMON_TEMPLATES=templates, PROJECT_TEMPLATES=set(), digest=protocol.fingerprint,
                             validate_deployment_plan=lambda value: observed.append(copy.deepcopy(value)),
                             freeze_deployment_plan=lambda cloud, value, source: copy.deepcopy(value["deployment"]))
    resource = RG + "/providers/Microsoft.Network/publicIPAddresses/ownedip"
    evidence = {"run_id": str(uuid4()), "receipt_hash": "e" * 64}
    record = {"owner": {"factory_id": factory["id"], "scaleset_id": scale["id"]},
              "ownership_source": "deployment-receipt", "ownership_evidence": evidence}
    ledger = {RG.lower(): copy.deepcopy(record), resource.lower(): copy.deepcopy(record)} if previous_ownership else {}
    planner = FrozenPlanner(runtime)
    planner._deployment(module, SimpleNamespace(compile_template=compile_template), root, factory, scale,
                        manifest, root, VERSION, ownership_records=ledger)
    assert manifest["deployment"]["known_ownership"] == ({resource.lower(): evidence} if previous_ownership else {})
    if previous_ownership:
        assert RG.lower() in ledger
    assert len(observed) == 1
    assert len(manifest["deployment"]["steps"]) == 3
    assert manifest["deployment"]["steps"][0]["scope"] == "subscription"
    assert all(step["parameters"]["enableAIFactoryCreatedDefaultProjectForAIFv2"] is False for step in manifest["deployment"]["steps"])
    assert manifest["target"]["project_ids"] == []
    assert manifest["config"]["useSelfHostedBuildAgent"] == "true"
    assert manifest["config"]["adminVMBuildAgentPool"] == "Private Linux"
    assert manifest["config"]["adminVMBuildAgentName"] == "worker-1"
    assert manifest["config"]["BYO_subnets"] == "false"


def test_job_progress_persists_while_catalog_operations_hold_the_file_lock(root, harness):
    service, runtime, factory, queue, _ = harness
    preview = service.prepare(deploy_request(root, factory), OWNER)
    job = service.confirm(str(root), preview["confirmation_id"], OWNER)["job"]
    session = runtime.terminals.get(job["id"])
    with catalog_lock(root):
        runtime._save_job(root, session["job"])
        assert runtime.job(root, job["id"], OWNER)["status"] == "queued"
    queue.pop()()
    assert runtime.job(root, job["id"], OWNER)["status"] == "succeeded"


@pytest.mark.parametrize("missing", ["scoped_runners", "creation", "shared_remote_namespaced_auth", "scoped_group_ownership_receipt"])
def test_published_capabilities_must_acknowledge_scoped_settings_before_cloud_reads(root, harness, missing):
    _, runtime, factory, _, _ = harness
    scoped(runtime)
    document = catalog.load_document(root)
    command = {**deploy_request(root, factory), "project_id": None}
    scale = factory["scale_sets"][0]
    capabilities = {"contract": 1, "scoped_worker_os": ["linux"], "scoped_runners": ["hosted", "self-hosted"],
                    "project_routes": ["ado", "gha"], "creation": "frozen-arm-deployment-plan-v1",
                    "shared_remote_namespaced_auth": True,
                    "scoped_group_ownership_receipt": "resource-group-ownership-v1"}
    capabilities.pop(missing)
    planner = FrozenPlanner(runtime, cloud_factory=lambda *args: pytest.fail("Unsupported published settings must block before cloud reads"))
    planner.module = lambda *args: (SimpleNamespace(capabilities=lambda: capabilities), root)
    with pytest.raises(CatalogError, match="published release"):
        planner.prepare(root, command, document, VERSION, [runtime.binding(root, factory, scale)],
                        runtime.inventory(root, factory, [scale]),
                        runtime._configuration(factory, [scale], document, command),
                        catalog.utc(100), catalog.utc(700))
