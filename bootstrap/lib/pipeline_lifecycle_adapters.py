"""Provider CAS and native, API-independent lifecycle adapters.

Existing enrollment, inventory, ownership, permissions, private-network and
worker implementations remain authoritative. This module does not relax their
guards or replace a missing enrollment with an inferred identity.
"""

from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

import factory_enrollment
import factory_lifecycle as fl
import provider_repository_state
from pipeline_lifecycle import PipelineError, LifecycleService, bound_plan, digest, identifier, require
from pipeline_lifecycle_parameters import parameters
from pipeline_lifecycle_keyvault import CONTRACT as KEYVAULT_TRANSPORT, is_reference, validate_reference


SECRET_KEYS = {"accesstoken", "clientsecret", "serviceprincipalsecret", "password", "adminpassword",
               "adminpasswordvm", "personalaccesstoken", "pat", "authorization", "privatekey", "accountkey",
               "connectionstring", "authclientsecret", "sastoken"}


def no_secret_material(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            sensitive = normalized in SECRET_KEYS or normalized.endswith(
                ("password", "clientsecret", "accesstoken", "connectionstring", "accountkey", "privatekey"))
            if sensitive and is_reference(child):
                validate_reference(child)
            else:
                require(not sensitive or child in ("", None), "secret-material-in-durable-state")
            no_secret_material(child)
    elif isinstance(value, list):
        for child in value:
            no_secret_material(child)
    elif isinstance(value, str):
        require("-----BEGIN PRIVATE KEY-----" not in value and not re.search(
            r"(?i)(?:SharedAccessSignature|AccountKey|sig)=[^;&\s]+", value), "secret-material-in-durable-state")


class RepositoryJournal:
    """Record-level CAS on the existing state ref, preserving native run records."""

    def __init__(self, provider_state):
        self.store = provider_state

    @staticmethod
    def key(operation_id):
        return "pipeline-lifecycle/" + identifier(operation_id) + ".json"

    def read(self, operation_id):
        head, state = self.store.read()
        record = (state or {}).get("records", {}).get(self.key(operation_id))
        return (head, digest(record)), copy.deepcopy(record)

    def write(self, operation_id, expected, record):
        no_secret_material(record)
        head, state = self.store.read()
        state = state or self.store.empty()
        key = self.key(operation_id)
        # Native workers write different keys while running. Rebase only when
        # this exact record is unchanged; never retry the provider CAS write.
        require(digest(state["records"].get(key)) == expected[1], "operation-cas-conflict")
        state["records"][key] = copy.deepcopy(record)
        new_head = self.store.replace(head, state)
        return new_head, digest(record)

    def ownership(self, factory_id, baseline=None):
        _, state = self.store.read()
        operations = [value for key, value in (state or {}).get("records", {}).items()
                      if key.startswith("pipeline-lifecycle/")
                      and value.get("status") in ("succeeded", "continuation-required")
                      and value.get("snapshot", {}).get("factory", {}).get("id") == factory_id]
        result = copy.deepcopy(baseline or {})
        for operation in sorted(operations, key=lambda value: value["prepared_at"]):
            require(digest(operation["snapshot"]) == operation["snapshot_hash"]
                    and digest(bound_plan(operation)) == operation["plan_hash"], "journal-evidence-binding-mismatch")
            for stage in operation["stages"]:
                receipt = (stage["observation"] if stage.get("observation", {}).get("verified") is True
                           else stage.get("receipt", {}))
                require(stage["status"] in ("succeeded", "continuation-required") and receipt.get("verified") is True
                        and receipt.get("status") == stage["status"], "journal-stage-not-verified")
                for child in receipt.get("children", []):
                    native = child.get("native") or {}
                    removed = native.get("deleted_resources", []) + native.get("deleted_resource_groups", [])
                    for deleted in removed:
                        result = {key: value for key, value in result.items()
                                  if key != deleted.lower() and not key.startswith(deleted.lower() + "/")}
                    worker = child.get("worker")
                    if not worker:
                        continue
                    require(worker.get("status") == "succeeded" and worker.get("target", {}).get("factory_id") == factory_id,
                            "journal-worker-not-verified")
                    for row in worker.get("resource_groups", []) + worker.get("ownership", []):
                        require(row.get("owner", {}).get("factory_id") == factory_id, "journal-owner-mismatch")
                        result[row["resource_id"].lower()] = {
                            "owner": copy.deepcopy(row["owner"]), "ownership_source": "deployment-receipt",
                            "ownership_evidence": {"run_id": worker["run_id"], "receipt_hash": fl.digest(worker)}}
        return result


def selected_binding(snapshot, scale):
    try:
        return _selected_binding(snapshot, scale)
    except factory_enrollment.EnrollmentError as error:
        raise PipelineError(error.code) from None


def _selected_binding(snapshot, scale):
    supplied = snapshot.get("binding")
    provider = snapshot["request"]["provider"]
    binding = snapshot["document"].get("bindings", {}).get(snapshot["factory"]["id"], {}).get(provider)
    require(isinstance(binding, dict) and binding.get("contract_version") == 1
            and binding.get("orchestrator") == provider and isinstance(supplied, dict) and supplied,
            "enrollment-and-external-trust-required")
    factory_enrollment._validate_binding(binding)
    operational_keys = {"schema", "provider", "consumer_commit", "consumer_ref", "pipeline_id"}
    operational = {key: value for key, value in supplied.items() if key in operational_keys}
    if operational:
        require(type(operational.get("schema")) is int and operational["schema"] == 1
                and operational.get("provider") == provider, "operational-binding-schema-invalid")
        require("consumer_commit" not in operational or isinstance(operational["consumer_commit"], str)
                and re.fullmatch(r"[a-f0-9]{40}", operational["consumer_commit"]),
                "operational-binding-consumer-commit-invalid")
        require("consumer_ref" not in operational or operational["consumer_ref"] == binding["ref"],
                "operational-binding-consumer-ref-mismatch")
        require("pipeline_id" not in operational or provider == "ado"
                and type(operational["pipeline_id"]) is int and operational["pipeline_id"] > 0,
                "operational-binding-pipeline-invalid")
    native_supplied = {key: value for key, value in supplied.items()
                       if key not in operational_keys | {"bootstrap", "admission"}}
    if "contract_version" in native_supplied:
        require(native_supplied == binding, "canonical-binding-projection-mismatch")
    else:
        require(operational and set(native_supplied) == {"repository"}
                and native_supplied["repository"] == binding["repository"],
                "operational-binding-fields-invalid")
    parsed = urlsplit(binding["repository"])
    path = unquote(parsed.path)
    pattern = (r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" if provider == "gha"
               else r"/[A-Za-z0-9_. -]+/[A-Za-z0-9_. -]+/_git/[A-Za-z0-9_. -]+")
    require(parsed.scheme == "https" and parsed.netloc == ("github.com" if provider == "gha" else "dev.azure.com")
            and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
            and re.fullmatch(pattern, path) and not any(part in (".", "..") for part in path.split("/"))
            and fl.valid_ref(binding["ref"]), "native-binding-route-invalid")
    matches = [item for item in binding.get("targets", []) if item.get("scale_set_id") == scale["id"]]
    require(len(matches) == 1, "exact-enrolled-scale-binding-required")
    target = copy.deepcopy(matches[0])
    target.setdefault("common_dependency_ids", [])
    effective = {**binding, **(target.get("execution") or {})}
    for key in ("writer_id", "auth_namespace", "deployment_object_id", "runner", "locks",
                "repository", "ref", "shared_remote"):
        require(key in effective, "incomplete-enrolled-binding:" + key)
    require(all(re.fullmatch(factory_enrollment.NAME, str(effective[key])) for key in ("writer_id", "auth_namespace")),
            "native-binding-execution-namespace-invalid")
    factory_enrollment.guid(effective["deployment_object_id"])
    factory_enrollment.validate_runner(effective["runner"], binding["orchestrator"])
    scopes = [factory_enrollment.rg_id(value) for value in target["resource_group_ids"]]
    dependencies = [factory_enrollment.rg_id(value) for value in target.get("common_dependency_ids", [])]
    require(len(set(scopes + dependencies)) == len(scopes + dependencies)
            and all(value.split("/")[2] == scale["subscription_id"].lower() for value in scopes),
            "native-binding-physical-scope-invalid")
    return effective, target


def operation_identity(cloud, scale):
    raw = json.loads(cloud.command(["az", "account", "get-access-token", "--resource", fl.ARM,
                                    "--subscription", scale["subscription_id"], "--output", "json"]))
    try:
        part = raw["accessToken"].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        oid = claims["oid"]
        require(fl.guid(oid) and claims.get("tid", "").lower() == scale["tenant_id"].lower()
                and claims.get("aud") in (fl.ARM, fl.ARM + "/", "https://management.core.windows.net/",
                                         "797f4846-ba00-4fd7-ba43-dac1f8f63013")
                and float(claims.get("exp", 0)) > time.time() + 60
                and float(claims.get("nbf", 0)) <= time.time() + 60, "authenticated-operator-required")
        return oid
    except (ValueError, KeyError, IndexError, TypeError):
        raise PipelineError("authenticated-operator-required") from None


def projects_for(snapshot, scale):
    return [project for project in snapshot["projects"] if any(
        place["scale_set_id"] == scale["id"] and place["environment"] == scale["environment"]
        for place in project["placements"])]


def freeze_deletion(snapshot, scale, projects, document, cloud, records):
    scenario = snapshot["request"]["scenario"]
    if scenario == 4:
        options = {"environments": [scale["environment"]],
                  "include_project_subnets": snapshot["request"]["include_project_subnets"],
                  "include_keyvault_and_resource_group": snapshot["request"]["include_keyvault_and_resource_group"]}
        document["deletion_scope"] = {
           "kind": "project", "contract": fl.SELECTIVE_PROJECT_DELETE, "project_id": projects[0]["id"],
           "project_number": projects[0]["number"], "options": options,
           "registered_resource_ids": scale["owned_resource_ids"]}
        document["reviewed_scope"] = {"factory_id": snapshot["factory"]["id"], "project_id": projects[0]["id"],
                                     "deletion_options": options, "expected_revision": digest(snapshot["document"])}
        return fl.freeze_project_deletion(cloud, document, records)
    require({scope.lower() for scope in document["locks"]["scopes"]}
           <= {resource.lower() for resource in scale["owned_resource_ids"]}, "registered-group-ownership-required")
    if scenario == 6:
        registered = [{"project_id": project["id"], "project_number": project["number"],
                      "registered_resource_ids": scale["owned_resource_ids"]} for project in projects]
        return fl.freeze_factory_deletion_pipeline(cloud, document, records, registered)
    return fl.freeze_deletion_inventory(cloud, document, records)


class NativePlanner:
    def __init__(self, repo_root, source_root, *, cloud_factory=None, review, journal=None, provider_context=None):
        self.repo_root, self.source_root = Path(repo_root), Path(source_root)
        self.cloud_factory, self.review, self.journal = cloud_factory, review, journal
        self.provider_context = copy.deepcopy(provider_context)

    def prepare(self, snapshot, operation_id, *, input_snapshot_hash=None, coordination_only=False):
        request, factory = snapshot["request"], snapshot["factory"]
        scenario = request["scenario"]
        require(not coordination_only or scenario >= 4, "deletion-coordination-only-required")
        require(snapshot["scales"], "selected-scales-required")
        require(factory.get("kind", "ai") == "ai", "unsupported-factory-type")
        if scenario == 6:
            expected = {scale["id"] for scale in factory["scale_sets"]
                        if request["environment"] == "all" or scale["environment"] == request["environment"]}
            require(expected == {scale["id"] for scale in snapshot["scales"]}, "complete-factory-cohort-required")
        # Resolve all bindings before even authenticating: no partial factory
        # cohort and no implicit cold-start federation or scope adoption.
        bindings = [selected_binding(snapshot, scale) for scale in snapshot["scales"]]
        origin = self.review.origin(snapshot)
        if snapshot.get("binding", {}).get("consumer_commit"):
            require(snapshot["binding"]["consumer_commit"] == origin["commit"],
                    "operational-binding-consumer-commit-mismatch")
        if self.provider_context is not None:
            require(self.provider_context["request_digest"] == (input_snapshot_hash or digest(snapshot))
                    and self.provider_context["provider"] == origin["provider"]
                    and str(self.provider_context["run_id"]) == origin["run_id"]
                    and self.provider_context["run_attempt"] == origin["attempt"]
                    and self.provider_context["consumer_commit"] == origin["commit"],
                    "provider-context-binding-mismatch")
        manifests = []
        for scale, (binding, physical) in zip(snapshot["scales"], bindings):
            projects = projects_for(snapshot, scale)
            operation = {1: "create-factory", 2: "create-scaleset", 3: "deploy-project",
                         4: "delete", 5: "delete", 6: "delete"}[scenario]
            if scenario in (1, 3, 4):
                require(len(projects) == 1, "one-exact-project-placement-required")
            target = {"factory_id": factory["id"], "factory_type": factory.get("kind", "ai"),
                      "scaleset_id": scale["id"], "prefix": factory["prefix"], "region": factory["region"],
                      **{key: scale[key] for key in ("environment", "tenant_id", "subscription_id", "suffix")},
                      "project_ids": [project["number"] for project in projects] if scenario != 2 else []}
            route = {"kind": request["provider"], "scoped_contract": 1,
                     **{key: binding[key] for key in ("writer_id", "repository", "ref", "shared_remote",
                                                     "auth_namespace", "runner")}}
            prepared = datetime.now(timezone.utc)
            document = {"schema": 1, "operation": operation, "run_id": str(uuid4()), "manifest_revision": 1,
                        "prepared_at": prepared.isoformat(),
                        "expires_at": (prepared + timedelta(seconds=fl.MANIFEST_MAX_LIFETIME_SECONDS)).isoformat(),
                        "source": {**snapshot["source"], "version": snapshot["source"]["ref"]},
                        "target": target, "identity": {"object_id": binding["deployment_object_id"],
                                                      "deployment_object_id": binding["deployment_object_id"]},
                        "route": route, "locks": {"provider": "azure-blob-lease", **binding["locks"],
                                                  "scopes": physical["resource_group_ids"],
                                                  "common_dependencies": physical["common_dependency_ids"]},
                        "config": {}}
            if coordination_only:
                document.pop("operation")
            from pipeline_lifecycle_cloud import PipelineCloud
            cloud = self.cloud_factory(document) if self.cloud_factory else PipelineCloud(document, origin)
            oid = operation_identity(cloud, scale)
            document["identity"]["object_id"] = oid
            cloud.document, cloud.expected_object_id = document, oid
            cloud.verify_identity()
            remote = cloud.command(["git", "ls-remote", "--exit-code", route["repository"], route["ref"]]).split()
            require(len(remote) == 2 and remote[1] == route["ref"] and re.fullmatch(r"[a-f0-9]{40}", remote[0]),
                    "exact-published-consumer-ref-required")
            route["commit"] = remote[0]
            require(origin.get("commit") == route["commit"], "provider-consumer-commit-mismatch")
            if route["kind"] == "gha":
                actor = json.loads(cloud.command(["gh", "api", "user", "--hostname", "github.com", "--method", "GET"]))
                require(type(actor.get("id")) is int and actor["id"] > 0, "authenticated-github-identity-required")
                route["github_user_id"] = actor["id"]
            require(cloud.command(["git", "rev-parse", "HEAD"], cwd=str(self.source_root))
                    == document["source"]["commit"], "exact-source-checkout-required")
            fl.verify_source(cloud, self.source_root, document["source"])
            fl.coordination(cloud, document).verify_enrollment()
            if coordination_only:
                manifests.append(document)
                continue
            records = snapshot["document"].get("ownership_evidence", {})
            if self.journal:
                records = self.journal.ownership(factory["id"], records)
            if scenario < 4:
                document["deployment"] = self.deployment(snapshot, scale, projects, document, cloud, records)
            else:
                document["deletion"] = freeze_deletion(snapshot, scale, projects, document, cloud, records)
            document["manifest_hash"] = fl.manifest_digest(document)
            fl.validate_manifest(document)
            no_secret_material(document)
            manifests.append(document)
        return {"stages": [{"id": "lifecycle", "kind": "lifecycle", "manifests": manifests}],
                "provider_context": self.provider_context,
                "origin": origin, "review": {
                    "scenario": scenario, "factory_id": factory["id"],
                    "targets": [manifest["target"] for manifest in manifests],
                    "source": snapshot["source"], "manifest_hashes": [
                        item["manifest_hash"] for item in manifests if "manifest_hash" in item],
                    "deletions": [row["id"] for item in manifests for row in
                                  item.get("deletion", {}).get("resources", [])
                                  + item.get("deletion", {}).get("resource_groups", []) if row.get("delete")],
                    "retained": [row["id"] for item in manifests for row in
                                 item.get("deletion", {}).get("resources", [])
                                 + item.get("deletion", {}).get("resource_groups", []) if not row.get("delete")]}}

    def deployment(self, snapshot, scale, projects, document, cloud, records=None):
        common = document["operation"] != "deploy-project"
        known = {
            key.lower(): row["ownership_evidence"]
            for key, row in (records or {}).items() if "/providers/" in key.lower()
            and row.get("owner", {}).get("factory_id") == document["target"]["factory_id"]
            and row.get("owner", {}).get("scaleset_id") == document["target"]["scaleset_id"]
            and isinstance(row.get("ownership_evidence"), dict)}
        producer = fl.foundry_identity_preparation(cloud, document, known) if known else None
        parameter_run = producer or document
        section = "dev" if scale["environment"] == "dev" else "stage_prod"
        settings = snapshot["configuration"]
        base = {**settings.get("factory", {}), **settings.get("scale_sets", {}).get(scale["id"], {})}
        if common and projects:
            base.update(snapshot["variables"][projects[0]["id"]]["dev"])
            base.update(snapshot["variables"][projects[0]["id"]][section])
        base.update(dev_test_prod="test" if scale["environment"] == "stage" else scale["environment"],
                    dev_test_prod_sub_id=scale["subscription_id"],
                    deployment_random_value=parameter_run["run_id"].replace("-", "")[:10])
        paths = [(path, None) for path in fl.COMMON_TEMPLATES.values()] if common else []
        byo = str(base.get("BYO_subnets", "false")).lower() == "true"
        if byo:
            paths = [item for item in paths if item[0] != fl.COMMON_TEMPLATES["12-networkCommon"]]
        for project in projects:
            paths.extend((path, project) for path in sorted(
                fl.PROJECT_TEMPLATES, key=lambda value: (0 if Path(value).stem == "31-network" else 1, value)))
        steps = []
        for path, project in paths:
            values = copy.deepcopy(base)
            if project:
                projection = snapshot["variables"][project["id"]]
                values.update(projection["dev"])
                values.update(projection[section])
            template = cloud.compile_template(self.source_root, path)
            resolved = parameters(template, values, document["target"],
                                  project=project["number"] if project else None,
                                  prepared_at=parameter_run["prepared_at"])
            scope = "subscription" if "subscriptiondeploymenttemplate" in template.get("$schema", "").lower() else "resource-group"
            step = {"id": "step-" + (project["number"] + "-" if project else "") + Path(path).stem,
                    "kind": "project" if project else "common", "template": path,
                    "template_hash": fl.digest(template), "parameters": resolved, "scope": scope,
                    "resource_groups": document["locks"]["scopes"],
                    "depends_on": [steps[-1]["id"]] if steps else []}
            if scope == "resource-group":
                if path.endswith("/31-network.bicep"):
                    # This canonical template targets the explicitly configured
                    # VNet group, not a group inferred from a project name.
                    name = resolved.get("vnetResourceGroup_param") or resolved.get("vnetResourceGroup")
                    identifier = "/subscriptions/" + scale["subscription_id"] + "/resourceGroups/" + str(name)
                    require(fl.RG_ID.fullmatch(identifier) and identifier.lower() in {
                        item.lower() for item in document["locks"]["scopes"]},
                        "project-network-resource-group-not-enrolled")
                    step["resource_group"] = identifier
                    step["resource_groups"] = [identifier]
                else:
                    require(len(document["locks"]["scopes"]) == 1, "exact-template-resource-group-binding-required")
                    step["resource_group"] = document["locks"]["scopes"][0]
            if project:
                step["project_id"] = project["number"]
                step["owner"] = {key: document["target"][key] for key in ("factory_id", "scaleset_id")}
                step["owner"]["project_id"] = project["number"]
            steps.append(step)
        document["config"] = (copy.deepcopy(snapshot["variables"][projects[0]["id"]]) if not common else
                              {"environment": scale["environment"],
                               "common_parameters": {step["id"]: step["parameters"] for step in steps},
                               **{key: base[key] for key in ("BYO_subnets", "useSelfHostedBuildAgent",
                                                             "selfHostedRunnerLabel", "adminVMBuildAgentPool",
                                                             "adminVMBuildAgentName") if key in base}})
        document["deployment"] = {"contract": 1, "network_mode": "byo" if byo else "managed",
                                  "configuration_hash": fl.digest(document["config"]), "steps": steps,
                                  "known_ownership": known}
        if any(is_reference(value) for step in steps for value in step["parameters"].values()):
            require(fl.capabilities().get("arm_parameter_transport") == KEYVAULT_TRANSPORT,
                    "native-keyvault-reference-transport-required")
            document["deployment"]["parameter_transport"] = KEYVAULT_TRANSPORT
        # Native planning verifies network preservation, exact schemas, live
        # what-if, ownership and Foundry phases; no fabricated what-if rows.
        return fl.freeze_deployment_plan(cloud, document, self.source_root)


def observe_foundry_runtime(cloud, document, worker):
    """Reuse native gates with GET-only evidence, never a fabricated write lease."""
    manifest_hash = digest(document)
    def observe(resource_id, api_version):
        require(digest(document) == manifest_hash, "foundry-observation-manifest-changed")
        cloud.verify_identity()
        status, _, body = cloud.arm("GET", resource_id, api_version, allowed=(200, 404))
        require(status == 200 and isinstance(body, dict)
                and str(body.get("id", "")).lower() == resource_id.lower(),
                "foundry-runtime-evidence-missing")
        return body
    fl.verify_foundry_live_readiness(cloud, None, document, worker, None, observe=observe)
    for row in worker.get("foundry_agent_readiness", {}).get("network_resources", []):
        body = observe(row["id"], row["api_version"])
        require(body.get("properties", {}).get("provisioningState") == "Succeeded"
                and fl.resource_digest(body) == row["body_hash"], "foundry-runtime-network-changed")


class NativeExecutor:
    def __init__(self, source_root, state_root, *, cloud_factory=None, review=None):
        self.source_root, self.state_root = Path(source_root), Path(state_root)
        self.transport_factory = cloud_factory
        self.origin = None
        self.review = review

    def cloud_factory(self, document):
        if self.transport_factory:
            return self.transport_factory(document)
        from pipeline_lifecycle_cloud import PipelineCloud
        require(isinstance(self.origin, dict), "authenticated-parent-origin-required")
        return PipelineCloud(document, self.origin)

    def execute(self, stage, record):
        self.origin = record.get("plan", {}).get("origin")
        require(stage["kind"] == "lifecycle" and stage["manifests"], "unsupported-native-stage")
        documents = stage["manifests"]
        for document in documents:
            cloud = self.cloud_factory(document)
            require(cloud.command(["git", "rev-parse", "HEAD"], cwd=str(self.source_root))
                    == document["source"]["commit"], "exact-source-checkout-required")
        execution = self.state_root / identifier(record["operation_id"]) / stage["id"]
        receipt_path = execution / "receipt.json"
        if documents[0].get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
            result = fl.execute_factory_deletion_cohort(documents, self.source_root, execution, receipt_path,
                                                        cloud_factory=self.cloud_factory)
        elif len(documents) > 1:
            require(all(item["operation"] == "delete" for item in documents), "native-deletion-cohort-required")
            result = fl.execute_cohort(documents, self.source_root, execution, receipt_path,
                                       cloud_factory=self.cloud_factory)
        else:
            result = fl.execute(documents[0], self.source_root, execution, receipt_path,
                                cloud=self.cloud_factory(documents[0]))
        if result.get("status") != "succeeded":
            return {"status": result.get("status", "reconciliation-required"), "verified": False, "native": result}
        observation = self.observe(stage, record)
        if (result.get("continuation_required") or result.get("completion") == "identity-only") \
                and observation.get("status") != "continuation-required":
            return {"status": "continuation-required", "verified": False, "native": result}
        return observation

    def _receipt(self, document, *, observation=False):
        cloud = self.cloud_factory(document)
        # A separately authenticated observer needs read access, not possession
        # of the completed job's workload identity. This changes only the
        # read-only transport's expected token subject, never the manifest's
        # execution authority or the identity used to execute/cancel effects.
        cloud.expected_object_id = (operation_identity(cloud, document["target"]) if observation
                                    else document["identity"]["object_id"])
        cloud.verify_identity()
        locks = fl.coordination(cloud, document)
        locks.verify_enrollment()
        status, _, receipt = locks.request("GET", "runs/" + document["run_id"] + ".json", allowed=(200, 404))
        if status == 404:
            return cloud, locks, None
        require(receipt.get("run_id") == document["run_id"]
                and receipt.get("manifest_hash") == document["manifest_hash"], "native-receipt-binding-mismatch")
        return cloud, locks, receipt

    @staticmethod
    def provider_result(cloud, document, remote):
        route = document["route"]
        require(isinstance(remote, dict) and remote.get("kind") == route["kind"]
                and str(remote.get("run_id", "")).isdigit(), "verified-provider-run-required")
        run_id = str(remote["run_id"])
        if route["kind"] == "gha":
            endpoint = "repos/" + urlsplit(route["repository"]).path.strip("/") + "/actions/runs/" + run_id
            _, _, run = cloud.state_request("gha", "GET", endpoint, None, (200,))
            require(run.get("head_sha") == route["commit"] and str(run.get("id")) == run_id,
                    "native-provider-run-binding-mismatch")
            return run.get("status") == "completed" and run.get("conclusion") == "success"
        org, project, _, _ = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
        endpoint = "https://dev.azure.com/" + quote(org) + "/" + quote(project) + "/_apis/build/builds/" + run_id + "?api-version=7.1"
        _, _, run = cloud.state_request("ado", "GET", endpoint, None, (200,))
        require(run.get("sourceVersion") == route["commit"] and str(run.get("id")) == run_id,
                "native-provider-run-binding-mismatch")
        return run.get("status") == "completed" and run.get("result") == "succeeded"

    def observe(self, stage, record):
        self.origin = (self.review.origin(record["snapshot"]) if self.review is not None
                       else record.get("plan", {}).get("origin"))
        children = []
        continuation = False
        for document in stage["manifests"]:
            cloud, locks, receipt = self._receipt(document, observation=True)
            if not receipt or receipt.get("status") != "succeeded":
                return {"status": "reconciliation-required", "verified": False,
                        "run_id": document["run_id"]}
            present_scopes = []
            for scope in document["locks"]["scopes"] + document["locks"]["common_dependencies"]:
                status, _, body = cloud.arm("GET", scope, fl.RG_API, allowed=(200, 404))
                require(status in (200, 404), "native-scope-observation-failed")
                if document["operation"] != "delete" or scope in document["locks"]["common_dependencies"]:
                    require(status == 200, "native-deployed-resource-group-missing")
                if status == 200:
                    require(isinstance(body, dict) and str(body.get("id", "")).lower() == scope.lower(),
                            "native-scope-identity-mismatch")
                    cloud.assert_no_active_deployments(scope)
                    present_scopes.append(scope)
            cloud.assert_no_active_runs(locks.enrollment)
            if "deployment" in document or document.get("deletion", {}).get("inventory_mode") == "ordered-project-pipelines-v1":
                require(self.provider_result(cloud, document, receipt.get("remote_run")),
                        "provider-completion-not-verified")
                worker = fl.verify_worker_receipt(locks, document)
                if receipt.get("continuation_required") or receipt.get("completion") == "identity-only":
                    fl.verify_foundry_identity_receipt(document, worker)
                    fl.revalidate_foundry_identity_receipt(cloud, document, worker["foundry_identity_receipt"])
                    continuation = True
                if "deployment" in document:
                    from pipeline_lifecycle_reconciliation import NativeReconciliationEvidence
                    _, bodies = fl.collect_resource_closure(cloud, present_scopes)
                    prefix = "runs/" + document["run_id"]
                    NativeReconciliationEvidence._completed_outcome(
                        cloud, document, {prefix + ".json": receipt, prefix + ".worker.json": worker},
                        bodies, set(), worker=worker)
            else:
                worker = None
            if document["operation"] == "delete":
                removed = []
                absent_at_review = set()
                for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"]:
                    if not row["delete"]:
                        status, _, body = cloud.arm("GET", row["id"], row.get("api_version", fl.RG_API),
                                                     allowed=(200, 404))
                        require(status == 200 and isinstance(body, dict)
                                and str(body.get("id", "")).lower() == row["id"].lower(),
                                "retained-resource-missing")
                        continue
                    status, _, body = cloud.arm("GET", row["id"], row.get("api_version", fl.RG_API), allowed=(200, 404))
                    require(status == 404, "deleted-resource-reappeared")
                    from pipeline_lifecycle_reconciliation import _not_found
                    _not_found(body, ("ResourceGroupNotFound",) if fl.RG_ID.fullmatch(row["id"])
                               else ("ResourceNotFound", "ParentResourceNotFound", "ResourceGroupNotFound"),
                               "deleted-resource-absence-unverified")
                    removed.append(row["id"])
                    if row.get("already_absent") is True:
                        absent_at_review.add(row["id"].lower())
                expected = set(map(str.lower, removed))
                observed_absent = set(map(str.lower, receipt.get("observed_absent", [])))
                require(expected - absent_at_review == set(map(str.lower,
                        receipt.get("deleted_resources", []) + receipt.get("deleted_resource_groups", [])))
                        and absent_at_review <= observed_absent <= expected,
                        "native-deletion-receipt-incomplete")
            children.append({"native": receipt, "worker": worker, "observer_object_id": cloud.expected_object_id})
        return {"status": "continuation-required" if continuation else "succeeded",
                "verified": True, "children": children,
                **({"runtime_ready": not continuation}
                   if any("foundry_lifecycle" in doc.get("deployment", {}) for doc in stage["manifests"]) else {}),
                **({"runtime_ready": False, "continuation": {
                    "requires_fresh_review": True, "stage": "foundry-project"}} if continuation else {})}

    def cancel(self, stage, record):
        self.origin = record.get("plan", {}).get("origin")
        # A provider cancellation is not an ARM rollback. Keep claims and the
        # journal even when the provider acknowledges the request.
        requested = []
        for document in stage["manifests"]:
            cloud, _, receipt = self._receipt(document)
            remote = (receipt or {}).get("remote_run")
            if not remote:
                continue
            self.provider_result(cloud, document, remote)
            route, run_id = document["route"], str(remote["run_id"])
            if route["kind"] == "gha":
                endpoint = "repos/" + urlsplit(route["repository"]).path.strip("/") + "/actions/runs/" + run_id + "/cancel"
                cloud.state_request("gha", "POST", endpoint, None, (202, 409))
            else:
                org, project, _, _ = unquote(urlsplit(route["repository"]).path).strip("/").split("/")
                endpoint = "https://dev.azure.com/" + quote(org) + "/" + quote(project) + "/_apis/build/builds/" + run_id + "?api-version=7.1"
                cloud.state_request("ado", "PATCH", endpoint, {"status": "cancelling"}, (200,))
            requested.append(remote)
        return {"requested": requested, "terminal_verified": False}


class NativeAuthorizationEvidence:
    """Fresh read-only native checks for the separate enrollment authorization."""

    def __init__(self, executor, journal):
        self.executor, self.journal = executor, journal

    def __call__(self, stage, record):
        if record is not None:
            self.executor.origin = (self.executor.review.origin(record["snapshot"])
                                    if self.executor.review is not None else record["plan"]["origin"])
        proposal = stage["deletion_authorization"]
        document = proposal["canonical"]["before"]["document"]
        ownership = self.journal.ownership(proposal["factory_id"], document.get("ownership_evidence", {}))
        inventories, identities, dependencies = [], [], []
        for original in stage["manifests"]:
            manifest = copy.deepcopy(original)
            cloud = self.executor.cloud_factory(manifest)
            oid = operation_identity(cloud, manifest["target"])
            cloud.expected_object_id = oid
            manifest["identity"]["object_id"] = oid
            cloud.document = manifest
            cloud.verify_identity()
            locks = fl.coordination(cloud, manifest)
            locks.verify_enrollment()
            cloud.assert_no_active_runs(locks.enrollment)
            if "request" in proposal:
                scope = next(row for row in proposal["selected_scales"]
                             if row["id"] == manifest["target"]["scaleset_id"])
                snapshot = {"request": proposal["request"], "factory": {"id": proposal["factory_id"]},
                            "document": document, "projects": proposal["selected_projects"]}
                inventory = freeze_deletion(snapshot, scope, projects_for(snapshot, scope), manifest, cloud, ownership)
            else:
                inventory = fl.freeze_deletion_inventory(cloud, manifest, ownership)
            fl.verify_project_permissions(cloud, inventory)
            for scope in manifest["locks"]["common_dependencies"]:
                closure, _ = fl.collect_resource_closure(cloud, [scope])
                cloud.assert_no_active_deployments(scope)
                dependencies.append(closure)
            inventories.append(inventory)
            identities.append({"observer": oid, "execution": manifest["identity"]["deployment_object_id"]})
        return {key: copy.deepcopy(proposal[key]) for key in (
                    "repository", "factory_id", "scopes", "common_dependencies")} | {
            "inventory_complete": True, "active_operations": [],
            "owner_hash": digest([row["resource_groups"] + row["resources"] for row in inventories]),
            "identity_hash": digest(identities), "inventory_hash": digest(inventories),
            "permission_hash": digest([fl.project_delete_roots(row) for row in inventories]),
            "dependency_hash": digest(dependencies), "observed_at": datetime.now(timezone.utc).isoformat()}


class NativeSetupEvidence:
    """Read identity, ownership and competing runs before enabling shared policy."""

    def __init__(self, review, *, cloud_factory=None):
        self.review, self.cloud_factory = review, cloud_factory

    def __call__(self, snapshot, scopes):
        from pipeline_lifecycle_cloud import PipelineCloud
        factory = snapshot["factory"]
        origin = self.review.origin(snapshot)
        observations = []
        for scale in factory["scale_sets"]:
            selected = [scope for scope in scopes if scope.split("/")[2] == scale["subscription_id"].lower()]
            if not selected:
                continue
            document = {"target": scale, "identity": {"object_id": "00000000-0000-0000-0000-000000000001"},
                        "route": {"kind": snapshot["request"]["provider"],
                                  "repository": snapshot["binding"]["repository"], "ref": origin["ref"]},
                        "locks": {"provider": "provider-repository-cas", "coordination_mode": "single-writer",
                                  "scopes": selected, "common_dependencies": []}}
            cloud = self.cloud_factory(document, origin) if self.cloud_factory else PipelineCloud(document, origin)
            oid = operation_identity(cloud, scale)
            document["identity"]["object_id"] = oid
            cloud.expected_object_id = oid
            cloud.verify_identity()
            enrollment = {"writers": {"setup": document["route"]},
                          "scopes": {scope: {"writers": ["setup"]} for scope in selected}}
            cloud.assert_no_active_runs(enrollment)
            absent = set(fl.absent_groups(cloud, selected))
            for scope in selected:
                status, _, body = cloud.arm("GET", scope, fl.RG_API, allowed=(200, 404))
                require(status != 404 or scope in absent, "admission-install-group-absence-changed")
                if status == 200:
                    require(str(body.get("id", "")).lower() == scope
                            and body.get("tags", {}).get("aifactory.factory_id") == factory["id"]
                            and body.get("tags", {}).get("aifactory.scaleset_id")
                            in {row["id"] for row in factory["scale_sets"]},
                            "admission-install-group-owner-mismatch")
                    cloud.assert_no_active_deployments(scope)
                observations.append({"scope": scope, "status": status, "operator": oid})
        require({row["scope"] for row in observations} == set(scopes), "admission-install-scope-tenant-mismatch")
        return {"verified": True, "factory_id": factory["id"], "repository": snapshot["binding"]["repository"],
                "scopes": scopes, "active_operations": [], "observations": observations}


class RuntimeAdapters:
    """Select enrollment before native binding resolution, with one journal."""

    def __init__(self, native_planner, native_executor, bootstrap, *, authorization=None, setup=None,
                 reconciliation=None, bootstrap_reconciliation=None):
        self.native_planner, self.native_executor, self.bootstrap = native_planner, native_executor, bootstrap
        self.authorization = authorization
        self.setup = setup
        self.reconciliation = reconciliation
        self.bootstrap_reconciliation = bootstrap_reconciliation

    def prepare_recovery(self, snapshot, prior, operation_id, *, input_snapshot_hash=None):
        adapter = (self.bootstrap_reconciliation if prior["plan"]["stages"][0]["kind"] == "bootstrap-enrollment"
                   else self.reconciliation)
        require(adapter is not None, "reconciliation-adapter-required")
        stage = adapter.prepare(snapshot, prior, operation_id)
        origin = stage["reconciliation"]["origin"]
        context = self.native_planner.provider_context
        if context is not None:
            require(context["request_digest"] == (input_snapshot_hash or digest(snapshot))
                    and str(context["run_id"]) == origin["run_id"] and context["provider"] == origin["provider"]
                    and context["consumer_commit"] == origin["commit"], "recovery-context-binding-mismatch")
        reprepare = stage["reconciliation"]["requires_reprepare"]
        return {"stages": [stage], "origin": origin, "provider_context": context, "continuation_required": reprepare,
                "review": {"kind": "reconcile-retained-native-claim", "prior_operation_id": prior["operation_id"],
                           "scopes": stage["reconciliation"]["scopes"], "live_evidence": stage["reconciliation"]["evidence"],
                           "next": ("New native residual plan and fresh protected approval; no failed write is replayed."
                                    if reprepare else "Persist verified completed effects; do not replay the native operation.")}}

    def prepare_residual(self, snapshot, parent, operation_id, *, input_snapshot_hash=None):
        from types import SimpleNamespace
        if parent["plan"]["stages"][0]["kind"] == "bootstrap-reconciliation":
            require(self.bootstrap_reconciliation is not None, "bootstrap-reconciliation-adapter-required")
            self.bootstrap_reconciliation.observe(parent["plan"]["stages"][0], parent)
            return self.bootstrap.prepare(snapshot, operation_id, input_snapshot_hash=input_snapshot_hash)
        require(self.reconciliation is not None, "reconciliation-adapter-required")
        planner = SimpleNamespace(prepare=lambda value, selected: self.native_planner.prepare(
            value, selected, input_snapshot_hash=input_snapshot_hash))
        return self.reconciliation.prepare_residual(snapshot, parent, operation_id, planner=planner)

    def prepare(self, snapshot, operation_id, *, input_snapshot_hash=None):
        if self.setup is not None and self.setup.needed():
            bindings = snapshot["document"]["bindings"].get(snapshot["factory"]["id"], {})
            scopes = {scope.lower() for binding in bindings.values() for target in binding["targets"]
                      for scope in target["resource_group_ids"]}
            if self.bootstrap.needed(snapshot):
                scopes.update(self.bootstrap._physical(snapshot).values())
            plan = self.setup.prepare(snapshot, operation_id, sorted(scopes))
            plan["provider_context"] = self.native_planner.provider_context
            return plan
        if snapshot["request"]["scenario"] >= 4 and self.authorization is not None:
            coordination = self.native_planner.prepare(snapshot, operation_id, coordination_only=True,
                                                       input_snapshot_hash=input_snapshot_hash)
            manifests = coordination["stages"][0]["manifests"]
            provider_backed = all(fl.single_writer(item) for item in manifests)
            state = self.authorization.provider.read()[1] if provider_backed else None
            enrolled = (state or {}).get("enrollment") or {}
            scopes = {scope.lower() for item in manifests for scope in item["locks"]["scopes"]}
            if provider_backed and any(
                    enrolled.get("scopes", {}).get(scope, {}).get("allow_delete") is not True for scope in scopes):
                self.native_executor.origin = coordination["origin"]
                stage = self.authorization.prepare(snapshot, operation_id, manifests)
                return {**coordination, "stages": [stage], "continuation_required": True,
                        "review": {"kind": "deletion-authorization-only", "next": "prepare-continuation",
                                   "authorization": stage["deletion_authorization"]}}
        planner = self.bootstrap if self.bootstrap.needed(snapshot) else self.native_planner
        if input_snapshot_hash is not None:
            return planner.prepare(snapshot, operation_id, input_snapshot_hash=input_snapshot_hash)
        return planner.prepare(snapshot, operation_id)

    def _executor(self, stage):
        if stage.get("kind") == "bootstrap-reconciliation":
            require(self.bootstrap_reconciliation is not None, "bootstrap-reconciliation-adapter-required")
            return self.bootstrap_reconciliation
        if stage.get("kind") == "retained-claim-reconciliation":
            require(self.reconciliation is not None, "reconciliation-adapter-required")
            return self.reconciliation
        if stage.get("kind") == "admission-installation":
            require(self.setup is not None, "admission-installation-adapter-required")
            return self.setup
        if stage.get("kind") == "deletion-authorization":
            require(self.authorization is not None, "deletion-authorization-adapter-required")
            return self.authorization
        require(stage.get("kind") in ("bootstrap-enrollment", "lifecycle"), "unsupported-native-stage")
        return self.bootstrap if stage["kind"] == "bootstrap-enrollment" else self.native_executor

    def execute(self, stage, record):
        return self._executor(stage).execute(stage, record)

    def observe(self, stage, record):
        observation = self._executor(stage).observe(stage, record)
        if stage["kind"] == "deletion-authorization" and observation.get("verified") is True:
            current = copy.deepcopy(stage)
            proposal = current["deletion_authorization"]
            for document in current["manifests"]:
                document["locks"].update(coordination_hash=proposal["coordination_hash"]["to"],
                                         revision=proposal["enrollment"]["after"]["revision"])
            proposal["canonical"]["before"] = copy.deepcopy(proposal["canonical"]["after"])
            self.authorization._evidence(current, record)
        return observation

    def cancel(self, stage, record):
        if stage["kind"] in ("bootstrap-enrollment", "deletion-authorization", "admission-installation",
                             "retained-claim-reconciliation", "bootstrap-reconciliation"):
            return {"requested": [], "terminal_verified": False, "reconciliation_required": True}
        return self.native_executor.cancel(stage, record)


def build_service(snapshot, *, repo_root, source_root, state_root, provider_context=None):
    from pipeline_lifecycle_review import ProtectedJobReview
    from pipeline_lifecycle_bootstrap import BootstrapAdapter
    scale = snapshot["scales"][0]
    if BootstrapAdapter.needed(snapshot):
        binding = snapshot["binding"]
        require(isinstance(binding.get("bootstrap"), dict), "enrollment-and-external-trust-required")
        parsed = urlsplit(binding.get("repository", ""))
        provider_kind = snapshot["request"]["provider"]
        require(parsed.scheme == "https"
                and parsed.netloc == {"gha": "github.com", "ado": "dev.azure.com"}.get(provider_kind)
                and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
                "bootstrap-consumer-route-required")
    else:
        binding, _ = selected_binding(snapshot, scale)
    state_request = {"coordination_mode": "single-writer",
                     "target": {"tenant_id": scale["tenant_id"], "subscription_id": scale["subscription_id"]},
                     "route": {"kind": snapshot["request"]["provider"], "repository": binding["repository"]}}
    if snapshot["request"]["provider"] == "ado":
        state_request["ado_tenant_id"] = (snapshot["binding"].get("bootstrap", {}).get("ado_tenant_id")
                                         or snapshot["configuration"]["factory"].get("ado_tenant_id"))
    from pipeline_lifecycle_cloud import PipelineEnrollmentCloud
    cloud = PipelineEnrollmentCloud(state_request)
    # This transport is used only for the existing provider state ref. No
    # enrollment.ensure or ARM provisioning runs through it.
    cloud.read_only = False
    provider = provider_repository_state.ProviderState(cloud, state_request["route"], PipelineError)
    review = ProtectedJobReview(cloud, state_request["route"])
    from pipeline_lifecycle_admission import NativeAdmission
    journal = RepositoryJournal(provider)
    native = NativeExecutor(source_root, state_root, review=review)
    bootstrap = BootstrapAdapter(repo_root, source_root, state_root, review=review,
                                 provider_context=provider_context)
    adapters = RuntimeAdapters(
        NativePlanner(repo_root, source_root, review=review, journal=journal, provider_context=provider_context),
        native, bootstrap)
    from pipeline_lifecycle_setup import AdmissionSetup
    setup = AdmissionSetup(provider, review=review, evidence=NativeSetupEvidence(review))
    adapters.setup = setup
    admission = NativeAdmission(provider, review, adapters, setup=setup)
    bootstrap.admission = admission
    from pipeline_lifecycle_authorization import DeletionAuthorization
    adapters.authorization = DeletionAuthorization(
        provider, review=review, admission=admission, evidence=NativeAuthorizationEvidence(native, journal))
    from pipeline_lifecycle_reconciliation import RetainedClaimReconciliation, NativeReconciliationEvidence
    reconciliation = RetainedClaimReconciliation(
        provider, review=review, admission=admission, evidence=NativeReconciliationEvidence(review))
    adapters.reconciliation = admission.reconciliation = reconciliation
    from pipeline_lifecycle_bootstrap_recovery import BootstrapReconciliation
    adapters.bootstrap_reconciliation = admission.bootstrap_reconciliation = BootstrapReconciliation(provider, bootstrap)
    return LifecycleService(store=journal, planner=adapters, executor=adapters, review=review,
                            admission=admission, configuration=admission)
