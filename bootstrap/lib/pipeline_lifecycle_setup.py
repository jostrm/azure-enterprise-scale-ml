"""Protected initial admission installation, independent of the Factory API.

Platform administrators must first fence older writers and opt upgraded API hosts
into the shared coordinator. That external trust prerequisite cannot be proven by
an input flag. The flag requests this separate native protected review; only the
authenticated review and fresh installed evidence adapter authorize the CAS.
"""

import copy
from uuid import UUID, uuid5

import lifecycle_admission as shared
from pipeline_lifecycle import bound_plan, digest, identifier, require


CONTRACT = "pipeline-admission-installation-v1"
GOVERNANCE = "exclusive-upgraded-writers-v1"
AUDIT_PREFIX = "pipeline-admission-installations/"


class AdmissionSetup:
    def __init__(self, provider, *, review, evidence):
        require(callable(evidence), "admission-install-live-adapter-required")
        self.provider, self.review, self.evidence = provider, review, evidence

    def needed(self):
        _, state = self.provider.read()
        return shared.RECORD not in (state or {}).get("records", {})

    def _state(self, factory_id, *, allow_installed=False):
        head, state = self.provider.read()
        state = state if state is not None else self.provider.empty()
        require(state.get("repository") == self.provider.route["repository"],
                "admission-install-repository-mismatch")
        require(state.get("active") is None, "admission-install-native-claim-active")
        require(allow_installed or shared.RECORD not in state["records"], "admission-already-installed")
        enrollment = state.get("enrollment")
        if enrollment:
            require(all(row.get("target", {}).get("factory_id") == factory_id
                        and row.get("scope_kind") == "aifactory-owned"
                        and row.get("common_dependencies") == []
                        for row in enrollment.get("scopes", {}).values()),
                    "admission-install-foreign-or-shared-enrollment")
        return head, state

    def _evidence(self, snapshot, scopes):
        self.provider.private()
        observed = self.evidence(copy.deepcopy(snapshot), copy.deepcopy(scopes))
        require(isinstance(observed, dict) and observed.get("verified") is True
                and observed.get("factory_id") == snapshot["factory"]["id"]
                and observed.get("repository") == self.provider.route["repository"]
                and observed.get("scopes") == scopes and observed.get("active_operations") == [],
                "admission-install-live-evidence-unverified")
        return copy.deepcopy(observed)

    def prepare(self, snapshot, operation_id, scopes):
        identifier(operation_id)
        require(snapshot["binding"].get("admission") == {"writer_governance": GOVERNANCE},
                "explicit-writer-governance-review-required")
        require(len(snapshot["document"]["factories"]) == 1, "admission-install-single-factory-required")
        scopes = shared._scopes(scopes)
        _, state = self._state(snapshot["factory"]["id"])
        if state.get("enrollment"):
            require(set(state["enrollment"]["scopes"]) <= set(scopes), "admission-install-complete-scope-required")
        observed = self._evidence(snapshot, scopes)
        policy = {"repository": state["repository"], "factories": {snapshot["factory"]["id"]: {
            "all_writers": shared.PROTOCOL, "shared_scopes": [], "operations": sorted(shared.OPERATIONS),
            "routes": ["api", "pipeline"], "scopes": scopes}}}
        stage = {"id": "install-admission", "kind": "admission-installation",
                 "setup": {"contract": CONTRACT, "policy": policy, "enrollment": state.get("enrollment"),
                           "evidence": observed, "audit_record": AUDIT_PREFIX + operation_id + ".json"}}
        return {"stages": [stage], "origin": self.review.origin(snapshot), "continuation_required": True,
                "review": {"kind": "install-cross-route-admission", "policy": policy,
                           "required_external_governance": [
                               "Upgrade and opt in every API writer before approval.",
                               "Fence old writer credentials and prohibit bypass operations.",
                               "Keep runner, execution identity, seeding vault and provider evidence outside teardown."],
                           "next": "Freshly prepare and approve the selected lifecycle operation."}}

    @staticmethod
    def _stage(record):
        stages = record["plan"]["stages"]
        require(len(stages) == 1 and stages[0]["kind"] == "admission-installation"
                and digest(record["snapshot"]) == record["snapshot_hash"]
                and digest(bound_plan(record)) == record["plan_hash"], "admission-install-review-binding-mismatch")
        return stages[0]

    def acquire(self, record):
        stage = self._stage(record)
        setup = stage["setup"]
        factory = record["snapshot"]["factory"]["id"]
        head, state = self._state(factory, allow_installed=True)
        installed = state["records"].get(shared.RECORD)
        if installed is not None:
            audit = state["records"].get(setup["audit_record"], {})
            claim = audit.get("claim")
            require(audit.get("plan_hash") == record["plan_hash"] and isinstance(claim, dict)
                    and claim.get("operation_id") == record["operation_id"]
                    and installed.get("claim") == claim, "admission-installation-conflict")
            self.review.verify(record)
            self._evidence(record["snapshot"], claim["scopes"])
            return copy.deepcopy(claim)
        require(state.get("enrollment") == setup["enrollment"], "admission-install-enrollment-changed")
        expected = self.prepare(record["snapshot"], record["operation_id"],
                                setup["policy"]["factories"][factory]["scopes"])
        require(expected["stages"][0]["setup"]["policy"] == setup["policy"]
                and expected["origin"] == record["plan"]["origin"], "admission-install-policy-changed")
        approval = self.review.verify(record)
        origin = record["plan"]["origin"]
        require(isinstance(approval, dict) and all(approval.get(key) == origin.get(key)
                and origin.get(key) is not None for key in ("provider", "run_id", "attempt")),
                "admission-install-native-review-required")
        policy = setup["policy"]
        claim = {"factory_id": factory, "operation_id": record["operation_id"], "route": "pipeline",
                 "operation": "bootstrap", "scopes": policy["factories"][factory]["scopes"],
                 "configuration_revision": digest(record["snapshot"]["document"]),
                 "review_digest": record["plan_hash"], "protocol": shared.PROTOCOL,
                 "id": str(uuid5(UUID(record["operation_id"]), CONTRACT)),
                 "identity": {"subject": origin["provider"] + ":" + origin["run_id"],
                              "run_id": origin["run_id"], "repository": state["repository"], "route": "pipeline",
                              "operation_id": record["operation_id"], "review_digest": record["plan_hash"],
                              "authorization_id": digest(approval)}}
        updated = copy.deepcopy(state)
        outer = shared.new_record(policy, {factory: record["snapshot"]["document"]})
        outer["claim"] = claim
        updated["records"][shared.RECORD] = outer
        updated["records"][setup["audit_record"]] = {
            "contract": CONTRACT, "plan_hash": record["plan_hash"], "claim": claim, "approval": approval,
            "evidence": expected["stages"][0]["setup"]["evidence"]}
        self.provider.replace(head, updated)
        return copy.deepcopy(claim)

    def execute(self, stage, record):
        require(stage == self._stage(record), "admission-install-stage-mismatch")
        return self.observe(stage, record)

    def observe(self, stage, record):
        require(stage == self._stage(record), "admission-install-stage-mismatch")
        _, state = self._state(record["snapshot"]["factory"]["id"], allow_installed=True)
        setup = stage["setup"]
        outer = state["records"].get(shared.RECORD, {})
        audit = state["records"].get(setup["audit_record"], {})
        claim = record.get("admission_claim")
        require(isinstance(claim, dict) and audit.get("claim") == claim
                and audit.get("plan_hash") == record["plan_hash"] and outer.get("policy") == setup["policy"]
                and (outer.get("claim") == claim or outer.get("claim") is None and
                     any(row.get("claim") == claim for row in outer.get("history", {}).values())),
                "admission-install-result-unverified")
        self._evidence(record["snapshot"], claim["scopes"])
        canonical = outer["canonical"][record["snapshot"]["factory"]["id"]]
        require(canonical["document"] == record["snapshot"]["document"]
                and canonical["revision"] == digest(canonical["document"]), "admission-install-canonical-changed")
        return {"status": "succeeded", "verified": True, "requires_reprepare": True,
                "canonical": copy.deepcopy(canonical), "audit_record": setup["audit_record"], "azure_writes": False}
