"""Opt-in whole-operation admission above the existing inner lifecycle claim.

The policy and canonical configuration live in ProviderState.records, preserving
the pinned provider schema and the inner runtime's ``active`` semantics. The
authority is installed trusted code performing authenticated provider queries,
not a boolean, a local JSON proof or a request-specified module. There is no
expiry, force unlock, automatic write retry, or release on context exit.

Version 1 serializes an entire enrolled repository. Cross-repository/shared-hub
writers are unsupported, not approximated by a repository-local claim. Enabling
requires every writer to participate, including configuration and cleanup.
"""

import copy
import hashlib
import json
import re
from uuid import uuid4


PROTOCOL = "aifactory-lifecycle-admission-v1"
RECORD = "lifecycle_admission_v1"
OPERATIONS = frozenset({"bootstrap", "configuration", "enrollment", "execute", "delete", "cleanup"})


class AdmissionError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise AdmissionError("lifecycle-admission-" + code)


def revision(document):
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def new_record(policy, configurations):
    """Seed one whole-catalog snapshot shared by every factory in this repository.

    Only a separately reviewed provisioning CAS may install this record. The
    factory keys identify admitted selectors, not independent register copies.
    """
    require(isinstance(configurations, dict)
            and all(isinstance(value, dict) for value in configurations.values())
            and len({revision(value) for value in configurations.values()}) <= 1,
            "canonical-catalog-conflict")
    return {"schema": 1, "policy": copy.deepcopy(policy), "claim": None, "history": {},
            "canonical": {key: {"revision": revision(value), "document": copy.deepcopy(value)}
                          for key, value in configurations.items()}}


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 1024 and all(ord(c) >= 32 for c in value)


def _scopes(value):
    require(isinstance(value, list) and value, "scopes-required")
    require(all(isinstance(scope, str) and re.fullmatch(
        r"/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[^/?#\\]+", scope, re.I)
        for scope in value), "scopes-invalid")
    result = sorted(scope.lower() for scope in value)
    require(len(result) == len(set(result)), "scopes-duplicate")
    return result


class Admission:
    def __init__(self, store, authority):
        require(callable(getattr(store, "read", None)) and callable(getattr(store, "replace", None)),
                "coordinator-required")
        require(callable(getattr(authority, "authenticate", None))
                and callable(getattr(authority, "observe", None)), "authority-required")
        self.store, self.authority = store, authority
        self.write_failed = False

    def _read(self):
        head, state = self.store.read()
        require(isinstance(state, dict) and isinstance(state.get("records"), dict), "not-enrolled")
        record = state["records"].get(RECORD)
        require(isinstance(record, dict), "not-enrolled")
        require(set(record) == {"schema", "policy", "claim", "history", "canonical"}
                and record["schema"] == 1
                and isinstance(record["policy"], dict)
                and isinstance(record["history"], dict)
                and isinstance(record["canonical"], dict), "state-invalid")
        require(record["policy"].get("repository") == state.get("repository"), "repository-mismatch")
        return head, state, record

    def _writable(self):
        require(not self.write_failed and not getattr(self.store, "write_failed", False),
                "reconciliation-required")

    def _replace(self, head, state):
        self._writable()
        self.write_failed = True
        result = self.store.replace(head, state)
        self.write_failed = False
        return result

    def _policy(self, record, factory_id):
        policy = record["policy"].get("factories", {}).get(factory_id)
        require(isinstance(policy, dict), "factory-not-enrolled")
        require(policy.get("all_writers") == PROTOCOL
                and policy.get("shared_scopes") == []
                and isinstance(policy.get("operations"), list)
                and set(policy["operations"]) == OPERATIONS
                and isinstance(policy.get("routes"), list)
                and set(policy["routes"]) == {"api", "pipeline"}, "writer-coverage-unsupported")
        _scopes(policy.get("scopes"))
        return policy

    def _canonical(self, record, factory_id):
        value = record["canonical"].get(factory_id)
        require(isinstance(value, dict) and set(value) == {"revision", "document"}
                and value["revision"] == revision(value["document"]), "canonical-configuration-invalid")
        require(all(other == value for other in record["canonical"].values()), "canonical-catalog-conflict")
        return copy.deepcopy(value)

    def canonical_configuration(self, factory_id):
        _, _, record = self._read()
        self._policy(record, factory_id)
        return self._canonical(record, factory_id)

    def acquire(self, request, *, scope_extension=()):
        self._writable()
        require(isinstance(request, dict) and set(request) == {
            "factory_id", "operation_id", "route", "operation", "scopes", "configuration_revision", "review_digest"},
            "request-invalid")
        require(all(_text(request[key]) for key in (
            "factory_id", "operation_id", "route", "operation", "configuration_revision")), "request-invalid")
        require(isinstance(request["review_digest"], str)
                and re.fullmatch(r"[a-f0-9]{64}", request["review_digest"]), "review-digest-required")
        head, state, record = self._read()
        policy = self._policy(record, request["factory_id"])
        require(request["route"] in policy["routes"] and request["operation"] in policy["operations"],
                "operation-not-enrolled")
        require(_scopes(request["scopes"]) == _scopes(policy["scopes"]), "scope-mismatch")
        additional = _scopes(list(scope_extension)) if scope_extension else []
        require(not additional or request["route"] == "pipeline" and request["operation"] in ("bootstrap", "execute"),
                "scope-extension-operation-invalid")
        require(not set(additional).intersection(_scopes(policy["scopes"])), "scope-extension-already-enrolled")
        require(state.get("active") is None, "inner-claim-active")
        require(record["claim"] is None, "busy-reconciliation-required")
        for completed in record["history"].values():
            require(isinstance(completed, dict) and isinstance(completed.get("claim"), dict),
                    "history-invalid")
            prior = completed["claim"]
            require((prior.get("route"), prior.get("operation_id")) !=
                    (request["route"], request["operation_id"]), "operation-already-completed")
        canonical = self._canonical(record, request["factory_id"])
        require(canonical["revision"] == request["configuration_revision"], "configuration-changed")
        identity = self.authority.authenticate(copy.deepcopy(request), copy.deepcopy(policy))
        require(isinstance(identity, dict)
                and all(_text(identity.get(key)) for key in ("subject", "run_id", "authorization_id"))
                and identity.get("repository") == state["repository"]
                and identity.get("route") == request["route"]
                and identity.get("operation_id") == request["operation_id"]
                and identity.get("review_digest") == request["review_digest"], "authenticated-identity-required")
        require(not additional or identity.get("scope_extension") == additional,
                "scope-extension-authorization-required")
        claim = {**copy.deepcopy(request), "id": str(uuid4()), "protocol": PROTOCOL,
                "scopes": sorted(_scopes(request["scopes"]) + additional), "identity": copy.deepcopy(identity)}
        updated = copy.deepcopy(state)
        if additional:
            updated["records"][RECORD]["policy"]["factories"][request["factory_id"]]["scopes"] = claim["scopes"]
        updated["records"][RECORD]["claim"] = claim
        self._replace(head, updated)
        return copy.deepcopy(claim)

    def _owned(self, claim):
        require(isinstance(claim, dict) and claim.get("protocol") == PROTOCOL, "ownership-required")
        head, state, record = self._read()
        require(record["claim"] == claim, "ownership-changed")
        policy = self._policy(record, claim["factory_id"])
        require(_scopes(policy["scopes"]) == claim["scopes"], "ownership-policy-changed")
        return head, state, record

    def assert_owned(self, claim):
        """Check immediately before each effect; an inner claim is allowed here."""
        self._writable()
        self._owned(claim)

    def commit_configuration(self, claim, expected_revision, document):
        """Publish canonical configuration first; a local projection is never authority."""
        self._writable()
        head, state, record = self._owned(claim)
        prior = self._canonical(record, claim["factory_id"])
        require(prior["revision"] == expected_revision, "configuration-changed")
        replacement = {"revision": revision(document), "document": copy.deepcopy(document)}
        updated = copy.deepcopy(state)
        updated["records"][RECORD]["canonical"] = {
            factory_id: copy.deepcopy(replacement) for factory_id in record["canonical"]}
        self._replace(head, updated)
        return copy.deepcopy(replacement)

    def complete(self, claim, evidence):
        """Release only after remote terminal identity AND live inventory reconciliation.

        A fresh instance may reconcile an uncertain previous write by reading the
        durable claim. Caller evidence is only a lookup hint to the authority.
        Failed/cancelled runs obey the same rule as successful ones.
        """
        self._writable()
        head, state, record = self._owned(claim)
        require(state.get("active") is None, "inner-claim-reconciliation-required")
        observation = self.authority.observe(copy.deepcopy(claim), copy.deepcopy(evidence))
        require(isinstance(observation, dict)
                and observation.get("run_id") == claim["identity"]["run_id"]
                and observation.get("repository") == state["repository"]
                and observation.get("terminal") is True
                and observation.get("inventory_complete") is True
                and observation.get("active_operations") == []
                and _text(observation.get("evidence_id")), "reconciliation-unverified")
        updated = copy.deepcopy(state)
        updated["records"][RECORD]["history"][claim["id"]] = {
            "claim": copy.deepcopy(claim), "observation": copy.deepcopy(observation)}
        updated["records"][RECORD]["claim"] = None
        self._replace(head, updated)
        return copy.deepcopy(observation)
