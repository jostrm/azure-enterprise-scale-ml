"""esaf.add_scale_set(settings=...) and `azurefactory esaf add-scale-set --settings-json`: scale-set settings such as
BYO VNet, BYO subnets and BYO ASE v3 travel in the one add-scale-set call (Joakim 2026-11-10)."""

import json

from test_esaf import FOLDER, JOB, Transport, posted

from azurefactory import cli, esaf

BYO = {"BYO_subnets": "true", "vnetResourceGroup_param": "rg-network", "vnetNameFull_param": "vnet-ai-dev",
       "byoASEv3": "true", "byoAseFullResourceId": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Web/"
                                                   "hostingEnvironments/ase"}


def test_add_scale_set_posts_its_settings(monkeypatch):
    transport = Transport()
    esaf.connect(folder=FOLDER, client=transport)
    job = esaf.add_scale_set("002", "dev", cidr="10.141.0.0/16", settings=BYO)
    assert posted(transport) == ("/api/v1/esaf/add-scale-set", {
        "folder": FOLDER, "approved": True, "scale_set": "002", "environment": "dev", "cidr": "10.141.0.0/16",
        "settings": BYO})
    assert job.id == JOB


def test_the_cli_reads_scale_set_settings_from_a_json_file(monkeypatch, capsys, tmp_path):
    settings = tmp_path / "byo.json"
    settings.write_text(json.dumps(BYO), encoding="utf-8")
    transport = Transport()
    monkeypatch.setattr(cli, "AzureFactoryClient", lambda *args, **kwargs: transport)
    monkeypatch.setenv("ESAF_FOLDER", FOLDER)
    assert cli.main(["esaf", "add-scale-set", "002", "dev", "--cidr", "10.141.0.0/16",
                     "--settings-json", str(settings)]) == 0
    assert json.loads(capsys.readouterr().out)["job_id"] == JOB
    assert posted(transport)[1]["settings"] == BYO
