"""Prepare a native Foundry endpoint; never publish, register a bot, or invoke it."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import re
from urllib.parse import quote

from .azure import AzureSession
from .catalog import validate_agent_name


INPUTS = (
    "enableBotService", "enableAIFoundry", "deleteAllServicesForProject",
    "deleteAllForProject", "dev_test_prod_sub_id", "tenantId",
    "botFoundryProjectResourceId", "botFoundryAgentName", "botEnableM365PublicEndpoint",
)
ARM_API = "2025-06-01"
AUDIENCE = "https://ai.azure.com"
_GUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_PROJECT_ID = re.compile(
    rf"/subscriptions/(?P<subscription>{_GUID})"
    r"/resourceGroups/[a-zA-Z0-9_().-]{1,90}"
    r"/providers/Microsoft\.CognitiveServices/accounts/"
    r"(?P<account>[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    r"/projects/(?P<project>[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63})",
    re.IGNORECASE,
)
_PATCH_FIELDS = ("protocol_configuration", "authorization_schemes")
_MANUAL_PUBLICATION = (
    "Not published. Review the active agent version, downstream identity permissions, and "
    "Microsoft 365 data-flow requirements. Separately approve and perform native Foundry "
    "Microsoft 365 publication/registration for Shared (BotServiceRbac) scope, then verify "
    "Teams end to end. Private projects require the REST publication flow from a connected "
    "client; this preparation performs neither publication nor ZIP generation."
)


def _optional(value: object, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string.")
    value = value.strip()
    return "" if re.fullmatch(r"\$\([^)]+\)", value) else value


def _flag(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = _optional(value, name).lower()
    if text in ("", "false"):
        return False
    if text == "true":
        return True
    raise ValueError(f"{name} must be true or false.")


def _guid(value: object, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(_GUID, value):
        raise ValueError(f"{name} must be a nonempty GUID.")
    return value.lower()


def _project_parts(resource_id: str, subscription_id: str) -> re.Match:
    match = _PROJECT_ID.fullmatch(resource_id)
    if not match:
        raise ValueError("botFoundryProjectResourceId must be a full Foundry project ARM resource id.")
    if match["subscription"].lower() != subscription_id:
        raise ValueError("Foundry project resource id belongs to a different subscription.")
    return match


@dataclass(frozen=True)
class PreparationRequest:
    subscription_id: str
    tenant_id: str
    project_resource_id: str
    agent_name: str
    enable_m365_public_endpoint: bool = False
    skip_reason: str = ""

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> PreparationRequest:
        flags = {name: _flag(values.get(name), name) for name in (
            "enableBotService", "enableAIFoundry", "deleteAllServicesForProject",
            "deleteAllForProject", "botEnableM365PublicEndpoint",
        )}
        if not flags["enableBotService"]:
            return cls("", "", "", "", skip_reason="enableBotService is disabled.")
        project = _optional(values.get("botFoundryProjectResourceId"), "botFoundryProjectResourceId")
        agent = _optional(values.get("botFoundryAgentName"), "botFoundryAgentName")
        if not project and not agent:
            return cls("", "", "", "", skip_reason="No native Foundry project and agent target is configured.")
        if not project or not agent:
            raise ValueError("Configure both botFoundryProjectResourceId and botFoundryAgentName, or neither.")
        if flags["deleteAllServicesForProject"] or flags["deleteAllForProject"]:
            raise ValueError("Native Foundry preparation cannot run while project deletion is enabled.")
        if not flags["enableAIFoundry"]:
            raise ValueError("enableAIFoundry must be true when a native Foundry target is configured.")
        subscription = _guid(
            _optional(values.get("dev_test_prod_sub_id"), "dev_test_prod_sub_id"),
            "dev_test_prod_sub_id",
        )
        tenant = _guid(_optional(values.get("tenantId"), "tenantId"), "tenantId")
        _project_parts(project, subscription)
        validate_agent_name(agent)
        return cls(subscription, tenant, project, agent, flags["botEnableM365PublicEndpoint"])


def _object(value: object, description: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{description} is missing or malformed; cannot safely prepare the endpoint.")
    return value


def _endpoint(agent: dict) -> dict:
    endpoint = _object(agent.get("agent_endpoint"), "agent_endpoint")
    configuration = _object(endpoint.get("protocol_configuration"), "protocol_configuration")
    protocols = endpoint.get("protocols", [])
    if not isinstance(protocols, list) or any(
        not isinstance(protocol, str) or protocol not in configuration for protocol in protocols
    ):
        raise ValueError(
            "Endpoint protocol list contains missing or unsupported protocol_configuration entries; "
            "retrieve complete configurations before preparing this agent."
        )
    schemes = endpoint.get("authorization_schemes")
    if not isinstance(schemes, list) or any(
        not isinstance(scheme, dict) or not isinstance(scheme.get("type"), str) or not scheme["type"]
        for scheme in schemes
    ):
        raise ValueError("authorization_schemes is missing or malformed; refusing to replace unknown authorization.")
    if "activity" in configuration:
        activity = _object(configuration["activity"], "activity protocol configuration")
        if "enable_m365_public_endpoint" in activity and not isinstance(activity["enable_m365_public_endpoint"], bool):
            raise ValueError("activity.enable_m365_public_endpoint must be a boolean.")
    return endpoint


def _binding(state: dict) -> dict:
    agent = state["agent"]
    return deepcopy({
        "subscription_id": state["subscription_id"],
        "project_resource_id": state["project_resource_id"],
        "account_resource_id": state["account_resource_id"],
        "tenant_id": state["tenant_id"],
        "project_endpoint": state["project_endpoint"],
        "agent_id": agent.get("id"), "agent_name": agent["name"],
        "client_id": state["client_id"],
        "instance_identity": agent["instance_identity"], "blueprint": agent.get("blueprint"),
    })


def _plan(request: PreparationRequest, state: dict) -> dict:
    before = deepcopy(_endpoint(state["agent"]))
    after = deepcopy(before)
    schemes = after["authorization_schemes"]
    if any(scheme["type"] == "BotServiceTenant" for scheme in schemes):
        raise ValueError(
            "BotServiceTenant conflicts with BotServiceRbac preparation; explicit operator handling "
            "is required. No existing authorization scheme was changed."
        )
    activity = after["protocol_configuration"].setdefault("activity", {})
    if state["public_network_access"] == "Disabled" and not (
        request.enable_m365_public_endpoint or activity.get("enable_m365_public_endpoint") is True
    ):
        raise ValueError(
            "The Foundry account has public network access disabled. Explicitly approve "
            "botEnableM365PublicEndpoint=true for the source-IP-filtered Microsoft 365 Activity "
            "route, or retain an already enabled route. Global PNA will not be changed."
        )
    if request.enable_m365_public_endpoint:
        activity["enable_m365_public_endpoint"] = True
    if "protocols" in after and "activity" not in after["protocols"]:
        after["protocols"].append("activity")
    if not any(scheme["type"] == "BotServiceRbac" for scheme in schemes):
        schemes.append({"type": "BotServiceRbac"})
    changed = {key: deepcopy(after[key]) for key in _PATCH_FIELDS if after[key] != before[key]}
    return {
        "mode": "plan", "status": "planned" if changed else "unchanged",
        "target": _binding(state), "warnings": [],
        "enable_m365_public_endpoint": request.enable_m365_public_endpoint,
        "subscription_id": request.subscription_id, "tenant_id": request.tenant_id,
        "project_resource_id": request.project_resource_id,
        "account_resource_id": state["account_resource_id"],
        "project_endpoint": state["project_endpoint"],
        "agent_name": request.agent_name, "client_id": state["client_id"],
        "activity_url": state["agent_url"].split("?", 1)[0] + "/endpoint/protocols/activityprotocol",
        "public_network_access": state["public_network_access"],
        "before": before, "after": after,
        "patch": {"agent_endpoint": changed} if changed else {},
        "changed": bool(changed), "applied": False, "published": False, "teams_verified": False,
        "remaining_manual_publication": _MANUAL_PUBLICATION,
    }


class FoundryPublishingPreparation:
    def __init__(self, session: AzureSession):
        self.session = session

    def _read(self, request: PreparationRequest) -> dict:
        parts = _project_parts(request.project_resource_id, request.subscription_id)
        project = _object(self.session.arm(
            "GET", request.project_resource_id, api_version=ARM_API,
        ), "Foundry project")
        if project.get("id") != request.project_resource_id:
            raise ValueError("Returned project resource id does not match the exact requested project.")
        tenant = _guid(_object(project.get("identity"), "Project identity").get("tenantId"), "Project tenant")
        if tenant != request.tenant_id:
            raise ValueError("Foundry project identity belongs to a different tenant.")
        properties = _object(project.get("properties"), "Foundry project properties")
        endpoint = _object(properties.get("endpoints"), "Foundry project endpoints").get("AI Foundry API")
        expected = f"https://{parts['account']}.services.ai.azure.com/api/projects/{parts['project']}"
        if endpoint != expected:
            raise ValueError("AI Foundry API endpoint must exactly match the requested account/project HTTPS endpoint.")
        account_id = request.project_resource_id.rsplit("/", 2)[0]
        account = _object(self.session.arm("GET", account_id, api_version=ARM_API), "Foundry account")
        if account.get("id") != account_id:
            raise ValueError("Returned account resource id does not match the project's exact parent account.")
        pna = _object(account.get("properties"), "Foundry account properties").get("publicNetworkAccess")
        if pna not in ("Enabled", "Disabled"):
            raise ValueError("Foundry account publicNetworkAccess must be explicitly Enabled or Disabled.")
        agent_url = f"{endpoint}/agents/{quote(request.agent_name, safe='')}?api-version=v1"
        agent = _object(self.session.request("GET", agent_url, audience=AUDIENCE), "Foundry agent")
        if agent.get("name") != request.agent_name:
            raise ValueError("Returned agent name does not match the requested native agent name.")
        identity = agent.get("instance_identity")
        if not isinstance(identity, dict) or not identity.get("client_id"):
            raise ValueError(
                "Unsupported legacy agent: a unique instance_identity.client_id is required. "
                "This preparation never recreates or upgrades an agent."
            )
        client = _guid(identity["client_id"], "Agent instance identity client_id")
        shared = properties.get("agentIdentity") or {}
        shared_id = _object(shared, "Shared project agent identity").get("agentIdentityId")
        if isinstance(shared_id, str) and client == shared_id.lower():
            raise ValueError("Unsupported legacy agent: instance identity is the shared project agent identity.")
        _endpoint(agent)
        return {
            "subscription_id": request.subscription_id,
            "project_resource_id": request.project_resource_id, "tenant_id": tenant,
            "account_resource_id": account_id, "project_endpoint": endpoint,
            "public_network_access": pna, "agent_url": agent_url, "agent": agent, "client_id": client,
        }

    def run(
        self, request: PreparationRequest, *, apply: bool = False,
        reviewed_plan: dict | None = None,
    ) -> dict:
        if not isinstance(apply, bool):
            raise ValueError("apply must be a boolean.")
        if request.skip_reason:
            return {
                "mode": "apply" if apply else "plan", "target": {},
                "before": {}, "after": {}, "patch": {}, "warnings": [],
                "status": "skipped", "reason": request.skip_reason, "changed": False,
                "applied": False, "published": False, "teams_verified": False,
            }
        if apply:
            if not isinstance(reviewed_plan, dict) or reviewed_plan.get("mode") != "plan":
                raise ValueError("Apply requires a reviewed plan produced by plan mode.")
            _object(reviewed_plan.get("target"), "Reviewed plan target")
            reviewed_before = _endpoint({"agent_endpoint": reviewed_plan.get("before")})
            if reviewed_plan.get("enable_m365_public_endpoint") is not request.enable_m365_public_endpoint:
                raise ValueError("The reviewed network opt-in must match botEnableM365PublicEndpoint.")
        subscription = _guid(request.subscription_id, "Subscription")
        tenant = _guid(request.tenant_id, "Tenant")
        _project_parts(request.project_resource_id, subscription)
        validate_agent_name(request.agent_name)
        if not isinstance(request.enable_m365_public_endpoint, bool):
            raise ValueError("botEnableM365PublicEndpoint must be a boolean.")
        if (self.session.subscription_id.lower() != subscription
                or self.session.tenant_id.lower() != tenant):
            raise ValueError("Azure session must use the exact requested subscription and tenant.")
        # Replan from live configuration rather than overwriting additions made during review.
        current = self._read(request)
        if apply and reviewed_plan["target"] != _binding(current):
            raise RuntimeError("Live target/identity binding differs from the reviewed plan; no PATCH was sent.")
        result = _plan(request, current)
        if not apply:
            return result
        result["mode"] = "apply"
        for field in (*_PATCH_FIELDS, "version_selector"):
            if reviewed_before.get(field) != result["before"].get(field):
                result["warnings"].append(
                    f"{field} changed since review; recomputed preparation from live settings "
                    "and preserved concurrent settings rather than replaying the reviewed patch."
                )
        if reviewed_plan.get("public_network_access") != current["public_network_access"]:
            result["warnings"].append(
                "Account publicNetworkAccess changed since review; revalidated the current route requirements "
                "without changing global public network access."
            )
        if not result["changed"]:
            return result
        self.session.request(
            "PATCH", current["agent_url"], result["patch"], audience=AUDIENCE,
            headers={"Content-Type": "application/merge-patch+json"},
        )
        verified = self._read(request)
        self._verify(current, verified, result["after"])
        result.update(status="prepared", applied=True)
        return result

    @staticmethod
    def _verify(before: dict, verified: dict, expected: dict) -> None:
        if _binding(before) != _binding(verified):
            raise RuntimeError("Read-back verification failed: agent identity/binding changed.")
        if before["public_network_access"] != verified["public_network_access"]:
            raise RuntimeError("Read-back verification failed: account public network access changed.")
        actual = verified["agent"]["agent_endpoint"]
        if any(actual[key] != expected[key] for key in _PATCH_FIELDS):
            raise RuntimeError("Read-back verification failed: intended endpoint configuration was not applied exactly.")
        # 'protocols' is a service-derived list; enabling Activity legitimately adds an entry.
        untouched = lambda endpoint: {
            key: value for key, value in endpoint.items() if key not in (*_PATCH_FIELDS, "protocols")
        }
        if untouched(actual) != untouched(before["agent"]["agent_endpoint"]):
            raise RuntimeError("Read-back verification failed: endpoint settings/version routing were not preserved.")
        if "protocols" in before["agent"]["agent_endpoint"]:
            required = set(before["agent"]["agent_endpoint"]["protocols"]) | {"activity"}
            if not required.issubset(actual.get("protocols", [])):
                raise RuntimeError("Read-back verification failed: enabled protocols were not preserved.")
        for key in ("versions", "version_selector", "metadata", "agent_card", "description", "display_name"):
            if before["agent"].get(key) != verified["agent"].get(key):
                raise RuntimeError(f"Read-back verification failed: agent {key} was not preserved.")
