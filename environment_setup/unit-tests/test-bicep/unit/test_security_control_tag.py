"""Joakim, 2026-11-05: "Yes, tag test RGs". Opt-in bootstrap key security_control_ignore_tag writes SecurityControl=Ignore
on the factory's owned resource groups from their first write: the exemption tag the MCAPS Modify policies check
(AI Foundry hub, Storage/Key Vault/Cosmos/SQL publicNetworkAccess, local auth). Never on by default: production
factories keep governance."""

from __future__ import annotations

import json

import pytest

from test_registered_prerequisites import OWNED, Runtime, arguments, core, workspace  # noqa: F401  (fixture)


def created_group_tags(plan):
    found = []

    def walk(value):
        if isinstance(value, dict):
            if str(value.get("resource_id", value.get("id", ""))).lower() == OWNED.lower() and isinstance(
                    (value.get("body") or {}).get("tags"), dict):
                found.append(value["body"]["tags"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(plan)
    return found


def test_the_key_is_an_accepted_prerequisite_config_field():
    assert "security_control_ignore_tag" in core.CONFIG_KEYS


@pytest.mark.parametrize("enabled", [True, False])
def test_a_new_owned_group_carries_the_exemption_tag_only_when_opted_in(workspace, enabled):
    runtime = Runtime()
    runtime.resources.pop(OWNED)
    plan = core.prepare(**arguments(workspace, **({"security_control_ignore_tag": True} if enabled else {})),
                        runtime=runtime)
    tags = created_group_tags(plan)
    assert tags, json.dumps(plan)[:400]
    assert all(("SecurityControl" in item) is enabled for item in tags)
    assert all(item.get("SecurityControl") == "Ignore" for item in tags if enabled)
    assert all(item["aifactory.factory_id"] for item in tags)


def test_an_existing_group_without_the_tag_is_not_silently_retagged(workspace):
    runtime = Runtime()
    with pytest.raises(core.PrerequisiteError, match="existing-owned-resource-group-tags-mismatch"):
        core.prepare(**arguments(workspace, security_control_ignore_tag=True), runtime=runtime)
    runtime.resources[OWNED]["tags"]["SecurityControl"] = "Ignore"
    assert core.prepare(**arguments(workspace, security_control_ignore_tag=True), runtime=runtime)["plan_hash"]


def test_the_key_must_be_a_boolean(workspace):
    with pytest.raises(core.PrerequisiteError, match="security-control-ignore-tag"):
        core.prepare(**arguments(workspace, security_control_ignore_tag="yes"), runtime=Runtime())
