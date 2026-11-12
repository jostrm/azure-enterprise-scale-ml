"""The ESAF facade's friendly names for the BYO network settings (Joakim 2026-11-11): byoVnetResourcegroupName,
byoVnetName and enableByoSubnets. The Factory API maps them to the wizard's keys (pink esaf_service.SETTING_ALIASES),
so the SDK and the CLI send a settings object exactly as it was written: one mapping, in one place."""

import json

from test_esaf import FOLDER, Transport, posted

from azurefactory import cli, esaf

CREATION = {"contract_version": 1, "mode": "full-bootstrap", "folder": FOLDER,
            "config": {"factory_prefix": "acme-", "location": "swedencentral", "scale_set_number": "001"}}
BYO_VNET = {"byoVnetResourcegroupName": "rg-network", "byoVnetName": "vnet-ai-dev"}
BYO_SUBNETS = {**BYO_VNET, "enableByoSubnets": True, "subnetCommon": "snet-dev-esml-cmn-001",
               "subnetProjGenAI": "snt-dev-prj001-genai"}


def connected():
    transport = Transport()
    esaf.connect(folder=FOLDER, client=transport)
    return transport


def test_init_factory_sends_the_friendly_names_as_written():
    transport = connected()
    esaf.init_factory(creation_request=CREATION, scale_set_settings=BYO_SUBNETS)
    assert posted(transport)[1]["scale_set_settings"] == BYO_SUBNETS


def test_add_scale_set_and_upsert_project_send_them_as_written():
    transport = connected()
    esaf.add_scale_set("002", "dev", cidr="10.141.0.0/16", settings=BYO_VNET)
    assert posted(transport)[1]["settings"] == BYO_VNET
    transport = connected()
    esaf.upsert_project("002", "dev", settings=BYO_VNET)
    assert posted(transport)[1]["settings"] == BYO_VNET


def test_the_cli_sends_a_one_file_example_with_friendly_names_as_written(monkeypatch, capsys, tmp_path):
    example = {"creation_request": CREATION, "scale_set_settings": BYO_SUBNETS}
    path = tmp_path / "create-factory.json"
    path.write_text(json.dumps(example), encoding="utf-8")
    transport = Transport()
    monkeypatch.setattr(cli, "AzureFactoryClient", lambda *args, **kwargs: transport)
    monkeypatch.setenv("ESAF_FOLDER", FOLDER)
    assert cli.main(["esaf", "init-factory", "--request-json", str(path)]) == 0
    capsys.readouterr()
    assert posted(transport)[1] == {"folder": FOLDER, "approved": True, **example}
