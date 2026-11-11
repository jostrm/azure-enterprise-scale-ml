"""Reviewed native Microsoft 365/Teams publication, without inference or bot resources."""

from __future__ import annotations

from copy import deepcopy
import json
import re
import time
from urllib.parse import quote, urlsplit

from .azure import AzureError, AzureSession
from .foundry_publishing import AUDIENCE, FoundryPublishingPreparation, PreparationRequest


METADATA_FIELDS = (
    "agentDisplayName", "shortDescription", "fullDescription", "developerName",
    "developerWebsiteUrl", "privacyUrl", "termsOfUseUrl", "appVersion",
)
_USER_FIELDS = METADATA_FIELDS[:-1]
_DEFAULT_FIELDS = (*METADATA_FIELDS, "appPublishScope", "agentName", "appRegistrationClientId",
                   "recommendedNextAppVersion", "titleId", "teamsAppId")
_VERSION = re.compile(r"[1-9][0-9]*\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_SCHEMES = {"Shared": "BotServiceRbac", "Tenant": "BotServiceTenant"}
_DESTINATION = "One native publication to Microsoft Teams and Microsoft 365 Copilot catalogs."


def _redact_diagnostic(message: str) -> str:
    message = re.sub(r"(?i)\b(?:Bearer|Basic)\s+[^\s,;\"'<>]+", "[REDACTED]", message)
    message = re.sub(
        r"""(?ix)\b((?:access|refresh|id)[_-]?token|client[_-]?(?:secret|assertion)|
        api[_-]?key|password|(?:proxy[_-])?authorization|token|secret|sig)
        \b["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;}&]+)""",
        r"\1=[REDACTED]", message,
    )
    message = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED]", message)
    message = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1[REDACTED]@", message)
    message = re.sub(r"[\x00-\x1f\x7f]", " ", message)
    return " ".join(message.split())[:600]


def _failure_cause(error: Exception) -> tuple[str | None, str]:
    detail = str(error)
    if isinstance(error, AzureError):
        detail = detail.partition(f"HTTP {error.status}: ")[2] or "No service diagnostic was returned."
    code = None
    try:
        document = json.loads(detail)
    except json.JSONDecodeError:
        message = detail
    else:
        payload = document.get("error", document) if isinstance(document, dict) else document
        if isinstance(payload, dict):
            candidate = payload.get("code")
            if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", candidate):
                code = _redact_diagnostic(candidate)
            message = payload.get("message")
        else:
            message = payload if isinstance(payload, str) else None
        if not isinstance(message, str):
            message = "Service returned a structured failure without a readable message."
    return code, _redact_diagnostic(message)


class PublicationUncertainError(RuntimeError):
    """A mutation was attempted; inspect live publication before any retry."""

    def __init__(self, stage: str, error: Exception):
        self.stage = stage
        self.http_status = error.status if isinstance(error, AzureError) else None
        self.cause_code, self.cause_message = _failure_cause(error)
        status = f" HTTP {self.http_status}." if self.http_status is not None else ""
        diagnostic = f"{self.cause_code}: " if self.cause_code else ""
        super().__init__(
            f"The endpoint may already be prepared; publication is uncertain during {stage}.{status} "
            f"Cause: {diagnostic}{self.cause_message} "
            "No automatic publication retry was attempted. Read publishdefaults and the agent before "
            "retrying; re-review identity, authorization, active version routing and metadata. "
            "Check server-side bot registration feature enablement, metadata validation, "
            "permissions and network connectivity. Store discovery and conversations are not verified."
        )


def _scope(scope: str) -> str:
    if not isinstance(scope, str) or scope not in _SCHEMES:
        raise ValueError("Publication scope must be Shared or Tenant; Tenant requires explicit review.")
    return scope


def _valid_version(value: object) -> bool:
    return isinstance(value, str) and _VERSION.fullmatch(value) is not None


def _metadata(metadata: dict) -> dict:
    if not isinstance(metadata, dict) or set(metadata) - set(METADATA_FIELDS):
        raise ValueError(f"Unsupported metadata fields; only {', '.join(METADATA_FIELDS)} are allowed.")
    result = {}
    for field, value in metadata.items():
        if not isinstance(value, str):
            raise ValueError(f"{field} metadata must be a string.")
        # Reject control characters before stripping so malformed URLs cannot become approved URLs.
        if field.endswith("Url") and any(character.isspace() for character in value):
            if value.strip():
                raise ValueError(f"{field} requires an HTTPS URL without whitespace.")
        value = value.strip()
        if not value:
            result[field] = ""
            continue
        limit = {"agentDisplayName": 100, "shortDescription": 80,
                 "fullDescription": 4000, "developerName": 32}.get(field)
        if limit and len(value) > limit:
            raise ValueError(f"{field} cannot exceed {limit} characters.")
        if field.endswith("Url"):
            try:
                parsed = urlsplit(value)
                valid = (parsed.scheme == "https" and bool(parsed.hostname)
                         and not parsed.username and not parsed.password
                         and not any(ord(character) < 32 or ord(character) == 127 for character in value)
                         and "\\" not in value and len(value) <= 2048)
                parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"{field} requires an HTTPS URL without embedded credentials.")
        if field == "appVersion" and not _valid_version(value):
            raise ValueError("appVersion must be three semantic-version numeric parts with major >= 1.")
        result[field] = value
    return result


def _published(defaults: dict) -> bool:
    return bool(defaults.get("titleId") or defaults.get("teamsAppId"))


def _publication_before(defaults: dict) -> dict:
    return {field: defaults.get(field) for field in
            (*METADATA_FIELDS, "appPublishScope", "titleId", "teamsAppId")}


def _published_scope(defaults: dict) -> str | None:
    value = defaults.get("appPublishScope")
    return "Shared" if value == "Personal" else value


class M365Publisher:
    def __init__(
        self, session: AzureSession, *, sleep=time.sleep,
        verification_attempts: int = 3, verification_delay: float = 2,
    ):
        if (isinstance(verification_attempts, bool) or not isinstance(verification_attempts, int)
                or not 1 <= verification_attempts <= 10):
            raise ValueError("verification_attempts must be between 1 and 10.")
        if not isinstance(verification_delay, (int, float)) or not 0 <= verification_delay <= 30:
            raise ValueError("verification_delay must be between 0 and 30 seconds.")
        self.session = session
        self.preparation = FoundryPublishingPreparation(session)
        self.sleep = sleep
        self.verification_attempts = verification_attempts
        self.verification_delay = verification_delay

    @staticmethod
    def _url(preparation: dict, operation: str) -> str:
        target = preparation["target"]
        return (f"{target['project_endpoint']}/agents/{quote(target['agent_name'], safe='')}"
                f"/microsoft365/{operation}?api-version=v1")

    def _observe(self, request: PreparationRequest, scope: str) -> tuple[dict, dict]:
        if request.skip_reason:
            raise ValueError("Publication requires a configured native agent target, not a skipped preparation.")
        preparation = self.preparation.run(
            request, authorization_scheme=_SCHEMES[scope], allow_scope_change=True,
        )
        latest = preparation["active_version"].get("resolved_latest")
        if latest is not None and (not latest["version"] or latest["version"] == "@latest"):
            raise ValueError("Cannot resolve the current @latest agent version; inspect versions.latest before publishing.")
        raw = self.session.request("GET", self._url(preparation, "publishdefaults"), audience=AUDIENCE)
        if not isinstance(raw, dict):
            raise ValueError("publishdefaults response is malformed; inspect the native publication service.")
        defaults = {}
        for field in _DEFAULT_FIELDS:
            if field in raw:
                value = raw[field]
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"publishdefaults {field} must be a string or null.")
                defaults[field] = value
        if defaults.get("agentName") and defaults["agentName"] != request.agent_name:
            raise ValueError("publishdefaults agent name does not match the reviewed native agent.")
        client = defaults.get("appRegistrationClientId")
        if client and client.lower() != preparation["target"]["client_id"].lower():
            raise ValueError("publishdefaults registration client identity differs from the native agent identity.")
        return preparation, defaults

    def plan(self, request: PreparationRequest, metadata: dict, *, scope: str = "Shared") -> dict:
        scope = _scope(scope)
        approved = _metadata(metadata)
        preparation, defaults = self._observe(request, scope)
        existing = _published(defaults)
        # New-app defaults can be generated from model instructions or placeholder legal URLs.
        # Only a previously published record is a source of approved metadata.
        candidate = {key: defaults[key] for key in _USER_FIELDS
                     if existing and defaults.get(key)}
        candidate.update({key: value for key, value in approved.items() if key != "appVersion"})
        candidate.setdefault("agentDisplayName", request.agent_name)
        candidate = _metadata(candidate)
        missing = [key for key in _USER_FIELDS if not candidate.get(key)]
        block_reasons = []
        candidate = {key: value for key, value in candidate.items() if value}
        changed = (not existing or _published_scope(defaults) != scope
                   or any(candidate.get(key) != defaults.get(key) for key in _USER_FIELDS))
        warnings = [
            "Publishing submits metadata to both Microsoft 365 and Teams; review their data handling requirements.",
            "Native bot registration requires the service feature to be enabled for this project.",
            "Active agent version routing is preserved; store discovery and conversations are not tested.",
        ]
        if scope == "Tenant":
            warnings.append(
                "Tenant scope enables BotServiceTenant for all tenant users and submits the app for admin approval; "
                "submission does not establish approval or availability."
            )
        else:
            warnings.append("Shared scope uses BotServiceRbac; other callers still need the required Foundry permissions.")
        explicit_version = approved.get("appVersion")
        current_version = defaults.get("appVersion")
        if explicit_version:
            if existing and changed and explicit_version == current_version:
                raise ValueError("Changed metadata or scope requires a new appVersion; the published version cannot be replayed.")
            version = explicit_version
        elif not existing:
            version = "1.0.0"
        elif not changed:
            version = current_version
        else:
            version = defaults.get("recommendedNextAppVersion")
            if version == current_version:
                version = None
        if not _valid_version(version):
            missing.append("appVersion")
            warnings.append("Supply an explicit new appVersion; the service did not return a valid usable published/recommended version.")
        else:
            candidate["appVersion"] = version
        if existing and _published_scope(defaults) not in _SCHEMES:
            block_reasons.append("Existing publication scope is unavailable; inspect publishdefaults before changing access.")
        needs_publish = changed or (existing and bool(explicit_version) and explicit_version != current_version)
        body = {**candidate, "performBotRegistration": True, "publishAsAutopilot": False, "publishScope": scope}
        return {
            "mode": "plan", "target": deepcopy(preparation["target"]), "preparation": preparation,
            "publish_body": body, "defaults": defaults, "publication_before": _publication_before(defaults),
            "missing_fields": missing, "block_reasons": block_reasons,
            "warnings": warnings + preparation["warnings"],
            "needs_publish": needs_publish,
            "status": "blocked" if missing or block_reasons else (
                "ready" if needs_publish or preparation["changed"] else "unchanged"
            ),
            "active_version": deepcopy(preparation["active_version"]),
            "destination": _DESTINATION, "scope": scope,
            "published": False, "store_discovery_verified": False, "conversation_verified": False,
        }

    @staticmethod
    def _check_review(reviewed: dict, current: dict) -> None:
        for field in ("target", "publish_body", "publication_before", "active_version", "needs_publish", "scope"):
            if reviewed.get(field) != current[field]:
                raise RuntimeError(f"Live {field} differs from the reviewed publication plan; review again before applying.")
        old, fresh = reviewed["preparation"], current["preparation"]
        for field in ("target", "enable_m365_public_endpoint", "public_network_access",
                      "authorization_scheme", "allow_scope_change"):
            if old.get(field) != fresh[field]:
                raise RuntimeError(f"Preparation {field} differs from the reviewed publication action.")
        for phase in ("before", "after"):
            if old[phase].get("authorization_schemes") != fresh[phase]["authorization_schemes"]:
                raise RuntimeError("Live authorization differs from the reviewed permission change.")
        if old.get("active_version") != current["active_version"]:
            raise RuntimeError("Active version routing differs from the reviewed preparation.")

    @staticmethod
    def _check_preservation(expected: dict, observed: dict) -> None:
        if expected["target"] != observed["target"]:
            raise RuntimeError("Publication verification failed: target identity changed.")
        if expected["public_network_access"] != observed["public_network_access"]:
            raise RuntimeError("Publication verification failed: account public network access changed.")
        if expected["active_version"] != observed["active_version"]:
            raise RuntimeError("Publication verification failed: active agent version changed.")
        before, actual = expected["after"], observed["before"]
        for key, value in before.items():
            if key in ("protocols", "publish_approval_status"):
                continue
            if key == "protocol_configuration":
                if any(actual[key].get(protocol) != config for protocol, config in value.items()):
                    raise RuntimeError("Publication verification failed: existing protocol settings were not preserved.")
            elif actual.get(key) != value:
                raise RuntimeError(f"Publication verification failed: endpoint {key}/routing was not preserved.")
        if not set(before.get("protocols", [])).issubset(actual.get("protocols", [])):
            raise RuntimeError("Publication verification failed: enabled protocols were not preserved.")

    @staticmethod
    def _matches(defaults: dict, body: dict, response: dict, preparation: dict) -> bool:
        return (_published(defaults) and _published_scope(defaults) == body["publishScope"]
                and all(defaults.get(key) == body.get(key) for key in METADATA_FIELDS)
                and preparation["before"].get("publish_approval_status") != "not_published"
                and all(defaults.get(key) == value for key, value in response.items()))

    @staticmethod
    def _result(plan: dict, preparation: dict, defaults: dict, *, verified: bool,
                submitted: bool, response: dict) -> dict:
        result = deepcopy(plan)
        approval = preparation["before"].get("publish_approval_status")
        status = "published" if submitted else "unchanged"
        if not verified:
            status = "pending_verification"
            result["warnings"].append(
                "Publication verification is pending: persisted IDs, metadata, scope or version do not match "
                "the reviewed submission. Inspect publishdefaults before retrying; no success is claimed."
            )
        elif approval == "rejected":
            status = "rejected"
        elif plan["scope"] == "Tenant" and approval != "approved":
            status = "pending_admin"
        result.update(
            mode="apply", status=status, published=verified, submitted=submitted,
            title_id=defaults.get("titleId") or response.get("titleId"),
            teams_app_id=defaults.get("teamsAppId") or response.get("teamsAppId"), approval_status=approval,
            defaults=deepcopy(defaults), store_discovery_verified=False, conversation_verified=False,
        )
        return result

    def apply(
        self, request: PreparationRequest, metadata: dict, *,
        scope: str = "Shared", reviewed_plan: dict,
    ) -> dict:
        scope = _scope(scope)
        if (not isinstance(reviewed_plan, dict) or reviewed_plan.get("mode") != "plan"
                or reviewed_plan.get("status") not in ("ready", "unchanged")
                or not isinstance(reviewed_plan.get("preparation"), dict)
                or any(not isinstance(reviewed_plan["preparation"].get(phase), dict)
                       for phase in ("before", "after"))):
            raise ValueError("Apply requires a complete reviewed plan; blocked or missing metadata cannot be published.")
        current = self.plan(request, metadata, scope=scope)
        if current["status"] == "blocked":
            raise ValueError("Live publication plan is blocked; resolve missing metadata or block_reasons before applying.")
        self._check_review(reviewed_plan, current)
        try:
            prepared = self.preparation.run(
                request, apply=True, reviewed_plan=current["preparation"],
                authorization_scheme=_SCHEMES[scope], allow_scope_change=True,
            )
            # Recheck publication content after preparation: another publisher may have changed it
            # while the endpoint PATCH and its read-back were in flight.
            live = self.plan(request, metadata, scope=scope)
            for field in ("target", "publish_body", "publication_before", "active_version", "needs_publish"):
                if live[field] != current[field]:
                    raise RuntimeError(f"Publication {field} changed during endpoint preparation.")
            self._check_preservation(prepared, live["preparation"])
        except (AzureError, RuntimeError, ValueError, OSError) as error:
            raise PublicationUncertainError("endpoint preparation/revalidation", error) from None
        current["preparation"] = prepared
        if not current["needs_publish"]:
            return self._result(current, live["preparation"], live["defaults"],
                                verified=self._matches(live["defaults"], current["publish_body"], {}, live["preparation"]),
                                submitted=False, response={})
        try:
            raw_response = self.session.request(
                "POST", self._url(prepared, "publish"), current["publish_body"], audience=AUDIENCE,
            )
            if not isinstance(raw_response, dict):
                raise ValueError("Publication response was not a JSON object.")
            response = {key: raw_response[key] for key in ("titleId", "teamsAppId")
                        if isinstance(raw_response.get(key), str) and raw_response[key]}
        except (AzureError, RuntimeError, ValueError, OSError) as error:
            raise PublicationUncertainError("native publication/registration", error) from None
        for attempt in range(self.verification_attempts):
            if attempt:
                self.sleep(self.verification_delay)
            try:
                observation, defaults = self._observe(request, scope)
                self._check_preservation(prepared, observation)
            except (AzureError, RuntimeError, ValueError, OSError) as error:
                raise PublicationUncertainError("post-publication read-back verification", error) from None
            if self._matches(defaults, current["publish_body"], response, observation):
                return self._result(current, observation, defaults, verified=True,
                                    submitted=True, response=response)
        return self._result(current, observation, defaults, verified=False, submitted=True, response=response)
