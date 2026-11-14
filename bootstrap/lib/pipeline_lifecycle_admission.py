"""Pipeline adapter to the shared cross-route admission protocol.

Enrollment is deliberately not automatic. An existing incomplete writer policy
cannot be upgraded by the pipeline that wants to enter it.
"""

import copy
from urllib.parse import quote, unquote, urlsplit

import lifecycle_admission
from pipeline_lifecycle import digest, require, verified_outcome


class NativeAdmission:
    def __init__(self, provider, review, executor, *, setup=None, reconciliation=None, bootstrap_reconciliation=None):
        self.provider, self.review, self.executor = provider, review, executor
        self.guard = lifecycle_admission.Admission(provider, self)
        self.record = None
        self._finalizing = False
        self._scope_extension = []
        self.setup = setup
        self.reconciliation = reconciliation
        self.bootstrap_reconciliation = bootstrap_reconciliation

    def _state(self):
        _, state = self.provider.read()
        require(isinstance(state, dict), "cross-route-admission-not-enrolled")
        outer = state["records"].get(lifecycle_admission.RECORD)
        require(isinstance(outer, dict), "cross-route-admission-not-enrolled")
        return state, outer

    def prepare(self, snapshot):
        from pipeline_lifecycle_configuration import prepare_change
        if self.setup is not None and self.setup.needed():
            return prepare_change(snapshot, {"revision": digest(snapshot["document"]), "document": snapshot["document"]})
        return prepare_change(snapshot, self.guard.canonical_configuration(snapshot["factory"]["id"]))

    def prepare_recovery(self, snapshot, prior, plan):
        from pipeline_lifecycle_configuration import prepare_recovery_change
        canonical = self.guard.canonical_configuration(snapshot["factory"]["id"])
        return prepare_recovery_change(snapshot, prior, plan, canonical)

    def acquire(self, record):
        self.record = copy.deepcopy(record)
        if record["plan"]["stages"][0].get("kind") == "bootstrap-reconciliation":
            require(self.bootstrap_reconciliation is not None, "bootstrap-reconciliation-adapter-required")
            return self.bootstrap_reconciliation.acquire(record)
        if record["plan"]["stages"][0].get("kind") == "admission-installation":
            require(self.setup is not None, "admission-installation-adapter-required")
            return self.setup.acquire(record)
        if record["plan"]["stages"][0].get("kind") == "retained-claim-reconciliation":
            require(self.reconciliation is not None, "reconciliation-adapter-required")
            return self.reconciliation.acquire(record)
        factory = record["snapshot"]["factory"]["id"]
        canonical = self.guard.canonical_configuration(factory)
        change = record["plan"].get("configuration")
        if change is not None:
            from pipeline_lifecycle_configuration import assert_baseline, prepare_change
            require(change == prepare_change(record["snapshot"], change["baseline"]), "configuration-review-changed")
            assert_baseline(change, canonical)
        else:
            require(canonical["document"] == record["snapshot"]["document"], "canonical-configuration-changed")
        _, outer = self._state()
        policy = outer["policy"]["factories"][factory]
        selected = {scope.lower() for stage in record["plan"]["stages"] for document in stage.get("manifests", [])
                    for scope in document["locks"]["scopes"]}
        dependencies = {scope.lower() for stage in record["plan"]["stages"] for document in stage.get("manifests", [])
                        for scope in document["locks"]["common_dependencies"]}
        require(dependencies <= {scope.lower() for scope in policy["scopes"]},
                "dependency-outside-admission-policy")
        selected.update(scope.lower() for stage in record["plan"]["stages"] if stage.get("kind") == "bootstrap-enrollment"
                        for scope in stage["enrollment"]["scopes"])
        self._scope_extension = sorted(selected - {scope.lower() for scope in policy["scopes"]})
        require(not self._scope_extension or change is not None and record["snapshot"]["request"]["scenario"] < 4,
                "operation-outside-admission-policy")
        return self.guard.acquire({
            "factory_id": factory, "operation_id": record["operation_id"], "route": "pipeline",
            "operation": "delete" if record["snapshot"]["request"]["scenario"] >= 4 else "execute",
            "scopes": policy["scopes"], "configuration_revision": canonical["revision"],
            "review_digest": record["plan_hash"]}, scope_extension=self._scope_extension)

    def persist(self, record):
        """Publish only the verified outcome; a fresh process can recover a lost CAS response."""
        from pipeline_lifecycle_configuration import assert_baseline, completed_document
        require("configuration" in record["plan"], "configuration-review-required")
        self.assert_owned(record)
        change = record["plan"]["configuration"]
        current = self.guard.canonical_configuration(record["snapshot"]["factory"]["id"])
        stages = record["plan"]["stages"]
        if len(stages) == 1 and stages[0].get("kind") in (
                "deletion-authorization", "admission-installation", "retained-claim-reconciliation", "bootstrap-reconciliation"):
            receipt = self.executor.observe(stages[0], record)
            details = stages[0].get("deletion_authorization", stages[0].get("setup", stages[0].get("reconciliation")))
            require(receipt.get("verified") is True and receipt.get("status") == "succeeded"
                    and receipt.get("canonical") == current
                    and receipt.get("audit_record") == details["audit_record"],
                    "configuration-authorization-result-unverified")
            if stages[0].get("kind") != "retained-claim-reconciliation" or receipt.get("completed_outcome") is not True:
                return current
            require(details.get("completed_outcome") is True
                    and receipt.get("requires_reprepare") is details["requires_reprepare"],
                    "configuration-reconciliation-outcome-mismatch")
            observed = copy.deepcopy(record)
            observed["stages"] = [{"id": stages[0]["id"], "status": receipt["status"], "observation": receipt}]
            document = completed_document(observed)
        else:
            document = completed_document(record)
        if current["document"] == document:
            return current
        assert_baseline(change, current)
        return self.guard.commit_configuration(self._saved_claim(record), current["revision"], document)

    def authenticate(self, request, policy):
        require(self.record is not None and self.record["operation_id"] == request["operation_id"]
                and self.record["plan_hash"] == request["review_digest"],
                "admission-operation-binding-mismatch")
        verified = self.review.verify(self.record)
        return {"subject": verified["provider"] + ":" + verified["run_id"] + ":" + str(verified["attempt"]),
                "run_id": verified["run_id"], "repository": self.provider.route["repository"],
                "route": "pipeline", "operation_id": request["operation_id"],
                "review_digest": self.record["plan_hash"], "authorization_id": digest(verified),
                **({"scope_extension": self._scope_extension} if self._scope_extension else {})}

    def assert_owned(self, record):
        _, outer = self._state()
        claim = self._saved_claim(record)
        require(outer["claim"] == claim, "admission-claim-binding-mismatch")
        self.guard.assert_owned(claim)

    @staticmethod
    def _saved_claim(record):
        claim = record.get("admission_claim")
        require(isinstance(claim, dict) and claim.get("protocol") == lifecycle_admission.PROTOCOL
                and claim.get("operation_id") == record["operation_id"] and claim.get("route") == "pipeline"
                and claim.get("review_digest") == record["plan_hash"], "admission-saved-claim-required")
        return claim

    def _terminal(self, record):
        if self._finalizing:
            proof = self.review.verify_finalizer(record)
            require(proof.get("operation_id") == record["operation_id"]
                    and proof.get("plan_hash") == record["plan_hash"],
                    "admission-finalizer-binding-mismatch")
            return True
        origin = record["plan"]["origin"]
        run_id = origin["run_id"]
        if origin["provider"] == "gha":
            run = self.review.get("repos/" + origin["repository"] + "/actions/runs/" + run_id)
            require(str(run.get("id")) == run_id and run.get("head_sha") == origin["commit"]
                    and run.get("run_attempt") == origin["attempt"], "admission-provider-run-changed")
            return run.get("status") == "completed" and run.get("conclusion") == "success"
        repository = self.provider.route["repository"]
        org, project, _, _ = unquote(urlsplit(repository).path).strip("/").split("/")
        run = self.review.get("https://dev.azure.com/" + quote(org) + "/" + quote(project)
                              + "/_apis/build/builds/" + run_id + "?api-version=7.1")
        require(str(run.get("id")) == run_id and run.get("sourceVersion") == origin["commit"],
                "admission-provider-run-changed")
        return run.get("status") == "completed" and run.get("result") == "succeeded"

    def release(self, record):
        self.record = copy.deepcopy(record)
        _, outer = self._state()
        claim = self._saved_claim(record)
        if outer["claim"] is None:
            require(any(value["claim"] == claim for value in outer["history"].values()),
                    "admission-claim-not-found")
            return {"status": "released"}

        require(outer["claim"] == claim, "admission-claim-binding-mismatch")
        # A protected job cannot truthfully claim its enclosing provider run is
        # terminal. Keep the claim for a separately authenticated observation.
        if not self._terminal(record):
            return {"status": "provider-completion-pending"}
        self.guard.complete(claim, {"operation_id": record["operation_id"], "plan_hash": record["plan_hash"]})
        return {"status": "released"}

    def finalize(self, record):
        self.record = copy.deepcopy(record)
        # A native finalizer proves the mutating job ended within this still-live workflow.
        self.review.verify_finalizer(record)
        self._finalizing = True
        try:
            return self.release(record)
        finally:
            self._finalizing = False

    def observe(self, claim, evidence):
        require(self.record is not None and self.record["operation_id"] == claim["operation_id"]
                and evidence == {"operation_id": claim["operation_id"], "plan_hash": self.record["plan_hash"]},
                "admission-evidence-binding-mismatch")
        require(self._terminal(self.record), "admission-provider-not-terminal")
        observations = [self.executor.observe(stage, self.record) for stage in self.record["plan"]["stages"]]
        require(all(verified_outcome(row) for row in observations),
                "admission-native-outcome-unverified")
        return {"run_id": claim["identity"]["run_id"], "repository": self.provider.route["repository"],
                "terminal": True, "inventory_complete": True, "active_operations": [],
                "evidence_id": digest(observations)}
