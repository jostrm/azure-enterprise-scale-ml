import copy

import pytest

from azurefactory import AzureFactoryClient, ConfigError
from azurefactory.cli import main
from azurefactory.review import write_receipt
from test_reviews import automatic_project_review, future


FACTORY = "11111111-1111-4111-8111-111111111111"
SCALE = "22222222-2222-4222-8222-222222222222"
PROJECT = "33333333-3333-4333-8333-333333333333"
REVISION = "a" * 64


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def request(self, method, path, *, body=None, **kwargs):
        calls.append((method, path, copy.deepcopy(body)))
        return {"can_execute": False, "blockers": ["Offline blocked preview"]}

    monkeypatch.setattr(AzureFactoryClient, "request", request)
    return calls


@pytest.mark.parametrize("method,kwargs,expected", [
    ("factory_clone_prepare", {"prefix": "new-", "include_projects": "all"},
     {"action": "clone", "target_prefix": "new-", "include_projects": "all"}),
    ("scaleset_add_prepare", {"scale_sets": [{"environment": "stage", "enabled": False}]},
     {"action": "create-scale-set", "scale_sets": [{"environment": "stage", "enabled": False}]}),
    ("project_add_prepare", {"number": "002", "environments": ["dev", "prod"], "settings": {"enableRedisCache": False}},
     {"action": "add-project", "project": {"number": "002", "display_name": "", "placements": [
         {"environment": "dev"}, {"environment": "prod"}]}, "settings": {"enableRedisCache": False}}),
    ("project_add_placements_prepare", {"project_id": PROJECT, "placements": [{"environment": "stage", "scale_set_id": SCALE}]},
     {"action": "add-project-placements", "project_id": PROJECT, "placements": [{"environment": "stage", "scale_set_id": SCALE}]}),
    ("project_delete_prepare", {"project_id": PROJECT, "environments": ["stage"],
                               "include_project_subnets": False, "include_keyvault_and_resource_group": True},
     {"action": "delete-project", "project_id": PROJECT, "deletion_options": {"environments": ["stage"],
      "include_project_subnets": False, "include_keyvault_and_resource_group": True}}),
    ("scaleset_delete_prepare", {"scale_set_id": SCALE},
     {"action": "delete-scale-set", "scale_set_id": SCALE}),
    ("draft_remove_prepare", {"kind": "project", "project_id": PROJECT},
     {"action": "delete-draft-project", "project_id": PROJECT}),
    ("draft_remove_prepare", {"kind": "scale-set", "scale_set_id": SCALE},
     {"action": "delete-draft-scale-set", "scale_set_id": SCALE}),
    ("draft_remove_prepare", {"kind": "factory"}, {"action": "delete-draft-factory"}),
])
def test_wrappers_prepare_once_preserve_wire_values(captured, method, kwargs, expected):
    original = copy.deepcopy(kwargs)
    result = getattr(AzureFactoryClient(), method)("folder", FACTORY, expected_revision=REVISION, **kwargs)
    assert result["can_execute"] is False
    assert kwargs == original
    assert captured == [("POST", "/api/v1/factory-catalog/prepare", {
        "folder": "folder", "contract_version": 1, "factory_id": FACTORY,
        "expected_revision": REVISION, **expected})]


@pytest.mark.parametrize("selection", [{}, {"environments": []}, {"placements": []},
    {"environments": ["dev"], "placements": [{"environment": "dev", "scale_set_id": SCALE}]}])
def test_project_selection_requires_one_explicit_source(captured, selection):
    with pytest.raises(ConfigError):
        AzureFactoryClient().project_add_prepare("folder", FACTORY, number="002", **selection)
    assert captured == []


def test_omitted_scale_requires_supporting_resolution(monkeypatch):
    request, preview = automatic_project_review()
    del request["project"]["placements"][0]["scale_set_id"]
    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", lambda self, body: preview)
    assert AzureFactoryClient().review_catalog_prepare(request) == preview
    del preview["capabilities"]
    with pytest.raises(ConfigError, match="supporting API"):
        AzureFactoryClient().review_catalog_prepare(request)


@pytest.mark.parametrize("command", ["add", "add-placements"])
def test_cli_explicit_environment_omits_scale_id(captured, capsys, command):
    args = ["project", command, "--folder", "folder", "--factory-id", FACTORY,
            "--environment", "dev", "--environment", "stage"]
    args += ["--number", "002"] if command == "add" else ["--project-id", PROJECT]
    assert main(args) == 3
    capsys.readouterr()
    body = captured[0][2]
    definition = body["project"] if command == "add" else body
    assert definition["placements"] == [{"environment": "dev"}, {"environment": "stage"}]


@pytest.mark.parametrize("options", [[], ["--environment", "dev", "--placement", "dev=" + SCALE]])
def test_cli_missing_or_ambiguous_selection_fails_before_io(captured, options):
    with pytest.raises(SystemExit):
        main(["project", "add", "--folder", "folder", "--factory-id", FACTORY, "--number", "002", *options])
    assert captured == []


def destructive_review(action="delete-project"):
    request = {"folder": "folder", "contract_version": 1, "action": action,
               "factory_id": FACTORY, "expected_revision": REVISION}
    if action == "delete-project":
        request.update(project_id=PROJECT, deletion_options={"environments": ["dev"],
            "include_project_subnets": False, "include_keyvault_and_resource_group": False})
    elif action in {"delete-scale-set", "delete-draft-scale-set"}:
        request["scale_set_id"] = SCALE
    elif action == "delete-draft-project":
        request["project_id"] = PROJECT
    preview = {"contract_version": 1, "confirmation_id": PROJECT, "can_execute": True,
        "expires_at": future(), "blockers": [], "source_revision": REVISION,
        "operation_mode": "configuration" if "draft" in action else "runtime",
        "target": {"id": FACTORY}, "factory_id": FACTORY,
        "scale_set_id": request.get("scale_set_id"), "project_id": request.get("project_id"),
        "deletion_options": request.get("deletion_options"), "capabilities": ["draft-lifecycle-v1"],
        "effects": ["Reviewed removal"], "deletion_targets": []}
    return request, preview


@pytest.mark.parametrize("action,operation", [
    ("delete-project", "project-delete"), ("delete-scale-set", "scaleset-delete"),
    ("delete-draft-factory", "draft-remove-factory"), ("delete-draft-scale-set", "draft-remove-scale-set"),
    ("delete-draft-project", "draft-remove-project")])
@pytest.mark.parametrize("field,value", [("operation_mode", "wrong"), ("factory_id", SCALE),
    ("project_id", FACTORY), ("scale_set_id", PROJECT), ("source_revision", "b" * 64),
    ("target", {}), ("deletion_options", {"include_project_subnets": True})])
def test_destructive_receipt_binds_exact_review(tmp_path, action, operation, field, value):
    request, preview = destructive_review(action)
    preview[field] = value
    with pytest.raises(ConfigError):
        write_receipt(str(tmp_path / "review.json"), client=AzureFactoryClient(), purpose="catalog-confirm",
                      operation=operation, request_body=request, preview=preview)


def test_project_delete_cli_requires_independent_choices(captured, capsys):
    base = ["project", "delete", "--folder", "folder", "--factory-id", FACTORY,
            "--project-id", PROJECT, "--expected-revision", REVISION, "--environment", "dev"]
    with pytest.raises(SystemExit):
        main(base + ["--include-project-subnets", "no"])
    assert not captured
    assert main(base + ["--include-project-subnets", "no", "--include-keyvault-and-resource-group", "yes"]) == 3
    capsys.readouterr()
    assert captured[0][2]["deletion_options"] == {"environments": ["dev"],
        "include_project_subnets": False, "include_keyvault_and_resource_group": True}


def test_deletion_receipt_uses_runtime_confirmation_only(monkeypatch, tmp_path, capsys):
    request, preview = destructive_review()
    calls = []
    monkeypatch.setattr(AzureFactoryClient, "catalog_prepare", lambda self, body: preview)
    monkeypatch.setattr(AzureFactoryClient, "catalog_confirm",
                        lambda self, folder, confirmation: calls.append(confirmation) or {
                            "contract_version": 1, "catalog": None, "job": {"id": PROJECT, "status": "queued"}})
    path = tmp_path / "delete.json"
    write_receipt(str(path), client=AzureFactoryClient(), purpose="catalog-confirm", operation="project-delete",
                  request_body=request, preview=preview)
    assert main(["catalog", "confirm", "--receipt", str(path), "--yes"]) == 2
    assert not calls
    assert main(["runtime", "confirm", "--receipt", str(path), "--yes"]) == 0
    assert calls == [PROJECT]
