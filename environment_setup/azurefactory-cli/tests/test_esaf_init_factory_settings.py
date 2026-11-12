"""esaf.init_factory(scale_set_settings=..., project_settings=...) and `azurefactory esaf init-factory
--scale-set-settings-json --project-settings-json`: the first scale set's settings (BYO VNet, BYO subnets) and the
initial project's service switches travel in the one init-factory call (Joakim 2026-11-11). `--request-json` reads
all three from one file, so a quickstart example is one file and one call. The Factory API saves the settings before
anything deploys."""

import json

from test_esaf import FOLDER, JOB, Transport, posted

from azurefactory import cli, esaf

CREATION = {"contract_version": 1, "mode": "full-bootstrap", "folder": FOLDER,
            "config": {"factory_prefix": "acme-", "location": "swedencentral", "scale_set_number": "001"}}
BYO = {"BYO_subnets": "true", "vnetResourceGroup_param": "rg-network", "vnetNameFull_param": "vnet-ai-dev"}
PROJECT = {"enableAIFactoryMCP": "true", "addAIFactoryMCP2APIM": "true", "enableFactoryChatAgent": "true"}


def test_init_factory_posts_the_scale_set_and_project_settings_with_the_creation_request():
    transport = Transport()
    esaf.connect(folder=FOLDER, client=transport)
    job = esaf.init_factory(creation_request=CREATION, scale_set_settings=BYO, project_settings=PROJECT)
    assert posted(transport) == ("/api/v1/esaf/init-factory", {
        "folder": FOLDER, "approved": True, "creation_request": CREATION, "scale_set_settings": BYO,
        "project_settings": PROJECT})
    assert job.id == JOB


def test_init_factory_without_settings_posts_the_same_body_as_before():
    transport = Transport()
    esaf.connect(folder=FOLDER, client=transport)
    esaf.init_factory(creation_request=CREATION)
    assert posted(transport)[1] == {"folder": FOLDER, "approved": True, "creation_request": CREATION}


def write(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def run_cli(monkeypatch, *arguments):
    transport = Transport()
    monkeypatch.setattr(cli, "AzureFactoryClient", lambda *args, **kwargs: transport)
    monkeypatch.setenv("ESAF_FOLDER", FOLDER)
    return cli.main(["esaf", "init-factory", *arguments]), transport


def test_the_cli_reads_both_settings_from_json_files(monkeypatch, capsys, tmp_path):
    code, transport = run_cli(
        monkeypatch, "--creation-request-json", write(tmp_path, "creation-request.json", CREATION),
        "--scale-set-settings-json", write(tmp_path, "scale-set-settings.json", BYO),
        "--project-settings-json", write(tmp_path, "project-settings.json", PROJECT))
    assert code == 0 and json.loads(capsys.readouterr().out)["job_id"] == JOB
    assert posted(transport) == ("/api/v1/esaf/init-factory", {
        "folder": FOLDER, "approved": True, "creation_request": CREATION, "scale_set_settings": BYO,
        "project_settings": PROJECT})


def test_one_file_can_hold_the_whole_example(monkeypatch, capsys, tmp_path):
    """--request-json: one file with creation_request, scale_set_settings and project_settings, the REST body's own
    field names (and the keyword arguments of esaf.init_factory)."""
    example = {"creation_request": CREATION, "scale_set_settings": BYO, "project_settings": PROJECT}
    code, transport = run_cli(monkeypatch, "--request-json", write(tmp_path, "create-factory.json", example))
    assert code == 0 and json.loads(capsys.readouterr().out)["job_id"] == JOB
    assert posted(transport)[1] == {"folder": FOLDER, "approved": True, **example}
    transport = Transport()
    esaf.connect(folder=FOLDER, client=transport)
    esaf.init_factory(**example)
    assert posted(transport)[1] == {"folder": FOLDER, "approved": True, **example}


def test_the_one_file_cannot_be_combined_with_the_separate_files(monkeypatch, capsys, tmp_path):
    example = {"creation_request": CREATION, "project_settings": PROJECT}
    code, transport = run_cli(monkeypatch, "--request-json", write(tmp_path, "create-factory.json", example),
                              "--project-settings-json", write(tmp_path, "project-settings.json", PROJECT))
    assert code != 0 and transport.calls == []
    assert "--request-json" in capsys.readouterr().err


def test_the_one_file_names_an_unknown_field(monkeypatch, capsys, tmp_path):
    example = {"creation_request": CREATION, "scaleset_settings": BYO}
    code, transport = run_cli(monkeypatch, "--request-json", write(tmp_path, "create-factory.json", example))
    assert code != 0 and transport.calls == []
    assert "scaleset_settings" in capsys.readouterr().err


def test_a_settings_file_must_hold_an_object(monkeypatch, capsys, tmp_path):
    code, transport = run_cli(monkeypatch, "--creation-request-json", write(tmp_path, "creation-request.json", CREATION),
                              "--scale-set-settings-json", write(tmp_path, "scale-set-settings.json", ["BYO_subnets"]))
    assert code != 0 and transport.calls == []
    assert "--scale-set-settings-json" in capsys.readouterr().err
