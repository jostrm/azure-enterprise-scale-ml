from __future__ import annotations

from .security import authorize
from pydantic import Field

from .tools import NoArguments, ToolError


ACTION_SKILLS = (
    "create-private-aifactory-full-bootstrap-private-with-own-hub-vpn-and-default-proj",
    "delete-aifactory",
    "add-project-to-aifactory",
)
COST_SKILLS = (
    "get-default-project-estimated-azure-idle-running-cost",
    "get-aifactory-common-estimated-azure-idle-running-cost",
    "get-monthtly-forecasted-project-estimated-azure-cost",
)
DIAGNOSTIC_SKILLS = (
    "get-aifactory-health", "get-aifactory-settings", "get-aifactory-operation-status",
)
WORKLOAD_SKILLS = ("create-agent-oftype-for-project", "create-ml-model-oftype-for-project")
SKILL_LABELS = {
    ACTION_SKILLS[0]: "Create private AI Factory with hub, VPN and default project",
    ACTION_SKILLS[1]: "Delete AI Factory",
    ACTION_SKILLS[2]: "Add project to AI Factory",
    COST_SKILLS[0]: "Default project idle running cost",
    COST_SKILLS[1]: "Common resource group idle running cost",
    COST_SKILLS[2]: "Project monthly Azure cost forecast",
    DIAGNOSTIC_SKILLS[0]: "Factory API health",
    DIAGNOSTIC_SKILLS[1]: "Scoped Factory settings",
    DIAGNOSTIC_SKILLS[2]: "Saved operation status",
    WORKLOAD_SKILLS[0]: "Create agent from a project template",
    WORKLOAD_SKILLS[1]: "Create ML model from a project template",
}
SKILL_PERMISSIONS = dict(zip(ACTION_SKILLS, ("factory.create", "factory.delete", "project.add")))
SKILL_PERMISSIONS.update({name: "cost.read" for name in COST_SKILLS})
SKILL_PERMISSIONS.update({name: "factory.read" for name in DIAGNOSTIC_SKILLS})
SKILL_PERMISSIONS.update(dict(zip(WORKLOAD_SKILLS, ("agent.create", "model.create"))))


class OperationStatusArguments(NoArguments):
    operation_id: str = Field(pattern=r"^[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}$")


def normalize_skill(name: str) -> str:
    if not isinstance(name, str):
        raise ToolError("unsupported_skill", "Select a supported Factory skill.", 400)
    name = name.removeprefix("/")
    if name == "get-monthly-forecasted-project-estimated-azure-cost":
        name = COST_SKILLS[2]
    if name not in SKILL_LABELS:
        raise ToolError("unsupported_skill", "Select a supported Factory skill.", 400)
    return name


def argument_model(name: str):
    name = normalize_skill(name)
    if name in ACTION_SKILLS:
        from .actions import argument_model as action_arguments
        return action_arguments(name)
    if name in WORKLOAD_SKILLS:
        from .workloads import argument_model as workload_arguments
        return workload_arguments(name)
    if name in DIAGNOSTIC_SKILLS:
        return OperationStatusArguments if name == DIAGNOSTIC_SKILLS[2] else NoArguments
    from .costs import argument_model as cost_arguments
    return cost_arguments(name)


def skill_catalog(settings, principal, scope_key: str) -> list[dict]:
    authorize(settings, principal, scope_key, "factory.read")
    result = []
    for name, label in SKILL_LABELS.items():
        permission = SKILL_PERMISSIONS[name]
        blockers = []
        try:
            authorize(settings, principal, scope_key, permission)
        except PermissionError:
            blockers.append("permission_required")
        action = name in ACTION_SKILLS or name in WORKLOAD_SKILLS
        if action:
            if not settings.factory.writes_enabled:
                blockers.append("writes_disabled")
            enabled = settings.workloads.enabled_skills if name in WORKLOAD_SKILLS else settings.actions.enabled_skills
            if name not in enabled:
                blockers.append("skill_disabled")
            if settings.scopes[scope_key].environment not in settings.factory.allowed_write_environments:
                blockers.append("environment_not_enabled")
            if not settings.factory.operation_signing_secret_url:
                blockers.append("operation_signing_unconfigured")
            if name == ACTION_SKILLS[0] and scope_key not in settings.actions.bootstrap_profiles:
                blockers.append("bootstrap_profile_required")
            if name == ACTION_SKILLS[1] and scope_key not in settings.actions.deletion_resource_groups:
                blockers.append("deletion_scope_required")
            if name in WORKLOAD_SKILLS:
                if not settings.workloads.repository_root:
                    blockers.append("workload_source_unconfigured")
                if not settings.workloads.profiles.get(scope_key):
                    blockers.append("workload_profile_required")
            elif not all((settings.factory.factory_id, settings.factory.scale_set_id, settings.factory.project_id)):
                blockers.append("factory_target_unconfigured")
        result.append({
            "name": name, "command": "/" + name, "label": label,
            "kind": "action" if action else "monitoring" if name in COST_SKILLS else "diagnostic",
            "permission": permission,
            "model_callable": not action, "approval_required": action,
            "arguments_schema": argument_model(name).model_json_schema(),
            "blockers": blockers, "available": not blockers,
        })
    return result
