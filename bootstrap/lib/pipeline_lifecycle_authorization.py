"""Protected, authorization-only enrollment transition in the provider CAS store.

No Factory API, Azure mutation, worker dispatch, or admission release occurs here.
The installed ``evidence(stage, record_or_none)`` adapter must freshly authenticate
and verify native ownership, identities, permissions, complete live inventory and
dependencies, and absence of other active operations. Evidence fingerprints and
timestamps are diagnostic: drift warns, while fresh native assertions decide.
Neither fingerprints nor user-supplied flags grant consent.

``prepare(snapshot, operation_id, manifests, canonical_document=None)`` returns one
stage for a standalone protected review. Manifests are read-only coordination
documents naming the selected bindings, NOT executable deletion manifests.
The stage's ``deletion_authorization`` contains the exact before/after documents.
``execute(stage, record)`` atomically publishes enrollment, all verified canonical
binding pins and an audit. ``observe`` only reads the audit/live state. A successful
authorization requires a NEW deletion prepare and protected review.

Essential integrity bindings remain: the immutable reviewed plan/snapshot digests,
native enrollment pins to the actual enrollment body, internally consistent
canonical revisions, exact owned claim and its CURRENT canonical revision, and
the provider head for the single CAS. Actual enrollment/policy bodies and semantic
configuration must match review; catalog generation alone may change. Diagnostic
evidence hashes/timestamps are not CAS tokens, permissions, or expiry gates.
"""

import copy
from datetime import datetime, timezone
import re
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import factory_enrollment
import factory_lifecycle as fl
import lifecycle_admission
import provider_repository_state
from pipeline_lifecycle import bound_plan, digest, identifier, now, require


CONTRACT = "pipeline-deletion-authorization-v1"
AUDIT_PREFIX = "pipeline-deletion-authorizations/"
EVIDENCE_HASHES = ("owner_hash", "identity_hash", "permission_hash", "inventory_hash", "dependency_hash")
TARGET_FIELDS = ("factory_id", "scaleset_id", "environment", "tenant_id",
                 "subscription_id", "prefix", "region", "suffix")


def _scopes(values):
    require(isinstance(values, list), "authorization-scopes-required")
    result = sorted(factory_enrollment.rg_id(value) for value in values)
    require(len(result) == len(set(result)), "authorization-scopes-duplicate")
    return result


def _semantic(document):
    return {key: value for key, value in document.items() if key != "generation"}


class DeletionAuthorization:
    """Authority adapters are installed code, never loaded from request JSON."""

    def __init__(self, provider, *, review, admission, evidence):
        require(callable(evidence), "authorization-evidence-adapter-required")
        require(callable(getattr(provider, "read", None)) and callable(getattr(provider, "replace", None)),
                "authorization-provider-cas-required")
        require(callable(getattr(review, "verify", None))
                and callable(getattr(admission, "assert_owned", None)), "authorization-authority-required")
        self.provider, self.review, self.admission, self.evidence = provider, review, admission, evidence
        self.attempted_operations = set()

    def _state(self, factory_id):
        head, state = self.provider.read()
        require(head is not None and isinstance(state, dict) and isinstance(state.get("records"), dict),
                "authorization-provider-state-required")
        require(state.get("repository") == self.provider.route["repository"],
                "authorization-repository-mismatch")
        outer = state["records"].get(lifecycle_admission.RECORD)
        require(isinstance(outer, dict) and outer.get("schema") == 1
                and isinstance(outer.get("policy"), dict) and isinstance(outer.get("canonical"), dict),
                "authorization-admission-required")
        require(outer["policy"].get("repository") == state["repository"], "authorization-policy-mismatch")
        policy = outer["policy"].get("factories", {}).get(factory_id, {})
        require(policy.get("all_writers") == lifecycle_admission.PROTOCOL
                and policy.get("shared_scopes") == []
                and set(policy.get("operations", [])) == lifecycle_admission.OPERATIONS
                and set(policy.get("routes", [])) == {"api", "pipeline"},
                "authorization-all-writer-policy-required")
        _scopes(policy.get("scopes"))
        canonical = outer["canonical"].get(factory_id)
        require(isinstance(canonical, dict) and isinstance(canonical.get("document"), dict)
                and canonical.get("revision") == digest(canonical["document"])
                and all(value == canonical for value in outer["canonical"].values()),
                "authorization-canonical-invalid")
        return head, state, outer, canonical

    @staticmethod
    def _pins(document, repository, enrollment):
        """Verify every pin of this shared enrollment before advancing any pin."""
        result = []
        expected = factory_enrollment.digest(enrollment), enrollment["revision"]
        for factory_id, routes in document.get("bindings", {}).items():
            for provider, binding in routes.items():
                containers = [("locks", binding.get("locks"))]
                containers.extend(("targets/" + str(index) + "/execution/locks",
                                   target.get("execution", {}).get("locks"))
                                  for index, target in enumerate(binding.get("targets", [])))
                matching = [(path, locks) for path, locks in containers if isinstance(locks, dict)
                            and locks.get("provider") == provider_repository_state.PROVIDER
                            and locks.get("repository") == repository]
                if not matching:
                    continue
                factory_enrollment._validate_binding(binding)
                require(binding.get("repository") == repository and binding.get("orchestrator") == provider,
                        "authorization-binding-repository-mismatch")
                for path, locks in matching:
                    require(locks.get("state_ref") == provider_repository_state.STATE_REF
                            and locks.get("coordination_mode") == "single-writer"
                            and (locks.get("coordination_hash"), locks.get("revision")) == expected,
                            "authorization-binding-pin-changed")
                    result.append({"factory_id": factory_id, "provider": provider, "path": path})
                for target in binding["targets"]:
                    effective = {**binding, **target.get("execution", {})}
                    locks = effective.get("locks", {})
                    if locks.get("repository") != repository:
                        continue
                    scopes = _scopes(target["resource_group_ids"])
                    dependencies = _scopes(target.get("common_dependency_ids", []))
                    require(scopes and not set(scopes) & set(dependencies),
                            "authorization-binding-scope-invalid")
                    writer = enrollment["writers"].get(effective["writer_id"], {})
                    require(writer.get("kind") == provider and all(writer.get(key) == effective[key]
                            for key in ("repository", "shared_remote", "auth_namespace",
                                        "deployment_object_id", "runner")),
                            "authorization-binding-writer-changed")
                    enrolled_dependencies = set()
                    for scope in scopes:
                        value = enrollment["scopes"].get(scope, {})
                        require(value.get("target", {}).get("factory_id") == factory_id
                                and value.get("target", {}).get("scaleset_id") == target["scale_set_id"]
                                and value.get("scope_kind") == "aifactory-owned"
                                and value.get("writers") == [effective["writer_id"]],
                                "authorization-binding-scope-changed")
                        enrolled_dependencies.update(_scopes(value.get("common_dependencies")))
                    require(enrolled_dependencies == set(dependencies)
                            and all(scope in enrollment["scopes"] for scope in dependencies),
                            "authorization-binding-dependencies-changed")
        require(result, "authorization-binding-pins-required")
        return sorted(result, key=lambda row: (row["factory_id"], row["provider"], row["path"]))

    def _proposal(self, snapshot, operation_id, manifests, state, outer, canonical):
        require(snapshot["request"].get("scenario") in (4, 5, 6), "authorization-deletion-scenario-required")
        require(_semantic(snapshot["document"]) == _semantic(canonical["document"]),
                "authorization-canonical-proposal-changed")
        enrolled = state.get("enrollment")
        require(isinstance(enrolled, dict) and enrolled.get("schema") == 1
                and enrolled.get("protocol") == provider_repository_state.PROTOCOL
                and enrolled.get("enforcement") == "repository-exclusive-writer"
                and type(enrolled.get("revision")) is int and enrolled["revision"] >= 1
                and isinstance(enrolled.get("scopes"), dict) and isinstance(enrolled.get("writers"), dict),
                "authorization-enrollment-required")
        require(state.get("active") is None, "authorization-native-claim-active")
        require(manifests and isinstance(manifests, list), "authorization-manifests-required")
        factory_id = snapshot["factory"]["id"]
        selected_scales = {scale["id"]: scale for scale in snapshot["scales"]}
        require(len(manifests) == len(selected_scales)
                and {item["target"]["scaleset_id"] for item in manifests} == set(selected_scales),
                "authorization-selected-scales-mismatch")
        scopes, dependencies = set(), set()
        binding = canonical["document"].get("bindings", {}).get(factory_id, {}).get(snapshot["request"]["provider"])
        require(isinstance(binding, dict), "authorization-canonical-binding-required")
        for document in manifests:
            target, route, locks = document["target"], document["route"], document["locks"]
            require(target.get("factory_id") == factory_id and route.get("kind") == snapshot["request"]["provider"]
                    == self.provider.route["kind"] and route.get("repository") == state["repository"],
                    "authorization-manifest-binding-mismatch")
            scale = selected_scales[target["scaleset_id"]]
            expected = {"factory_id": factory_id, "scaleset_id": scale["id"],
                        "prefix": snapshot["factory"]["prefix"], "region": snapshot["factory"]["region"],
                        **{key: scale[key] for key in ("environment", "tenant_id", "subscription_id", "suffix")}}
            require({key: target.get(key) for key in TARGET_FIELDS} == expected,
                    "authorization-target-mismatch")
            targets = [row for row in binding["targets"] if row["scale_set_id"] == scale["id"]]
            require(len(targets) == 1, "authorization-exact-binding-target-required")
            physical = targets[0]
            effective = {**binding, **physical.get("execution", {})}
            owned, common = _scopes(locks["scopes"]), _scopes(locks["common_dependencies"])
            require(owned and owned == _scopes(physical["resource_group_ids"])
                    and common == _scopes(physical.get("common_dependency_ids", [])),
                    "authorization-exact-bound-scopes-required")
            require(all(route.get(key) == effective[key] for key in (
                "repository", "writer_id", "auth_namespace", "shared_remote", "runner", "ref"))
                and document["identity"].get("deployment_object_id") == effective["deployment_object_id"]
                and all(locks.get(key) == value for key, value in effective["locks"].items())
                and locks.get("provider") == provider_repository_state.PROVIDER,
                "authorization-binding-changed")
            view = SimpleNamespace(document=document, settings=locks)
            fl.BlobLocks.verify_enrollment_document(view, enrolled, provider_repository_state.PROTOCOL,
                                                    "repository-exclusive-writer")
            require(set(enrolled["writers"]) == {route["writer_id"]},
                    "authorization-single-writer-required")
            scopes.update(owned)
            dependencies.update(common)
        require(not scopes & dependencies, "authorization-dependency-scope-retained")
        # A scope needed by any enrolled target is retained, including unselected targets.
        retained = {scope for row in enrolled["scopes"].values()
                    for scope in _scopes(row.get("common_dependencies", []))}
        require(not scopes & retained, "authorization-common-scope-retained")
        policy_scopes = set(_scopes(outer["policy"]["factories"][factory_id]["scopes"]))
        require(scopes | dependencies <= policy_scopes, "authorization-outside-admission-policy")
        changed = sorted(scope for scope in scopes if enrolled["scopes"][scope].get("allow_delete") is not True)
        require(changed, "authorization-already-authorized")
        require(all(type(enrolled["scopes"][scope].get("allow_delete")) is bool for scope in scopes),
                "authorization-invalid-delete-enrollment")
        pins = self._pins(canonical["document"], state["repository"], enrolled)
        updated = copy.deepcopy(enrolled)
        updated["revision"] += 1
        for scope in changed:
            updated["scopes"][scope]["allow_delete"] = True
        document = copy.deepcopy(canonical["document"])
        for pin in pins:
            value = document["bindings"][pin["factory_id"]][pin["provider"]]
            for key in pin["path"].split("/"):
                value = value[int(key)] if isinstance(value, list) else value[key]
            value.update(coordination_hash=factory_enrollment.digest(updated), revision=updated["revision"])
        if "generation" in document:
            document["generation"] = str(uuid5(
                NAMESPACE_URL, CONTRACT + "/" + operation_id + "/" + digest(_semantic(document))))
        return {
            "contract": CONTRACT, "operation_id": operation_id, "factory_id": factory_id,
            "request": copy.deepcopy(snapshot["request"]),
            "selected_projects": copy.deepcopy(snapshot["projects"]),
            "selected_scales": copy.deepcopy(snapshot["scales"]),
            "repository": state["repository"], "scopes": sorted(scopes), "changed_scopes": changed,
            "common_dependencies": sorted(dependencies), "bindings": pins,
            "enrollment": {"before": copy.deepcopy(enrolled), "after": updated},
            "coordination_hash": {"from": factory_enrollment.digest(enrolled),
                                  "to": factory_enrollment.digest(updated)},
            "canonical": {"before": copy.deepcopy(canonical),
                          "after": {"document": document, "revision": digest(document)}},
            "policy": copy.deepcopy(outer["policy"]), "policy_hash": digest(outer["policy"]),
            "audit_record": AUDIT_PREFIX + factory_id + "/" + operation_id + ".json",
            "requires_reprepare": True, "azure_writes": False,
        }

    def _evidence(self, stage, record):
        """Invoke fresh native assertions, never accept a request-supplied proof.

        Return repository, factory_id, sorted scopes/common_dependencies, the five
        EVIDENCE_HASHES, inventory_complete=True, active_operations=[], observed_at
        (timezone-aware ISO timestamp). The adapter must raise on unsafe actual
        ownership, identity, permission, scope, inventory or dependency checks.
        Fingerprints/time describe those reads; missing or changed diagnostics warn.
        """
        observed = self.evidence(copy.deepcopy(stage), copy.deepcopy(record))
        require(isinstance(observed, dict), "authorization-live-evidence-required")
        expected = stage["deletion_authorization"]
        require(all(observed.get(key) == expected[key] for key in (
            "repository", "factory_id", "scopes", "common_dependencies"))
            and observed.get("inventory_complete") is True and observed.get("active_operations") == [],
            "authorization-live-evidence-incomplete")
        return copy.deepcopy(observed)

    @staticmethod
    def _evidence_warnings(observed, reviewed=None):
        warnings = []
        for key in EVIDENCE_HASHES:
            if not isinstance(observed.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", observed[key]):
                warnings.append("authorization-evidence-fingerprint-unavailable:" + key)
            elif reviewed is not None and observed[key] != reviewed.get(key):
                warnings.append("authorization-evidence-fingerprint-drift:" + key)
        try:
            stamp = datetime.fromisoformat(observed["observed_at"])
            fresh = stamp.tzinfo is not None and -30 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 300
        except (KeyError, TypeError, ValueError):
            fresh = False
        if not fresh:
            warnings.append("authorization-evidence-time-drift")
        return warnings

    def prepare(self, snapshot, operation_id, manifests, *, canonical_document=None):
        identifier(operation_id)
        _, state, outer, canonical = self._state(snapshot["factory"]["id"])
        if canonical_document is not None:
            require(_semantic(canonical_document) == _semantic(canonical["document"]),
                    "authorization-canonical-baseline-changed")
        documents = []
        for value in manifests:
            require(not any(key in value for key in ("deletion", "deployment")),
                    "authorization-coordination-only-manifests-required")
            document = copy.deepcopy(value)
            document.pop("operation", None)
            document.pop("manifest_hash", None)
            documents.append(document)
        proposal = self._proposal(snapshot, operation_id, documents, state, outer, canonical)
        stage = {"id": "authorize-deletion", "kind": "deletion-authorization",
                 "manifests": documents, "deletion_authorization": proposal}
        proposal["evidence"] = self._evidence(stage, None)
        proposal["warnings"] = self._evidence_warnings(proposal["evidence"])
        if snapshot["document"] != canonical["document"] or (
                canonical_document is not None and canonical_document != canonical["document"]):
            proposal["warnings"].append("authorization-canonical-generation-drift")
        return stage

    @staticmethod
    def _record(stage, record):
        require(record.get("plan", {}).get("stages") == [stage]
                and stage.get("kind") == "deletion-authorization", "authorization-only-plan-required")
        require(stage["deletion_authorization"].get("contract") == CONTRACT
                and stage["deletion_authorization"].get("operation_id") == identifier(record["operation_id"])
                and digest(record["snapshot"]) == record["snapshot_hash"]
                and digest(bound_plan(record)) == record["plan_hash"], "authorization-reviewed-plan-mismatch")
        change = record["plan"].get("configuration")
        if change is not None:
            baseline = change.get("baseline", {})
            require(change.get("contract") == "pipeline-configuration-v1"
                    and isinstance(baseline.get("document"), dict)
                    and baseline.get("revision") == digest(baseline["document"])
                    and _semantic(baseline["document"])
                    == _semantic(stage["deletion_authorization"]["canonical"]["before"]["document"])
                    and change.get("proposal") == record["snapshot"]["document"],
                    "authorization-configuration-baseline-mismatch")

    @staticmethod
    def _owned(outer, record, proposal, canonical):
        claim = record.get("admission_claim")
        require(isinstance(claim, dict) and outer.get("claim") == claim
                and claim.get("protocol") == lifecycle_admission.PROTOCOL
                and claim.get("route") == "pipeline" and claim.get("operation_id") == record["operation_id"]
                and claim.get("factory_id") == proposal["factory_id"]
                and claim.get("review_digest") == record["plan_hash"]
                and claim.get("configuration_revision") == canonical["revision"]
                and claim.get("scopes") == _scopes(outer["policy"]["factories"][proposal["factory_id"]]["scopes"]),
                "authorization-owned-outer-claim-required")

    def execute(self, stage, record):
        self._record(stage, record)
        proposal = stage["deletion_authorization"]
        _, state, _, _ = self._state(proposal["factory_id"])
        if proposal["audit_record"] in state["records"]:
            return self.observe(stage, record)
        require(record["operation_id"] not in self.attempted_operations
                and not getattr(self.provider, "write_failed", False)
                and record.get("status") == "running" and len(record.get("stages", [])) == 1
                and record["stages"][0].get("id") == stage["id"]
                and record["stages"][0].get("status") == "running",
                "authorization-reconciliation-required")
        approval = self.review.verify(record)
        origin = record["plan"].get("origin", {})
        require(isinstance(approval, dict) and origin.get("provider") in ("gha", "ado")
                and all(approval.get(key) == origin.get(key) and origin.get(key) is not None
                        for key in ("provider", "run_id", "attempt")),
                "authorization-protected-review-required")
        self.admission.assert_owned(record)
        observed = self._evidence(stage, record)
        warnings = [*proposal["warnings"], *self._evidence_warnings(observed, proposal["evidence"])]
        self.admission.assert_owned(record)
        head, state, outer, canonical = self._state(proposal["factory_id"])
        self._owned(outer, record, proposal, canonical)
        expected = self._proposal(record["snapshot"], record["operation_id"], stage["manifests"],
                                  state, outer, canonical)
        reviewed = {key: value for key, value in proposal.items() if key not in ("evidence", "warnings")}
        require(_semantic(expected["canonical"]["before"]["document"])
                == _semantic(reviewed["canonical"]["before"]["document"]),
                "authorization-canonical-proposal-changed")
        if canonical != reviewed["canonical"]["before"] or (
                record["plan"].get("configuration", {}).get("baseline", canonical) != canonical):
            warnings.append("authorization-canonical-generation-drift")
        expected["canonical"]["before"] = copy.deepcopy(reviewed["canonical"]["before"])
        require(expected == reviewed,
                "authorization-reviewed-state-changed")
        updated = copy.deepcopy(state)
        updated["enrollment"] = copy.deepcopy(proposal["enrollment"]["after"])
        updated["records"][lifecycle_admission.RECORD]["canonical"] = {
            factory_id: copy.deepcopy(proposal["canonical"]["after"]) for factory_id in outer["canonical"]}
        audit = {"schema": 1, "contract": CONTRACT, "operation_id": record["operation_id"],
                 "factory_id": proposal["factory_id"], "plan_hash": record["plan_hash"],
                 "stage_hash": digest(stage), "claim": copy.deepcopy(record["admission_claim"]),
                 "previous_head": head, "approval": copy.deepcopy(approval), "evidence": observed,
                 "authorized_at": now(), "scopes": proposal["changed_scopes"],
                 "coordination_hash": proposal["coordination_hash"],
                 "canonical_revision": proposal["canonical"]["after"]["revision"],
                 "warnings": sorted(set(warnings))}
        updated["records"][proposal["audit_record"]] = audit
        self.attempted_operations.add(record["operation_id"])
        try:
            self.provider.replace(head, updated)
        except Exception:
            # A missing response does not imply a failed commit. Never repeat the CAS.
            return self.observe(stage, record)
        return self.observe(stage, record)

    def observe(self, stage, record):
        self._record(stage, record)
        proposal = stage["deletion_authorization"]
        head, state, outer, canonical = self._state(proposal["factory_id"])
        audit = state["records"].get(proposal["audit_record"])
        if audit is None:
            return {"status": "reconciliation-required", "verified": False,
                    "audit_record": proposal["audit_record"], "requires_reprepare": True}
        require(isinstance(audit, dict) and audit.get("contract") == CONTRACT
                and audit.get("operation_id") == record["operation_id"]
                and audit.get("plan_hash") == record["plan_hash"] and audit.get("stage_hash") == digest(stage)
                and audit.get("claim") == record.get("admission_claim"),
                "authorization-audit-binding-mismatch")
        claim = record["admission_claim"]
        require(outer.get("claim") == claim or outer.get("claim") is None and any(
            value.get("claim") == claim for value in outer.get("history", {}).values()),
            "authorization-claim-reconciliation-required")
        require(state.get("active") is None and state["enrollment"] == proposal["enrollment"]["after"]
                and _semantic(canonical["document"]) == _semantic(proposal["canonical"]["after"]["document"])
                and outer["policy"] == proposal["policy"]
                and audit.get("coordination_hash") == proposal["coordination_hash"]
                and audit.get("canonical_revision") == proposal["canonical"]["after"]["revision"],
                "authorization-live-result-changed")
        warnings = list(audit.get("warnings", []))
        if canonical != proposal["canonical"]["after"]:
            warnings.append("authorization-canonical-generation-drift")
        return {"status": "succeeded", "verified": True, "audit_record": proposal["audit_record"],
                "provider_head": head, "coordination_hash": proposal["coordination_hash"]["to"],
                "canonical_revision": canonical["revision"], "canonical": copy.deepcopy(canonical),
                "scopes": proposal["changed_scopes"],
                "requires_reprepare": True, "azure_writes": False, "warnings": sorted(set(warnings))}
