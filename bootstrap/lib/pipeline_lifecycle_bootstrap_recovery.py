"""Reviewed enrollment-claim retirement; never replays provisioning effects."""

import copy
from uuid import UUID, uuid5

import lifecycle_admission
from pipeline_lifecycle import bound_plan, digest, identifier, now, require
from pipeline_lifecycle_reconciliation import NativeReconciliationEvidence, RetainedClaimReconciliation, _not_found


KIND = "bootstrap-reconciliation"
ATTEMPTS = "pipeline-bootstrap-attempt/"
AUDITS = "pipeline-bootstrap-recovery/"


def capture_attempt(provider, stage, record):
    head, state = provider.read()
    claim = state.get("active")
    if claim is None:
        return
    require(claim.get("kind") == "enrollment" and set(claim) == {"kind", "id", "plan_hash"},
            "bootstrap-native-enrollment-claim-required")
    identifier(claim["id"])
    require(state["records"][lifecycle_admission.RECORD]["claim"] == record["admission_claim"],
            "bootstrap-attempt-outer-claim-changed")
    key = ATTEMPTS + record["operation_id"] + ".json"
    evidence = {"schema": 1, "operation_id": record["operation_id"], "plan_hash": record["plan_hash"],
                "stage_hash": digest(stage), "native_claim": copy.deepcopy(claim)}
    previous = state["records"].get(key)
    if previous is not None:
        require(previous == evidence, "bootstrap-attempt-changed")
        return
    state["records"][key] = evidence
    provider.replace(head, state)


class BootstrapReconciliation:
    def __init__(self, provider, bootstrap):
        self.provider, self.bootstrap, self.review = provider, bootstrap, bootstrap.review
        self.attempted = set()

    def _state(self, factory_id):
        return RetainedClaimReconciliation._state(self, factory_id)

    @staticmethod
    def _integrity(record):
        require(record.get("schema") == 1 and digest(record["snapshot"]) == record["snapshot_hash"]
                and digest(bound_plan(record)) == record["plan_hash"], "bootstrap-recovery-record-changed")

    def _prior(self, state, operation_id):
        prior = state["records"].get("pipeline-lifecycle/" + identifier(operation_id) + ".json")
        require(isinstance(prior, dict), "bootstrap-recovery-prior-required")
        self._integrity(prior)
        stages = prior["plan"]["stages"]
        require(len(stages) == 1 and stages[0]["kind"] == "bootstrap-enrollment"
                and prior["status"] in ("running", "reconciliation-required", "cancel-pending", "continuation-required"),
                "bootstrap-recovery-prior-stage-required")
        attempt = state["records"].get(ATTEMPTS + operation_id + ".json")
        require(isinstance(attempt, dict) and attempt.get("operation_id") == operation_id
                and attempt.get("plan_hash") == prior["plan_hash"]
                and attempt.get("stage_hash") == digest(stages[0])
                and attempt.get("native_claim", {}).get("kind") == "enrollment",
                "bootstrap-recovery-durable-attempt-required")
        return prior, stages[0], attempt

    def _evidence(self, prior, stage, active):
        from pipeline_lifecycle_bootstrap import enrollment
        request = self.bootstrap._validated(stage, prior)
        native = self.bootstrap._native_request(request)
        cloud = self.bootstrap._cloud(native, self.review.origin(prior["snapshot"]))
        parent = NativeReconciliationEvidence._terminal(cloud, request["route"], prior["plan"]["origin"])
        self.bootstrap._active_runs(cloud)
        previous = getattr(cloud, "single_writer_enrollment_claim", None)
        cloud.single_writer_enrollment_claim = copy.deepcopy(active)
        try:
            state = enrollment._snapshot(native, cloud)
        finally:
            if previous is None:
                del cloud.single_writer_enrollment_claim
            else:
                cloud.single_writer_enrollment_claim = previous
        require(not state["blockers"] and state["identity"] == stage["native_review"]["identity"],
                "bootstrap-recovery-identity-or-authority-changed")
        self.bootstrap._retained_grants(request, state)
        groups = self.bootstrap._empty_groups(request, cloud, prior["snapshot"])
        inventories = {}
        for scope in request["scopes"]:
            group = state["groups"][scope]
            if group is None:
                status, _, body = cloud.arm("GET", scope, enrollment.RG_API, allowed=(200, 404))
                require(status == 404, "bootstrap-recovery-group-absence-changed")
                _not_found(body, ("ResourceGroupNotFound",), "bootstrap-recovery-group-absence-unverified")
                continue
            body = group["body"]
            require(str(body.get("id", "")).lower() == scope
                    and body.get("properties", {}).get("provisioningState") in (None, "Succeeded"),
                    "bootstrap-recovery-group-not-terminal")
            deployments = cloud.collection(scope + "/providers/Microsoft.Resources/deployments", "2022-09-01")
            require(all(row.get("properties", {}).get("provisioningState") in ("Succeeded", "Failed", "Canceled")
                        for row in deployments), "bootstrap-recovery-deployment-active")
            if any(row["id"] == scope for row in stage["empty_groups"]["effects"]):
                resources = cloud.collection(scope + "/resources", "2021-04-01")
                require(resources == [], "bootstrap-recovery-unreviewed-group-resources")
            inventories[scope] = copy.deepcopy(deployments)
        state.pop("repository_head", None)
        state.pop("repository_state", None)
        if state.get("enrollment"):
            state["enrollment"]["etag"] = None
        return {"parent": parent, "native": state, "groups": groups, "deployments": inventories}

    def prepare(self, snapshot, previous, operation_id):
        _, state, outer, canonical = self._state(snapshot["factory"]["id"])
        prior, stage, attempt = self._prior(state, previous["operation_id"])
        require(prior == previous and prior["snapshot"] == snapshot, "bootstrap-recovery-prior-changed")
        claim = prior.get("admission_claim")
        require(isinstance(claim, dict) and outer["claim"] == claim
                and claim.get("operation_id") == prior["operation_id"]
                and claim.get("review_digest") == prior["plan_hash"]
                and claim.get("protocol") == lifecycle_admission.PROTOCOL
                and claim.get("route") == "pipeline"
                and state["active"] in (None, attempt["native_claim"]),
                "bootstrap-recovery-exact-claims-required")
        origin = self.review.origin(snapshot)
        require(origin["run_id"] != prior["plan"]["origin"]["run_id"]
                and all(origin[key] == prior["plan"]["origin"][key] for key in ("provider", "repository", "ref", "commit")),
                "bootstrap-recovery-new-provider-review-required")
        proposal = {"operation_id": identifier(operation_id), "factory_id": snapshot["factory"]["id"],
                    "origin": origin, "prior_operation_id": prior["operation_id"], "prior_plan_hash": prior["plan_hash"],
                    "prior_claim": claim, "native_claim": state["active"], "attempt": attempt,
                    "enrollment": state["enrollment"], "canonical": canonical, "policy": outer["policy"],
                    "scopes": stage["enrollment"]["scopes"], "requires_reprepare": True,
                    "audit_record": AUDITS + operation_id + ".json",
                    "evidence": self._evidence(prior, stage, state["active"])}
        return {"id": "reconcile-bootstrap", "kind": KIND, "reconciliation": proposal}

    def _validate(self, record):
        self._integrity(record)
        stage = record["plan"]["stages"][0]
        proposal = stage["reconciliation"]
        require(len(record["plan"]["stages"]) == 1 and stage["kind"] == KIND
                and proposal["operation_id"] == record["operation_id"]
                and record["plan"]["origin"] == proposal["origin"]
                and record["plan"].get("recovery_of") == {
                    "operation_id": proposal["prior_operation_id"], "plan_hash": proposal["prior_plan_hash"]},
                "bootstrap-recovery-review-binding-mismatch")
        return stage, proposal

    def acquire(self, record):
        stage, proposal = self._validate(record)
        approval = self.review.verify(record)
        require(all(approval.get(key) == proposal["origin"][key] for key in ("provider", "run_id", "attempt")),
                "bootstrap-recovery-new-protected-review-required")
        head, state, outer, canonical = self._state(proposal["factory_id"])
        audit = state["records"].get(proposal["audit_record"])
        if audit is not None:
            adopted = {**record, "admission_claim": audit["claim"]}
            require(outer["claim"] == audit["claim"], "bootstrap-recovery-claim-not-owned")
            self.observe(stage, adopted)
            return copy.deepcopy(audit["claim"])
        require(record["operation_id"] not in self.attempted, "bootstrap-recovery-observe-before-retry")
        prior, native_stage, attempt = self._prior(state, proposal["prior_operation_id"])
        require(prior["plan_hash"] == proposal["prior_plan_hash"] and attempt == proposal["attempt"]
                and outer["claim"] == proposal["prior_claim"] and outer["policy"] == proposal["policy"]
                and canonical == proposal["canonical"] and state["enrollment"] == proposal["enrollment"]
                and state["active"] == proposal["native_claim"],
                "bootstrap-recovery-authority-changed")
        evidence = self._evidence(prior, native_stage, state["active"])
        require(evidence == proposal["evidence"], "bootstrap-recovery-live-state-changed")
        origin = proposal["origin"]
        claim = {"protocol": lifecycle_admission.PROTOCOL, "id": str(uuid5(UUID(record["operation_id"]), KIND)),
                 "factory_id": proposal["factory_id"], "operation_id": record["operation_id"], "route": "pipeline",
                 "operation": "cleanup", "review_digest": record["plan_hash"],
                 "configuration_revision": canonical["revision"],
                 "scopes": proposal["policy"]["factories"][proposal["factory_id"]]["scopes"],
                 "identity": {"subject": origin["provider"] + ":" + origin["run_id"] + ":" + str(origin["attempt"]),
                              "run_id": origin["run_id"], "repository": self.provider.route["repository"],
                              "route": "pipeline", "operation_id": record["operation_id"],
                              "review_digest": record["plan_hash"], "authorization_id": digest(approval)}}
        retired = {"claim": copy.deepcopy(proposal["prior_claim"]), "observation": {
            "run_id": prior["plan"]["origin"]["run_id"], "repository": self.provider.route["repository"],
            "terminal": True, "inventory_complete": True, "active_operations": [], "evidence_id": digest(evidence),
            "replacement_operation_id": record["operation_id"], "status": "reconciled-not-completed"}}
        outer["claim"] = copy.deepcopy(claim)
        outer["history"][proposal["prior_claim"]["id"]] = retired
        state["active"] = None
        state["records"][proposal["audit_record"]] = {
            "operation_id": record["operation_id"], "plan_hash": record["plan_hash"], "stage_hash": digest(stage),
            "claim": copy.deepcopy(claim), "retired": retired, "completed_at": now()}
        state["records"][lifecycle_admission.RECORD] = outer
        self.attempted.add(record["operation_id"])
        self.provider.replace(head, state)
        self.observe(stage, {**record, "admission_claim": claim})
        return claim

    def execute(self, stage, record):
        return self.observe(stage, record)

    def observe(self, stage, record):
        expected, proposal = self._validate(record)
        require(stage == expected, "bootstrap-recovery-stage-changed")
        _, state, outer, canonical = self._state(proposal["factory_id"])
        audit = state["records"].get(proposal["audit_record"])
        require(isinstance(audit, dict) and audit.get("plan_hash") == record["plan_hash"]
                and audit.get("stage_hash") == digest(stage) and audit.get("claim") == record["admission_claim"]
                and state["active"] is None and state["enrollment"] == proposal["enrollment"]
                and canonical == proposal["canonical"] and outer["policy"] == proposal["policy"]
                and outer["history"].get(proposal["prior_claim"]["id"]) == audit["retired"]
                and (outer["claim"] == audit["claim"] or outer["claim"] is None
                     and outer["history"].get(audit["claim"]["id"], {}).get("claim") == audit["claim"]),
                "bootstrap-recovery-durable-result-changed")
        prior, native_stage, attempt = self._prior(state, proposal["prior_operation_id"])
        require(attempt == proposal["attempt"] and prior["plan_hash"] == proposal["prior_plan_hash"]
                and self._evidence(prior, native_stage, None) == proposal["evidence"],
                "bootstrap-recovery-live-state-changed")
        return {"status": "succeeded", "verified": True, "requires_reprepare": True, "runtime_ready": False,
                "canonical": canonical, "audit_record": proposal["audit_record"], "azure_writes": False}
