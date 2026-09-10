import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import api, operations
from src.operations import (
    CONFIG_DEFAULTS,
    ML_METRICS,
    AzureInventoryProvider,
    LocalFactoryDiscovery,
    OperationsService,
    OperationsStore,
    PromptCategorizer,
    azure_region_catalog,
    parse_resource_group_name,
    resolve_azure_cli,
    _normalize_prompt_record,
)


@pytest.fixture
def store(tmp_path):
    return OperationsStore(tmp_path / "operations.db")


def test_region_catalog_is_complete_and_map_safe():
    regions = azure_region_catalog()
    assert len(regions) >= 55
    assert len({region["name"] for region in regions}) == len(regions)
    assert all(-90 <= region["latitude"] <= 90 for region in regions)
    assert all(-180 <= region["longitude"] <= 180 for region in regions)
    assert all(not region["name"].startswith(("china", "usgov")) for region in regions)


def test_local_discovery_and_resource_group_parsing(tmp_path):
    root = tmp_path / "aifactory"
    snapshot = root / "config-wizard" / "project-015" / "project_state.json"
    snapshot.parent.mkdir(parents=True)
    (root / "variables.json").write_text(json.dumps({
        "dev": {
            "dev_sub_id": "sub-dev",
            "admin_aifactoryPrefixRG": "demo-",
            "admin_aifactorySuffixRG": "-007",
            "admin_location": "swedencentral",
        },
        "stage_prod": {
            "test_sub_id": "sub-test",
            "prod_sub_id": "sub-prod",
            "admin_location": "westeurope",
        },
    }), encoding="utf-8")
    snapshot.write_text(json.dumps({
        "project_number_000": "015", "orchestrator": "gha",
    }), encoding="utf-8")

    found = LocalFactoryDiscovery().discover(str(root))
    assert found["name"] == "demo-007"
    assert found["orchestrator"] == "gha"
    assert found["subscriptions"] == {
        "dev": "sub-dev", "stage": "sub-test", "prod": "sub-prod",
    }
    assert found["active_regions"] == ["swedencentral", "westeurope"]
    assert found["project_numbers"] == ["015"]
    assert parse_resource_group_name("demo-project015-test-sdc-rg") == {
        "name": "demo-project015-test-sdc-rg",
        "project_number": "015",
        "environment": "stage",
        "is_common": False,
    }
    assert parse_resource_group_name("demo-common-prod-rg")["is_common"] is True


def _write_orchestrator_snapshot(root, project, orchestrator):
    path = (
        root / "config-wizard" / f"project-{project}" / "project_state.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "project_number_000": project, "orchestrator": orchestrator,
    }), encoding="utf-8")


@pytest.mark.parametrize("current_evidence", ["json", "new_repo", "metadata", "sibling_env"])
def test_mixed_snapshots_use_current_gha_evidence(tmp_path, current_evidence):
    root = tmp_path / "aifactory"
    root.mkdir()
    dev = {"admin_location": "eastus2"}
    if current_evidence == "json":
        dev["GITHUB_USERNAME"] = "octocat"
    elif current_evidence == "new_repo":
        dev["GITHUB_NEW_REPO"] = "example/repository"
    elif current_evidence == "sibling_env":
        (root.parent / ".env").write_text(
            "GITHUB_USERNAME=octocat\n", encoding="utf-8"
        )
    document = {"dev": dev, "stage_prod": {}}
    if current_evidence == "metadata":
        document["_wizard"] = {"orchestrator": "gha"}
    (root / "variables.json").write_text(json.dumps(document), encoding="utf-8")
    _write_orchestrator_snapshot(root, "001", "ado")
    _write_orchestrator_snapshot(root, "002", "gha")
    _write_orchestrator_snapshot(root, "003", "ado")

    assert LocalFactoryDiscovery().discover(str(root))["orchestrator"] == "gha"


def test_generic_github_defaults_do_not_select_gha(tmp_path):
    (tmp_path / "variables.json").write_text(json.dumps({"dev": {
        "GITHUB_USERNAME": "", "GITHUB_NEW_REPO": "",
        "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
        "GITHUB_USE_SSH": "false", "GITHUB_NEW_REPO_VISIBILITY": "public",
    }}), encoding="utf-8")
    assert LocalFactoryDiscovery().discover(str(tmp_path))["orchestrator"] == "ado"


def test_mixed_snapshots_use_clear_ado_majority(tmp_path):
    root = tmp_path / "aifactory"
    root.mkdir()
    (root / "variables.json").write_text(
        json.dumps({"dev": {}, "stage_prod": {}}), encoding="utf-8"
    )
    _write_orchestrator_snapshot(root, "001", "ado")
    _write_orchestrator_snapshot(root, "002", "gha")
    _write_orchestrator_snapshot(root, "003", "ado")

    assert LocalFactoryDiscovery().discover(str(root))["orchestrator"] == "ado"


def test_current_project_snapshot_wins_over_history(tmp_path):
    root = tmp_path / "aifactory"
    root.mkdir()
    (root / "variables.json").write_text(json.dumps({
        "dev": {"project_number_000": "009"}, "stage_prod": {},
    }), encoding="utf-8")
    _write_orchestrator_snapshot(root, "001", "ado")
    _write_orchestrator_snapshot(root, "002", "ado")
    _write_orchestrator_snapshot(root, "009", "gha")

    assert LocalFactoryDiscovery().discover(str(root))["orchestrator"] == "gha"


def test_store_schema_config_merges_and_draft_actions(store, tmp_path):
    for kind in CONFIG_DEFAULTS:
        loaded = store.load_config(str(tmp_path), "001", "dev", kind)
        assert loaded["is_saved"] is False
        saved = store.save_config(
            str(tmp_path), "001", "dev", kind, {"frequency": "monthly"}
        )
        assert saved["is_saved"] is True
        assert saved["config"]["frequency"] == "monthly"
        assert set(CONFIG_DEFAULTS[kind]) <= set(saved["config"])

    action = store.create_action_request(
        str(tmp_path), "clone", "westeurope", "swedencentral"
    )
    project_action = store.create_project_action(
        str(tmp_path), "001", "dev", "stage", "promote"
    )
    assert action["status"] == project_action["status"] == "draft"
    assert "no Azure resources were changed" in action["message"]
    with sqlite3.connect(store.db_path) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {
        "operation_configs", "monitoring_snapshots",
        "factory_action_requests", "prompt_records",
    } <= tables
    assert all(len(values) == 10 for values in ML_METRICS.values())


@pytest.mark.parametrize(
    ("prompt", "category"),
    [
        ("Fix this Python function and tests", "Coding"),
        ("Analyze a SQL dataframe", "Data/Analytics"),
        ("Detect model drift and retrain", "MLOps"),
        ("Investigate production latency telemetry", "Operations"),
        ("Review RBAC security policy", "Security/Governance"),
        ("Tune vector retrieval for RAG", "Search/RAG"),
        ("Rewrite this email", "Content/Communication"),
        ("Plan the roadmap", "Planning"),
        ("Hello there", "General"),
    ],
)
def test_prompt_categorizer_is_deterministic_and_local(prompt, category):
    result = PromptCategorizer().categorize(prompt)
    assert result["category"] == category
    assert 0 <= result["confidence"] <= 1
    assert result == PromptCategorizer().categorize(prompt)


def test_prompt_store_filters_and_token_shapes(store, tmp_path):
    folder = str(tmp_path)
    rows = [
        {
            "operation_id": "op-1", "response_id": "response-1",
            "timestamp": "2026-09-01T10:00:00Z", "project_number": "001",
            "environment": "dev", "model": "gpt-4o", "category": "Coding",
            "prompt": "write python", "response": "done", "input_tokens": 100,
            "cached_input_tokens": 25, "output_tokens": 40, "success": True,
            "source": "azure",
        },
        {
            "operation_id": "op-2", "response_id": "response-2",
            "timestamp": "2026-09-02T10:00:00Z", "project_number": "002",
            "environment": "prod", "model": "gpt-4.1", "category": "Operations",
            "prompt": "monitor error", "response": "", "input_tokens": 20,
            "cached_input_tokens": 0, "output_tokens": 0, "success": False,
            "error_type": "timeout", "source": "azure",
        },
    ]
    assert store.upsert_prompt_records(folder, rows) == 2
    result = store.query_prompt_records(
        folder, project_number="001", model="gpt-4o",
        search="python", success=True,
    )
    assert result["total"] == 1
    assert result["rows"][0]["total_tokens"] == 140
    assert result["rows"][0]["cached_input_tokens"] == 25


def test_idless_prompt_records_have_stable_noncolliding_synthetic_ids():
    row = {
        "timestamp": "2026-09-05T12:00:00Z",
        "response_id": "response-42",
        "model": "gpt-4.1-mini",
        "prompt": "Summarize this report",
        "response": "Summary",
        "input_tokens": 25,
        "output_tokens": 10,
        "latency_ms": 120,
        "source": "azure",
    }

    first = _normalize_prompt_record(row)
    repeated = _normalize_prompt_record(dict(row))
    changed_prompt = _normalize_prompt_record({
        **row, "prompt": "Summarize this different report",
    })
    changed_timestamp = _normalize_prompt_record({
        **row, "timestamp": "2026-09-05T12:00:01Z",
    })

    assert first["operation_id"].startswith("synthetic-")
    assert repeated["operation_id"] == first["operation_id"]
    assert changed_prompt["operation_id"] != first["operation_id"]
    assert changed_timestamp["operation_id"] != first["operation_id"]
    assert _normalize_prompt_record({
        **row, "operation_id": "explicit-operation",
    })["operation_id"] == "explicit-operation"


def test_real_shaped_telemetry_parsing():
    rows = [{
        "TimeGenerated": "2026-09-01T10:00:00Z",
        "OperationId": "operation-1",
        "DurationMs": 321.5,
        "Success": True,
        "Properties": json.dumps({
            "gen_ai.conversation.id": "conversation-1",
            "gen_ai.response.id": "response-1",
            "gen_ai.request.model": "gpt-4o",
            "gen_ai.usage.input_tokens": "120",
            "gen_ai.usage.cache_read.input_tokens": "30",
            "gen_ai.usage.output_tokens": "45",
            "gen_ai.input.messages": json.dumps([
                {"role": "user", "content": "Write Python code"}
            ]),
            "gen_ai.output.messages": json.dumps([
                {"role": "assistant", "content": "Here is code"}
            ]),
        }),
    }]
    parsed = AzureInventoryProvider.parse_telemetry_rows(
        rows, {"source": "azure", "project_number": "015", "environment": "dev"}
    )
    assert parsed[0]["operation_id"] == "operation-1"
    assert parsed[0]["input_tokens"] == 120
    assert parsed[0]["cached_input_tokens"] == 30
    assert parsed[0]["output_tokens"] == 45
    assert parsed[0]["total_tokens"] == 165
    assert "Write Python code" in parsed[0]["prompt"]
    assert "Here is code" in parsed[0]["response"]


def test_inventory_cache_and_unavailable_fallback(store, tmp_path):
    def fail(*args, **kwargs):
        raise FileNotFoundError("az unavailable")

    provider = AzureInventoryProvider(store, runner=fail)
    unavailable = provider.get_inventory(str(tmp_path), ["sub"], force_refresh=True)
    assert unavailable["source"] == "unavailable"
    assert unavailable["resources"] == []
    assert "az unavailable" in unavailable["warning"]
    store.save_snapshot(str(tmp_path), "azure", {
        "source": "azure", "resources": [{"name": "real"}],
        "resource_groups": [], "subscriptions": ["sub"],
        "telemetry": {"prompt_records": []},
        "configuration_scope": {
            "telemetry_auth_scope": "explicit-token-https-v3",
            "telemetry_query_schema": "endpoint-specific-tables-v1",
            "monitoring_targets": [], "monitoring_regions": [],
            "subscriptions": ["sub"], "subscription_tenants": {}, "tenant_ids": [], "prefix": "", "suffix": "",
        },
    })
    cached = provider.get_inventory(str(tmp_path), ["sub"], force_refresh=True)
    assert cached["source"] == "cached"
    assert cached["resources"][0]["name"] == "real"
    assert cached["warning"]


def test_inventory_group_filter_requires_factory_identity(store):
    provider = AzureInventoryProvider(store, runner=lambda *_args, **_kwargs: None)
    factory = {
        "prefix_rg": "gh-", "suffix_rg": "-001",
        "project_numbers": ["003"],
    }
    assert provider._is_relevant_group(
        "gh-esml-common-eus2-dev-001", factory
    )
    assert provider._is_relevant_group(
        "gh-esml-project003-eus2-dev-001", factory
    )
    assert not provider._is_relevant_group(
        "mrvel-1-esml-common-eus2-dev-001", factory
    )
    assert not provider._is_relevant_group(
        "other-project003-eus2-dev-002", factory
    )


def test_service_aggregates_all_telemetry_charts(store, tmp_path):
    service = OperationsService(store=store)
    result = service.overview(str(tmp_path), include_azure=False)
    monitoring = result["monitoring"]
    assert {
        "resources_by_service_type", "resources_by_environment",
        "resources_by_region", "top_resource_groups", "provisioning_state",
        "requests_over_time", "tokens_over_time", "requests_by_model",
        "tokens_by_model", "success_error_rate", "latency_trend",
    } <= set(monitoring)
    assert monitoring["tokens_over_time"]["series"].keys() == {
        "input", "cached_input", "output",
    }
    assert result["prompt_summary"]["source"] == "mock"


def test_operations_endpoints_auth_validation_and_shapes(monkeypatch, tmp_path):
    monkeypatch.setenv(api.API_KEY_ENV, "key")
    monkeypatch.setenv("AIFACTORY_OPERATIONS_DB", str(tmp_path / "api-ops.db"))
    headers = {"X-API-Key": "key"}
    with TestClient(api.app) as client:
        assert client.get("/api/v1/operations/regions").status_code == 401
        regions = client.get("/api/v1/operations/regions", headers=headers)
        overview = client.post(
            "/api/v1/operations/overview", headers=headers,
            json={"aifactory_folder": str(tmp_path), "include_azure": False},
        )
        saved = client.post(
            "/api/v1/operations/config/save", headers=headers,
            json={
                "aifactory_folder": str(tmp_path), "project_number": "001",
                "environment": "dev", "kind": "rag",
                "config": {"retrieval_top_k": 10},
            },
        )
        draft = client.post(
            "/api/v1/operations/factory-actions", headers=headers,
            json={
                "aifactory_folder": str(tmp_path), "action": "create",
                "target_region": "swedencentral",
            },
        )
        invalid = client.post(
            "/api/v1/operations/prompts/search", headers=headers,
            json={"aifactory_folder": str(tmp_path), "limit": 501},
        )
        prompts = client.post(
            "/api/v1/operations/prompts/search", headers=headers,
            json={"aifactory_folder": str(tmp_path), "limit": 5},
        )
    assert regions.json()["count"] >= 55
    assert overview.json()["source"] == "mock"
    assert "monitoring" in overview.json()
    assert saved.json()["config"]["retrieval_top_k"] == 10
    assert draft.json()["status"] == "draft"
    assert invalid.status_code == 422
    assert prompts.json()["source"] == "mock"
    assert len(prompts.json()["rows"]) == 5


def test_azure_runner_never_uses_shell(store, tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    provider = AzureInventoryProvider(store, runner=runner)
    result = provider.get_inventory(str(tmp_path), ["sub"], force_refresh=True)
    assert result["source"] == "azure"
    assert calls
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert all(argv[0] == "az" for argv, _ in calls)
    assert not any(
        verb in argv for argv, _ in calls
        for verb in ("create", "delete", "update", "deploy")
    )


def test_windows_azure_cli_cmd_is_resolved_and_run_without_shell(
    monkeypatch, store, tmp_path
):
    cli_root = tmp_path / "CLI2"
    windows_cli = cli_root / "wbin" / "az.cmd"
    windows_cli.parent.mkdir(parents=True)
    windows_cli.write_text("@echo off", encoding="utf-8")
    bundled_python = cli_root / "python.exe"
    bundled_python.write_bytes(b"test")
    probes = []

    def which(name):
        probes.append(name)
        return str(windows_cli) if name == "az.cmd" else None

    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    monkeypatch.setattr(operations.sys, "platform", "win32")
    monkeypatch.setattr(operations.shutil, "which", which)
    resolved = resolve_azure_cli()
    provider = AzureInventoryProvider(store, runner=runner, azure_cli=resolved)
    result = provider.get_inventory(str(tmp_path), ["sub"], force_refresh=True)

    assert probes[:2] == ["az.exe", "az.cmd"]
    assert result["source"] == "azure"
    assert all(
        argv[:3] == [str(bundled_python), "-IBm", "azure.cli"]
        for argv, _ in calls
    )
    assert all(kwargs["shell"] is False for _, kwargs in calls)


def test_missing_azure_cli_has_actionable_error(monkeypatch):
    monkeypatch.setattr(operations.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="not found on PATH.*Install Azure CLI"):
        resolve_azure_cli()
