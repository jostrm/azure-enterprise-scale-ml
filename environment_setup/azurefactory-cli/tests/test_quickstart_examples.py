"""Keep the two README quickstarts on the existing CLI's real command contract."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

import pytest

from azurefactory import cli

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT.parent / "install_config_wizard" / "api-usage-examples"
TARGET = {
    "FACTORY_FOLDER": r"C:\example-only\azurefactory", "FACTORY_KEY": "example-ai",
    "FACTORY_PREFIX": "example-", "FACTORY_REGION": "swedencentral",
    "DEV_SUBSCRIPTION_ID": "11111111-1111-4111-8111-111111111111",
    "TENANT_ID": "22222222-2222-4222-8222-222222222222",
    "DEV_VNET_CIDR": "172.16.0.0/18", "ORCHESTRATOR": "ado", "AIFACTORY_VERSION": "main",
}


def quickstart_commands(path):
    text = path.read_text(encoding="utf-8").split("## Quickstart:", 1)[1].split("\n## ", 1)[0]
    lines = iter(text.splitlines())
    commands = []
    for line in lines:
        match = re.match(r"(?:\$[A-Za-z]\w* = )?azurefactory ", line)
        if not match:
            continue
        while line.rstrip().endswith("`"):
            line = line.rstrip()[:-1] + next(lines).strip()
        tokens = line[match.end():].split()
        commands.append([TARGET.get(token[5:], token) if token.startswith("$env:") else token
                         for token in tokens])
    return commands


@pytest.mark.parametrize("readme", [ROOT / "readme.md", EXAMPLES / "readme.md"])
def test_quickstart_prepares_one_default_project_via_existing_cli(readme, monkeypatch, capsys):
    calls, receipts = [], []

    class Client:
        def catalog_prepare(self, body):
            calls.append(body)
            return {
                "contract_version": 1, "confirmation_id": "33333333-3333-4333-8333-333333333333",
                "can_execute": True, "operation_mode": "configuration", "blockers": [],
                "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            }

    monkeypatch.setattr(cli, "client", lambda args: Client())
    monkeypatch.setattr(cli, "ensure_receipt_target_available", lambda args: None)
    monkeypatch.setattr(cli, "maybe_save_receipt",
                        lambda args, preview, body, purpose, **extra: receipts.append(
                            (args.save_receipt, purpose, extra)))
    commands = quickstart_commands(readme)
    prepares = [args for args in commands if args[:2] == ["factory", "create"]]
    assert len(prepares) == 1
    assert cli.main(prepares[0]) == 0
    assert len(calls) == 1
    body = calls[0]
    assert body["action"] == "create-factory" and body["contract_version"] == 1
    assert body["factory_kind"] == "ai"
    assert "project" not in body and "initial_project" not in body
    assert body["folder"] == TARGET["FACTORY_FOLDER"]
    assert body["target_region"] == TARGET["FACTORY_REGION"]
    assert body["target_prefix"] == TARGET["FACTORY_PREFIX"]
    assert body["factory_key"] == TARGET["FACTORY_KEY"]
    assert body["scale_sets"] == [{
        "environment": "dev", "suffix": "001", "subscription_id": TARGET["DEV_SUBSCRIPTION_ID"],
        "tenant_id": TARGET["TENANT_ID"], "orchestrator": TARGET["ORCHESTRATOR"],
        "network": {"vnet_cidr": TARGET["DEV_VNET_CIDR"], "max_projects": 3},
    }]
    assert body["aifactory_version"] == TARGET["AIFACTORY_VERSION"]
    assert receipts[0][1:] == ("catalog-confirm", {"operation": "factory-create"})
    assert json.loads(capsys.readouterr().out)["operation_mode"] == "configuration"
    for command in commands:
        args = cli.build_parser().parse_args(command)
        assert args.command not in ("runtime", "bootstrap", "enrollment", "legacy")
    confirms = [args for args in commands if args[:2] == ["catalog", "confirm"]]
    assert len(confirms) == 1 and "--yes" in confirms[0] and "--receipt" in confirms[0]


@pytest.mark.parametrize("readme", [ROOT / "readme.md", EXAMPLES / "readme.md"])
def test_quickstart_checks_fresh_isolated_catalog_before_create(readme):
    commands = quickstart_commands(readme)
    read_index = next(index for index, args in enumerate(commands) if args[:2] == ["catalog", "list"])
    create_index = next(index for index, args in enumerate(commands) if args[:2] == ["factory", "create"])
    assert read_index < create_index
    assert commands[read_index] == ["catalog", "list", "--folder", TARGET["FACTORY_FOLDER"]]
    text = readme.read_text(encoding="utf-8")
    assert "@($before.factories).Count -ne 0" in text
    assert "do not recreate an occupied factory" in text
