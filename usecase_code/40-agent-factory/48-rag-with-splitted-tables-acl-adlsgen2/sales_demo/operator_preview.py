"""Explicit trusted-local operator preview; never a managed-backend or ACL-denial proof."""
from uuid import UUID

from agent_factory.prompt import SessionCredential

from .identity import (
    GRAPH, SEARCH, STORAGE, DelegatedAuthorization, ManagedIdentitySearchTransport,
    SalesUnavailable, _claims, search_endpoint,
)


def require_preview_policy(config: dict) -> str:
    if config.get("evaluation_mode") != "operator-preview":
        raise ValueError("This command requires explicit evaluation_mode=operator-preview.")
    identifier = UUID(config.get("operator_preview_user_id", ""))
    if not identifier.int:
        raise ValueError("A concrete existing user identity is required.")
    user = str(identifier)
    if config.get("denied_test_user_ids"):
        raise ValueError("An operator preview cannot designate a denied test identity.")
    partitions = config["partitions"]
    if len(partitions) != 2 or {p["id"] for p in partitions} != {"json", "excel"}:
        raise ValueError("Both configured sales partitions are required.")
    if any(p.get("allowed_user_ids") != [user] or p.get("allowed_group_ids") for p in partitions):
        raise ValueError("Operator preview must authorize only the same explicit user in both partitions.")
    return user


def verified_preview_identity(config: dict, authorization):
    user = require_preview_policy(config)
    identity = authorization.authorize()
    if identity.tenant_id != config["tenant_id"] or identity.oid != user:
        raise SalesUnavailable()
    return identity


class SessionTokenProvider:
    def __init__(self, session):
        self.session = session

    def token(self, resource: str) -> str:
        if resource not in {GRAPH, SEARCH, STORAGE}:
            raise SalesUnavailable()
        return self.session.token(resource)


def preview_authorization(config: dict, session):
    return DelegatedAuthorization(config["tenant_id"], SessionTokenProvider(session))


class PreviewSearchTransport(ManagedIdentitySearchTransport):
    """Same read-only request guard, but explicitly use the authenticated operator.

    This is not a fallback for a missing managed identity. Only preview.py creates
    it, after binding the configured user to authenticated Graph /me.
    """
    def __init__(self, config: dict, session):
        self.user = require_preview_policy(config)
        self.tenant = config["tenant_id"]
        self.endpoint = search_endpoint(config)
        self.session = session
        self.credential = SessionCredential(session)

    def request(self, method, url, body=None, *, audience=SEARCH, headers=None):
        bearer = self.session.token(SEARCH)
        if _claims(bearer, SEARCH, self.tenant)["oid"] != self.user:
            raise SalesUnavailable()
        supplied = (headers or {}).get("x-ms-query-source-authorization")
        if supplied and _claims(supplied, SEARCH, self.tenant)["oid"] != self.user:
            raise SalesUnavailable()
        return super().request(method, url, body, audience=audience, headers=headers)


def summarize_preview_evaluation(report: dict) -> dict:
    return {
        **report, "scope": "operator-preview", "passed": False,
        "authorized_cases_passed": bool(report.get("cases")) and all(item["passed"] for item in report["cases"]),
        "complete_acl_acceptance": False,
        "restricted_identity": {
            "state": "not-tested",
            "reason": "One existing operator was selected; broad RBAC is not evidence of ACL allow/deny or revocation.",
        },
        "backend_identity_mode": "operator-not-managed-identity",
    }
