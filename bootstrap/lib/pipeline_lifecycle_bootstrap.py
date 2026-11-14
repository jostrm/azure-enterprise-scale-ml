"""Reviewed cold enrollment, not a second deployment engine.

An existing external platform identity, protected runner and private provider
state are prerequisites. Native enrollment creates only the reviewed target
groups, grants and federation. Its verified binding is a continuation input;
it never authorizes or reports completion of common/project deployment.
"""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re

import factory_enrollment as enrollment
import pipeline_inputs
import registered_personas
import registered_prerequisites as prerequisites
from pipeline_lifecycle import bound_plan, canonical, digest, identifier, require
from pipeline_lifecycle_parameters import expand


PLATFORM_KEYS = {"identity_id", "runner", "auth_namespace", "writer_id",
                 "deployment_role_definition_ids", "ado_tenant_id"}
SOURCE_FILES = (
    "bootstrap/lib/pipeline_lifecycle_bootstrap.py",
    "bootstrap/lib/pipeline_lifecycle_bootstrap_recovery.py",
    "bootstrap/lib/pipeline_lifecycle_cloud.py",
    "bootstrap/lib/pipeline_ancestor_runs.py",
    "bootstrap/lib/factory_enrollment.py",
    "bootstrap/lib/provider_repository_state.py",
    "bootstrap/lib/registered_prerequisites.py",
    "bootstrap/lib/registered_personas.py",
    "bootstrap/lib/pipeline_lifecycle_parameters.py",
    "environment_setup/aifactory/bicep/personas/pipeline.py",
)


def _ordinary(path, root):
    path, root = Path(path).absolute(), Path(root).resolve()
    require(path.is_relative_to(root) and path != root, "bootstrap-state-outside-consumer")
    current = root
    for part in path.relative_to(root).parts:
        require(part not in ("", ".", ".."), "unsafe-bootstrap-state-path")
        current /= part
        require(not current.is_symlink() and not getattr(current, "is_junction", lambda: False)(),
                "bootstrap-state-link-forbidden")
    require(path.resolve().is_relative_to(root), "bootstrap-state-outside-consumer")
    return path


def _normalized_state(state, operation_id, *, stage=None, record=None):
    value = copy.deepcopy(state)
    value.pop("repository_head", None)
    if value.get("enrollment"):
        value["enrollment"]["etag"] = None
    remote = value.get("repository_state")
    if remote:
        records = remote["records"]
        # Outer journals carry checkpoints, not native provisioning authority.
        # Keep canonical policy, enrollment, claims and native run evidence bound.
        for key in list(records):
            if re.fullmatch(r"pipeline-lifecycle/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.json", key):
                records.pop(key)
        if "lifecycle_admission_v1" in records:
            # The separately authenticated outer claim changes between jobs.
            # Only this claim's reviewed scope extension may accompany it;
            # canonical configuration, history and other policy remain bound.
            outer = records["lifecycle_admission_v1"]
            claim = outer.pop("claim", None)
            baseline = (stage or {}).get("admission_policy")
            if baseline and record and claim == record.get("admission_claim"):
                factory_id = record["snapshot"]["factory"]["id"]
                previous = baseline.get("factories", {}).get(factory_id, {}).get("scopes", [])
                additional = (claim or {}).get("identity", {}).get("scope_extension", [])
                if additional:
                    require(set(additional) <= set(stage["enrollment"]["scopes"])
                            and not set(additional).intersection(previous)
                            and claim["scopes"] == sorted(previous + additional),
                            "bootstrap-admission-scope-extension-mismatch")
                    expected = copy.deepcopy(baseline)
                    expected["factories"][factory_id]["scopes"] = claim["scopes"]
                    require(outer.get("policy") == expected, "bootstrap-admission-policy-changed")
                    outer["policy"] = copy.deepcopy(baseline)
        if not records and remote["active"] is None and remote["enrollment"] is None:
            value["repository_state"] = None
    return value


class _GuardedCloud:
    """Recheck the shared outer reservation before every native write."""

    def __init__(self, cloud, admission, record, groups, grant_scopes, capture=None):
        object.__setattr__(self, "_cloud", cloud)
        object.__setattr__(self, "_admission", admission)
        object.__setattr__(self, "_record", record)
        object.__setattr__(self, "_groups", {item["id"]: item["body"] for item in groups["effects"]})
        object.__setattr__(self, "_grant_scopes", set(grant_scopes))
        object.__setattr__(self, "_capture", capture)

    def __getattr__(self, name):
        return getattr(self._cloud, name)

    def __setattr__(self, name, value):
        setattr(self._cloud, name, value)

    def __delattr__(self, name):
        delattr(self._cloud, name)

    def _invoke(self, name, method, *args, **kwargs):
        if method not in ("GET", "HEAD"):
            self._admission.assert_owned(self._record)
            if self._capture is not None:
                self._capture()
        return getattr(self._cloud, name)(method, *args, **kwargs)

    def arm(self, method, identifier, version, data=None, headers=None, allowed=(200,)):
        if method == "PUT" and "/providers/microsoft.authorization/roleassignments/" in identifier.lower():
            require(identifier.lower().split("/providers/microsoft.authorization/roleassignments/")[0]
                    in self._grant_scopes, "bootstrap-role-grant-outside-reviewed-delta")
        if method == "PUT" and identifier.lower() in self._groups:
            body = self._groups[identifier.lower()]
            native_body = {"location": body["location"], "tags": {
                key: body["tags"][key] for key in ("aifactory.factory_id", "aifactory.scaleset_id")}}
            require(version == enrollment.RG_API and data == native_body, "bootstrap-group-effect-mismatch")
            # Enrollment owns the create/re-read protocol. The frozen prerequisite
            # body adds the logical project tags required by downstream workers.
            data = copy.deepcopy(body)
        result = self._invoke("arm", method, identifier, version, data, headers, allowed)
        if method == "GET" and identifier.lower() in self._groups and result[0] == 200:
            require(prerequisites._contains(result[2], self._groups[identifier.lower()]),
                    "bootstrap-created-group-ownership-mismatch")
        return result

    def gh(self, method, *args, **kwargs):
        return self._invoke("gh", method, *args, **kwargs)

    def http(self, method, *args, **kwargs):
        return self._invoke("http", method, *args, **kwargs)

    def storage(self, method, *args, **kwargs):
        return self._invoke("storage", method, *args, **kwargs)

    def state_request(self, kind, method, *args, **kwargs):
        if method not in ("GET", "HEAD"):
            self._admission.assert_owned(self._record)
        return self._cloud.state_request(kind, method, *args, **kwargs)


class BootstrapAdapter:
    def __init__(self, repo_root, source_root, state_root, *, review, admission=None,
                 cloud_factory=None, provider_context=None):
        self.repo_root, self.source_root = Path(repo_root).resolve(), Path(source_root).resolve()
        self.state_root = _ordinary(state_root, self.repo_root)
        self.review, self.admission, self.cloud_factory = review, admission, cloud_factory
        self.provider_context = copy.deepcopy(provider_context)

    @staticmethod
    def needed(snapshot, source_root=None):
        if snapshot["request"]["scenario"] not in (1, 2, 3):
            return False
        binding = snapshot["document"].get("bindings", {}).get(snapshot["factory"]["id"], {}).get(
            snapshot["request"]["provider"], {})
        selected = {scale["id"] for scale in snapshot["scales"]}
        if not selected <= {target["scale_set_id"] for target in binding.get("targets", [])}:
            return True
        if snapshot["request"]["scenario"] == 3:
            require(len(selected) == 1, "bootstrap-exact-scale-required")
            target = next(item for item in binding["targets"] if item["scale_set_id"] in selected)
            return not set(BootstrapAdapter._physical(snapshot, source_root).values()) <= {
                enrollment.rg_id(scope) for scope in target["resource_group_ids"]}
        return False

    def _source(self):
        hashes = {}
        for relative in SOURCE_FILES:
            path = self.source_root / relative
            require(path.is_file() and not path.is_symlink()
                    and path.resolve().is_relative_to(self.source_root), "bootstrap-source-file-required")
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        require(hashes[SOURCE_FILES[0]] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "bootstrap-loaded-source-mismatch")
        for module, relative in (
                (enrollment, "bootstrap/lib/factory_enrollment.py"),
                (prerequisites, "bootstrap/lib/registered_prerequisites.py"),
                (registered_personas, "bootstrap/lib/registered_personas.py")):
            require(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == hashes[relative],
                    "bootstrap-loaded-helper-source-mismatch")
        return hashes

    @staticmethod
    def _physical(snapshot, source_root=None):
        factory, scale, settings = snapshot["factory"], snapshot["scales"][0], snapshot["configuration"]
        projects = snapshot["projects"] if snapshot["request"]["scenario"] in (1, 3) else []
        require(snapshot["request"]["scenario"] not in (1, 3) or len(projects) == 1,
                "bootstrap-exact-project-required")
        values = {**settings["factory"], **settings["scale_sets"].get(scale["id"], {})}
        if projects:
            projection = snapshot["variables"][projects[0]["id"]]
            values.update(registered_personas.selected_config(projection, scale["environment"]))
        env = "test" if scale["environment"] == "stage" else scale["environment"]
        values.update(admin_aifactoryPrefixRG=factory["prefix"], admin_aifactorySuffixRG="-" + scale["suffix"],
                      admin_locationSuffix=factory["region_short_name"], dev_test_prod=env,
                      dev_test_prod_sub_id=scale["subscription_id"], AZURE_SUBSCRIPTION_ID=scale["subscription_id"])
        values[env + "_sub_id"] = scale["subscription_id"]
        if projects:
            values["project_number_000"] = projects[0]["number"]
        naming = registered_personas.pipeline_module(source_root or Path(__file__).resolve().parents[2])
        names = {"commonResourceGroup_param", "vnetResourceGroupBase", "projectPrefix", "projectSuffix"}
        aliases = names | {name.upper() for name in names} | {naming.ALIASES.get(name, name) for name in names}
        for name in aliases.intersection(values):
            values[name] = expand(values[name], values)
        physical = naming.deployment_scopes(values, scale["environment"])
        return {key: enrollment.rg_id(physical[key]) for key in ("common", *(("project",) if projects else ()))}

    def _inputs(self, snapshot, operation_id):
        identifier(operation_id)
        pipeline_inputs.public_configuration(snapshot)
        require(self.needed(snapshot, self.source_root) and len(snapshot["scales"]) == 1,
                "cold-enrollment-scope-required")
        factory, scale = snapshot["factory"], snapshot["scales"][0]
        provider, binding = snapshot["request"]["provider"], snapshot["binding"]
        platform = binding.get("bootstrap")
        require(isinstance(platform, dict) and set(platform) <= PLATFORM_KEYS
                and PLATFORM_KEYS - {"ado_tenant_id"} <= set(platform), "explicit-platform-bootstrap-required")
        require((provider == "ado") == ("ado_tenant_id" in platform), "bootstrap-ado-tenant-selection-invalid")
        enrollment.validate_runner(platform["runner"], provider)
        runner = platform["runner"]
        require(runner["kind"] == "self-hosted" and (
            "esaf-lifecycle-external" in runner.get("labels", []) if provider == "gha"
            else runner.get("pool") == "esaf-lifecycle-external"), "external-surviving-runner-required")
        identity = enrollment.resource_id(platform["identity_id"], "Microsoft.ManagedIdentity/userAssignedIdentities")
        require(identity.split("/")[2] not in {item["subscription_id"] for item in factory["scale_sets"]},
                "external-surviving-identity-required")
        roles = platform["deployment_role_definition_ids"]
        require(isinstance(roles, list) and 1 <= len(roles) <= 8 and all(isinstance(role, str) for role in roles)
                and len(set(roles)) == len(roles), "explicit-bootstrap-role-definitions-required")
        roles = [enrollment.guid(role) for role in roles]
        old = snapshot["document"].get("bindings", {}).get(factory["id"], {}).get(provider)
        if old:
            enrollment._validate_binding(old)
            require(old["locks"].get("coordination_mode") == "single-writer",
                    "bootstrap-cannot-migrate-coordination")
        require(binding.get("repository") and binding.get("consumer_ref", (old or {}).get("ref")),
                "bootstrap-consumer-route-required")
        route_ref = binding.get("consumer_ref", (old or {}).get("ref"))
        require(not old or old["repository"] == binding["repository"] and old["ref"] == route_ref,
                "bootstrap-existing-route-mismatch")
        physical = self._physical(snapshot, self.source_root)
        scopes = sorted(physical.values())
        creation, dependencies = scopes, []
        document = copy.deepcopy(snapshot["document"])
        if snapshot["request"]["scenario"] == 3:
            targets = [target for target in (old or {}).get("targets", [])
                       if target["scale_set_id"] == scale["id"]]
            require(len(targets) == 1, "bootstrap-project-existing-target-required")
            target = targets[0]
            previous = {enrollment.rg_id(scope) for scope in target["resource_group_ids"]}
            require(physical["common"] in previous and physical["project"] not in previous,
                    "bootstrap-project-exact-addition-required")
            creation = [physical["project"]]
            scopes = sorted(previous | set(creation))
            dependencies = copy.deepcopy(target.get("common_dependency_ids", []))
            # Native enrollment deliberately rejects edits of an existing target.
            # This private, reviewed projection changes only its exact scope list;
            # native merge/CAS still verifies the actual provider enrollment.
            projected = document["bindings"][factory["id"]][provider]
            next(item for item in projected["targets"] if item["scale_set_id"] == scale["id"])[
                "resource_group_ids"] = scopes
        options = {
            "repository": binding["repository"], "ref": route_ref, "shared_remote": True,
            "writer_id": platform["writer_id"], "auth_namespace": platform["auth_namespace"],
            "runner": copy.deepcopy(runner), "identity_id": identity, "coordination_mode": "single-writer",
            "resource_group_ids": scopes, "common_dependency_ids": dependencies,
            "create_resource_group_ids": creation,
            "approved_group_creation_scope": "/subscriptions/" + scale["subscription_id"],
            "deployment_roles": [{"scope": scope, "role_definition_id": role} for scope in creation for role in roles],
            **({"ado_tenant_id": platform["ado_tenant_id"]} if provider == "ado" else {}),
        }
        # This private desired register is frozen by the outer review, not
        # published canonical state, an API profile or a credential.
        folder = _ordinary(self.state_root / operation_id / "consumer" / "azurefactory", self.repo_root)
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = _ordinary(folder / "register.json", self.repo_root)
        data = canonical(document)
        if path.exists():
            require(path.is_file() and path.read_bytes() == data, "bootstrap-canonical-input-changed")
        else:
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        return enrollment.load_request(folder.parent, factory["id"], scale["id"], scale["environment"], options)

    def _cloud(self, request, origin=None):
        if self.cloud_factory:
            return self.cloud_factory(request)
        from pipeline_lifecycle_cloud import PipelineEnrollmentCloud
        return PipelineEnrollmentCloud(request, origin)

    @staticmethod
    def _native_request(request):
        retained = set(request["scopes"]) - set(request["create_resource_group_ids"])
        if not retained:
            return request
        # Native enrollment requires explicit role evidence for every retained
        # scope. Those grants are observations only, never permission to repair.
        options = copy.deepcopy(request["options"])
        roles = sorted({row["role_definition_id"] for row in request["deployment_roles"]})
        options["deployment_roles"].extend(
            {"scope": scope, "role_definition_id": role} for scope in sorted(retained) for role in roles)
        target = request["target"]
        return enrollment.load_request(request["consumer_root"], target["factory_id"], target["scaleset_id"],
                                       target["environment"], options)

    @staticmethod
    def _retained_grants(request, state):
        retained = set(request["scopes"]) - set(request["create_resource_group_ids"])
        if retained:
            previous = (state.get("enrollment") or {}).get("body", {})
            require(retained <= set(previous.get("scopes", {})), "bootstrap-retained-enrollment-missing")
        require(all(row["exists"] for row in state["roles"]["grants"]
                    if row["scope"] not in request["create_resource_group_ids"]),
                "bootstrap-retained-role-grant-missing")

    def _empty_groups(self, request, cloud, snapshot):
        builder = prerequisites.Builder(cloud)
        project = self._physical(snapshot, self.source_root).get("project")
        for scope in request["scopes"]:
            tags = {"aifactory.factory_id": request["target"]["factory_id"],
                    "aifactory.scaleset_id": request["target"]["scaleset_id"]}
            if scope == project:
                tags.update({"aifactory.project_id": snapshot["projects"][0]["number"],
                             "aifactory.logical_project_id": snapshot["projects"][0]["id"]})
            builder.ensure(scope, enrollment.RG_API, {
                "location": request["target"]["region"], "tags": tags,
            }, ownership="factory-owned")
        require(not builder.blockers, "bootstrap-existing-groups-incompatible")
        return {"effects": builder.effects, "observations": builder.observations}

    def prepare(self, snapshot, operation_id, *, input_snapshot_hash=None):
        require(input_snapshot_hash is None or isinstance(input_snapshot_hash, str)
                and re.fullmatch(r"[a-f0-9]{64}", input_snapshot_hash), "bootstrap-input-snapshot-hash-invalid")
        expected_input_hash = digest(snapshot) if input_snapshot_hash is None else input_snapshot_hash
        request = self._inputs(snapshot, operation_id)
        origin = self.review.origin(snapshot)
        repository = (request["route"]["repository"].removeprefix("https://github.com/")
                      if request["route"]["kind"] == "gha" else request["route"]["repository"])
        require(origin["provider"] == request["route"]["kind"] and origin["repository"] == repository
                and origin["ref"] == request["route"]["ref"] and origin["attempt"] == 1,
                "bootstrap-authenticated-route-mismatch")
        context = self.provider_context
        if context is not None:
            require(context["request_digest"] == expected_input_hash and context["provider"] == origin["provider"]
                    and str(context["run_id"]) == origin["run_id"] and context["run_attempt"] == 1
                    and context["consumer_commit"] == origin["commit"]
                    and context["source_commit"] == snapshot["source"]["commit"],
                    "bootstrap-provider-context-mismatch")
        native_request = self._native_request(request)
        cloud = self._cloud(native_request, origin)
        self._active_runs(cloud)
        review = enrollment.plan(native_request, cloud=cloud, acknowledge_exclusive_writer_governance=True)
        require(review["can_ensure"] and not review["blockers"], "bootstrap-enrollment-prerequisites-blocked")
        state = enrollment._snapshot(native_request, cloud)
        self._retained_grants(request, state)
        require(enrollment._review(native_request, state, True) == review, "bootstrap-plan-read-drift")
        stage = {"id": "bootstrap-enrollment", "kind": "bootstrap-enrollment",
                 "snapshot_hash": digest(snapshot), "source_hashes": self._source(),
                 "enrollment": request, "native_review": review,
                 "native_state_digest": digest(_normalized_state(state, operation_id)),
                 "admission_policy": copy.deepcopy((state.get("repository_state") or {}).get(
                     "records", {}).get("lifecycle_admission_v1", {}).get("policy")),
                 "empty_groups": self._empty_groups(request, cloud, snapshot)}
        delta = {"previous": copy.deepcopy(snapshot["document"].get("bindings", {}).get(
                     snapshot["factory"]["id"], {}).get(snapshot["request"]["provider"])),
                 "candidate": copy.deepcopy(state["candidate"])}
        return {"origin": origin, "provider_context": copy.deepcopy(context),
                "stages": [stage], "continuation_required": True,
                "review": {"kind": "external-platform-cold-enrollment", "native": review,
                           "empty_groups": stage["empty_groups"], "binding_delta": delta,
                           "next": "Persist the verified binding and prepare common/project deployment for a fresh protected review."}}

    def _validated(self, stage, record):
        require(digest(record["snapshot"]) == record["snapshot_hash"]
                and digest(bound_plan(record)) == record["plan_hash"], "bootstrap-record-hash-mismatch")
        require(stage in record["plan"]["stages"] and stage["kind"] == "bootstrap-enrollment"
                and stage["snapshot_hash"] == record["snapshot_hash"], "bootstrap-stage-binding-mismatch")
        require(self._source() == stage["source_hashes"], "bootstrap-executable-source-changed")
        request = self._inputs(record["snapshot"], record["operation_id"])
        before, after = copy.deepcopy(stage["enrollment"]), copy.deepcopy(request)
        # Absolute working directories differ across protected jobs. No logical
        # request field, reviewed permission or remote observation is relaxed.
        before.pop("consumer_root")
        after.pop("consumer_root")
        require(before == after, "bootstrap-enrollment-input-changed")
        return request

    @staticmethod
    def _continuation(request, state):
        require(not state["actions"] and not state["blockers"] and state["enrollment"]
                and state["enrollment"]["body"] == state["merged"], "bootstrap-enrollment-not-observed")
        candidate = state["candidate"]
        enrollment._validate_binding(candidate)
        return {
            "status": "continuation-required", "verified": True, "runtime_ready": False,
            "enrollment_complete": True, "binding_candidate": candidate,
            "continuation": {"requires_fresh_review": True, "stage": "common-and-project",
                             "factory_id": request["target"]["factory_id"],
                             "scale_set_id": request["target"]["scaleset_id"],
                             "provider": request["route"]["kind"], "binding_digest": digest(candidate)},
        }

    def execute(self, stage, record):
        request = self._validated(stage, record)
        require(self.admission is not None, "authenticated-shared-admission-required")
        proof = self.review.verify(record)
        require(isinstance(proof, dict) and proof, "authenticated-bootstrap-review-required")
        self.admission.assert_owned(record)
        native_request = self._native_request(request)
        from pipeline_lifecycle_bootstrap_recovery import capture_attempt
        provider = getattr(self.admission, "provider", None)
        capture = (lambda: capture_attempt(provider, stage, record)) if provider is not None else None
        cloud = _GuardedCloud(self._cloud(native_request, self.review.origin(record["snapshot"])),
                              self.admission, record, stage["empty_groups"], request["create_resource_group_ids"], capture)
        self._active_runs(cloud)
        state = enrollment._snapshot(native_request, cloud)
        self._retained_grants(request, state)
        require(digest(_normalized_state(state, record["operation_id"], stage=stage, record=record))
                == stage["native_state_digest"],
                "bootstrap-reviewed-native-state-changed")
        require(self._empty_groups(request, cloud, record["snapshot"]) == stage["empty_groups"],
                "bootstrap-reviewed-groups-changed")
        fresh = enrollment._review(native_request, state, True)
        # Native ensure re-reads this exact hash, preserving its own final CAS
        # and permission checks after expected outer-journal/claim changes.
        result = enrollment.ensure(native_request, fresh["plan_hash"], yes=True,
                                   acknowledge_exclusive_writer_governance=True, cloud=cloud)
        require(result.get("enrollment_complete") is True
                and result.get("status") in ("changed", "unchanged"), "bootstrap-native-reconciliation-required")
        observed = enrollment._snapshot(native_request, cloud)
        require(observed["candidate"] == result["binding_candidate"], "bootstrap-binding-observation-mismatch")
        require(not self._empty_groups(request, cloud, record["snapshot"])["effects"],
                "bootstrap-groups-not-observed")
        return self._continuation(request, observed)

    def observe(self, stage, record):
        request = self._validated(stage, record)
        native_request = self._native_request(request)
        cloud = self._cloud(native_request, self.review.origin(record["snapshot"]))
        state = enrollment._snapshot(native_request, cloud)
        self._retained_grants(request, state)
        require(state["identity"] == stage["native_review"]["identity"], "bootstrap-identity-observation-mismatch")
        result = self._continuation(request, state)
        require(not self._empty_groups(request, cloud, record["snapshot"])["effects"],
                "bootstrap-groups-not-observed")
        return result

    @staticmethod
    def _active_runs(cloud):
        check = getattr(cloud, "assert_no_active_runs", None)
        if check is not None:
            check()
