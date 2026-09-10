import base64
import copy
import gc
import io
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src import api, operations, simple_mode as sm
from src.ticket_connectors import TicketError


SUB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENANT = "11111111-1111-4111-8111-111111111111"
OID = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
NOW = 1800000000.0
SHA = "a" * 40
CATALOG = {
    "hub": [
        {"id": "virtual-network", "label": "Private virtual network", "description": "Integrated Dev /20.", "required": True, "default_selected": True, "dependencies": []},
        {"id": "private-dns", "label": "Private DNS", "description": "Private zones and resolver.", "required": True, "default_selected": True, "dependencies": ["virtual-network"]},
    ],
    "common": [
        {"id": "log-analytics", "label": "Log Analytics", "description": "Common diagnostic workspace.", "required": True, "default_selected": True, "dependencies": []},
    ],
    "project": [
        {"id": "storage", "label": "Project Storage", "description": "Standard_LRS private storage.", "required": True, "default_selected": True, "dependencies": ["private-dns"]},
        {"id": "key-vault", "label": "Project Key Vault", "description": "Standard private vault.", "required": True, "default_selected": True, "dependencies": ["private-dns"]},
        {"id": "managed-identities", "label": "Project managed identities", "description": "Baseline project RBAC.", "required": True, "default_selected": True, "dependencies": []},
        {"id": "foundry", "label": "Foundry", "description": "S0 account and project.", "required": False, "default_selected": True, "dependencies": ["storage", "key-vault", "managed-identities"]},
        {"id": "ai-search", "label": "AI Search", "description": "Standard search.", "required": False, "default_selected": True, "dependencies": ["managed-identities"]},
        {"id": "application-insights", "label": "Application Insights", "description": "Optional project telemetry.", "required": False, "default_selected": True, "dependencies": ["log-analytics"]},
    ],
}
DEFAULT_RESOURCES = ["foundry", "ai-search", "application-insights"]


def http(value, status=200, scopes="repo, workflow"):
    return f"HTTP/2.0 {status} response\r\nX-OAuth-Scopes: {scopes}\r\n\r\n" + json.dumps(value)


class FakeCLI:
    def __init__(self):
        self.calls = []
        self.login = "octocat"
        self.oid = OID
        self.expiry = NOW + 3600
        self.tenant = TENANT
        self.scopes = "repo, workflow"
        self.repository_status = 404
        self.repo = {"id": 42, "full_name": "octocat/aifaifactory-001", "private": True,
                     "archived": False, "size": 0, "permissions": {"admin": True}}
        self.refs = []
        self.roles = [{"role": "Owner", "scope": f"/subscriptions/{SUB}", "condition": None}]
        self.membership = {"role": "admin", "state": "active"}
        self.source_dirty = ""
        self.remote_sha = SHA
        self.published_files = {}

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        assert kwargs["shell"] is False
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert not {"GH_TOKEN", "GITHUB_TOKEN", "AIF_DRY_RUN", "BASH_ENV"} & kwargs["env"].keys()
        assert not any(word in argv for word in ("login", "logout", "create", "push", "deploy", "dispatch"))
        code = 0
        if argv[0] == "az" and argv[1:3] == ["account", "list"]:
            result = [{"id": SUB, "tenantId": self.tenant, "name": "Development",
                       "accountName": "dev@example.org", "isDefault": True, "state": "Enabled"}]
        elif argv[0] == "az" and argv[1:3] == ["account", "get-access-token"]:
            claims = {"tid": self.tenant, "oid": self.oid, "exp": self.expiry, "aud": "https://management.azure.com/"}
            payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
            result = {"tenant": self.tenant, "accessToken": "e30." + payload + ".test-only"}
        elif argv[0] == "az" and argv[1:4] == ["role", "assignment", "list"]:
            result = self.roles
        elif argv[0] == "gh" and argv[-1] == "user":
            return SimpleNamespace(returncode=0, stdout=http({"login": self.login}, scopes=self.scopes), stderr="")
        elif argv[0] == "gh" and argv[-1].startswith("user/memberships/orgs/"):
            result = self.membership
        elif argv[0] == "gh" and argv[-1].endswith("/git/matching-refs/"):
            return SimpleNamespace(returncode=0, stdout=http(self.refs), stderr="")
        elif argv[0] == "gh" and argv[-1].startswith("repos/"):
            return SimpleNamespace(returncode=0 if self.repository_status == 200 else 1,
                                   stdout=http(self.repo, self.repository_status), stderr="sensitive never echoed")
        elif argv[0] == "git":
            if "rev-parse" in argv:
                value = SHA
            elif "status" in argv:
                value = self.source_dirty
            elif "ls-remote" in argv:
                value = f"{self.remote_sha}\t{argv[-1]}"
            elif "show" in argv:
                ref, path = argv[-1].split(":", 1)
                if ref != SHA or path not in self.published_files:
                    return SimpleNamespace(returncode=1, stdout="", stderr="not fetched")
                value = self.published_files[path]
            elif "cat-file" in argv:
                value = ""
            else:
                pytest.fail(f"Unexpected git read: {argv}")
            return SimpleNamespace(returncode=0, stdout=value, stderr="")
        else:
            pytest.fail(f"Unexpected command: {argv}")
        return SimpleNamespace(returncode=code, stdout=json.dumps(result), stderr="")


@pytest.fixture(autouse=True)
def no_real_side_effects(monkeypatch):
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=AssertionError("No real CLI calls")))
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=AssertionError("No real bootstrap launches")))
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("No live network")))
    sm._LIVE_JOBS.clear()
    yield
    sm._LIVE_JOBS.clear()


def test_accelerator_root_honors_bundled_source(monkeypatch, tmp_path):
    root = tmp_path / "accelerator"
    monkeypatch.setenv("AIFACTORY_ACCELERATOR_ROOT", str(root))
    assert sm.accelerator_root() == root


@pytest.fixture
def context(tmp_path, monkeypatch):
    # Isolate system-path protection from pytest's default LocalAppData temp root.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "protected-local-appdata"))
    # Ignore only the real outer .git marker; nested destination repos are real.
    outer_git = sm.APP_ROOT / ".git"
    monkeypatch.setattr(sm, "_git_marker_exists", lambda p: p != outer_git and p.exists())
    monkeypatch.setattr(sm, "APP_ROOT", tmp_path / "protected-app")
    runner = FakeCLI()
    cli = sm.ReadOnlyCLI(runner)
    source_state = {"blockers": [], "fingerprint": "source-v2", "commit": SHA, "branch": "release/v1.24",
                    "preset": {"preset": "authoritative-purple-test-preset", "contractVersion": 2,
                               "resourceCatalog": copy.deepcopy(CATALOG)}}
    source = SimpleNamespace(check=lambda version=None: {
        **copy.deepcopy(source_state), "branch": sm.release_version.branch_for(version or "124"),
    }, manifest=lambda: copy.deepcopy(source_state["preset"]))
    work = []
    process = SimpleNamespace(
        stdout=io.StringIO("AIF_SIMPLE_STAGE=common\nAIF_SIMPLE_STAGE=hub\nAIF_SIMPLE_STAGE=project\nAIF_SIMPLE_STAGE=completed\n"),
        wait=lambda: 0, poll=lambda: 0, pid=98765, kill=Mock(),
    )
    popen = Mock(return_value=process)
    clock = [NOW]
    store = operations.OperationsStore(tmp_path / "operations.db")
    service = sm.SimpleModeService(store, cli=cli, source=source, clock=lambda: clock[0],
                                   popen=popen, dispatch=work.append)
    data = {
        "subscription_id": SUB, "tenant_id": TENANT, "location": "swedencentral",
        "factory_prefix": "aif-", "github_repository": "octocat/aifaifactory-001",
        "team_member_email": "dev@example.org", "team_group_name": "aif-prj001-team",
        "cost_center": "123456", "repo_root": str(tmp_path / "AI Factories" / "aifaifactory-001"),
    }
    return SimpleNamespace(service=service, runner=runner, cli=cli, source=source_state,
                           data=data, work=work, popen=popen, process=process, clock=clock, root=tmp_path)


def preview(c):
    plan = c.service.prepare(c.data)
    assert plan["can_execute"], plan["blockers"]
    return plan


def test_options_read_only_derived_and_stable(context):
    c = context
    gc.collect()
    before = set(c.root.rglob("*"))
    first = c.service.options()
    assert c.service.options() == first
    assert set(c.root.rglob("*")) == before
    assert not c.service._ready
    assert first["github_account"] == "octocat"
    assert first["defaults"]["github_repository"] == "octocat/aifaifactory-001"
    assert first["defaults"]["team_member_email"] == "dev@example.org"
    assert first["defaults"]["tenant_id"] == TENANT
    assert first["defaults"]["cost_center"] == "123456"
    assert first["azure_accounts"][0]["subscription_name"] == "Development"
    assert "is_default" not in first["azure_accounts"][0]
    assert "swedencentral" in first["regions"]
    assert "not fully verified" in " ".join(first["warnings"])
    c.popen.assert_not_called()


def test_options_auth_failure_does_not_fake_success(context):
    context.runner.expiry = NOW - 1
    context.runner.scopes = ""
    options = context.service.options()
    assert any("token could not be verified" in item for item in options["warnings"])


def test_options_exposes_catalog_even_without_azure_or_github_auth(context, monkeypatch):
    c = context
    monkeypatch.setattr(c.cli, "accounts", Mock(side_effect=TicketError("Not signed in")))
    monkeypatch.setattr(c.cli, "github", Mock(side_effect=TicketError("Not signed in")))
    result = c.service.options()
    assert result["resource_catalog"] == CATALOG
    assert result["defaults"]["project_resources"] == DEFAULT_RESOURCES
    assert result["defaults"]["github_visibility"] == "private"
    assert result["github_visibilities"] == ["private", "public"]
    assert not c.service._ready
    assert not c.work
    c.popen.assert_not_called()


def test_legacy_nine_field_request_selects_canonical_defaults(context):
    p = preview(context)
    assert p["github_visibility"] == "private"
    assert p["project_resources"] == DEFAULT_RESOURCES
    assert len(p["resource_catalog"]["project"]) == 6
    assert p["resource_catalog"]["hub"] == CATALOG["hub"]
    assert p["resource_catalog"]["common"] == CATALOG["common"]


@pytest.mark.parametrize("selected", [[], ["ai-search"], ["foundry"], ["application-insights"]])
def test_optional_selection_never_removes_required_resources_or_reenables_others(context, selected):
    c = context
    c.data["project_resources"] = selected
    p = preview(c)
    assert p["project_resources"] == selected
    assert {i["id"] for i in p["resource_catalog"]["project"]} == sm.REQUIRED_PROJECT_RESOURCES | set(selected)
    assert json.loads(p["environment"]["AIF_SIMPLE_PROJECT_RESOURCES_JSON"]) == selected
    project_effects = p["effects"][p["effects"].index("Project 001 resources (required plus selected optional):") + 1:]
    for item in CATALOG["project"]:
        assert any(effect.startswith(item["label"] + " - ") for effect in project_effects) is (item["required"] or item["id"] in selected)


@pytest.mark.parametrize("value", [["storage"], ["key-vault"], ["managed-identities"], ["unknown-service"],
                                  ["foundry", "foundry"], ["foundry;exit"], [True], [1], "foundry", {}, None])
def test_resource_ids_strict_and_foundations_cannot_be_supplied_or_overridden(context, value):
    c = context
    c.data["project_resources"] = value
    with pytest.raises(TicketError):
        c.service.prepare(c.data)
    assert not c.runner.calls
    c.popen.assert_not_called()


def test_resource_dependencies_rejected_not_silently_enabled(context):
    c = context
    search = next(i for i in c.source["preset"]["resourceCatalog"]["project"] if i["id"] == "ai-search")
    search["dependencies"].append("foundry")
    c.data["project_resources"] = ["ai-search"]
    with pytest.raises(TicketError, match="requires selected dependencies: foundry"):
        c.service.prepare(c.data)
    assert not c.runner.calls
    c.data["project_resources"] = ["ai-search", "foundry"]
    p = preview(c)
    assert p["project_resources"] == ["foundry", "ai-search"]


def test_invalid_required_catalog_fails_closed(context):
    c = context
    c.source["preset"]["resourceCatalog"]["project"][0]["required"] = False
    options = c.service.options()
    assert options["resource_catalog"] == {"hub": [], "common": [], "project": []}
    c.runner.calls.clear()
    with pytest.raises(TicketError, match="catalog is invalid"):
        c.service.prepare(c.data)
    assert not c.runner.calls


def test_old_v1_or_unavailable_catalog_cannot_execute_even_legacy_request(context):
    c = context
    c.source["preset"] = {"preset": "old", "contractVersion": 1}
    options = c.service.options()
    assert options["resource_catalog"] == {"hub": [], "common": [], "project": []}
    assert options["defaults"]["project_resources"] == []
    assert "v2" in " ".join(options["warnings"])
    p = c.service.prepare(c.data)
    assert not p["can_execute"]
    assert "capability v2" in " ".join(p["blockers"])
    with pytest.raises(TicketError):
        c.service.start(p["confirmation_id"])
    c.popen.assert_not_called()


@pytest.mark.parametrize("visibility", ["private", "public"])
@pytest.mark.parametrize("existing", [False, True])
def test_selected_repository_visibility_is_exact_and_read_only(context, visibility, existing):
    c = context
    c.data["github_visibility"] = visibility
    c.runner.repository_status = 200 if existing else 404
    c.runner.repo["private"] = visibility == "private"
    p = preview(c)
    assert p["github_visibility"] == visibility
    assert p["environment"]["GITHUB_REPOSITORY_VISIBILITY"] == visibility
    assert f"a {visibility} GitHub repository" in p["effects"][0]
    assert (sm.PUBLIC_REPOSITORY_WARNING in p["warnings"]) is (visibility == "public")
    assert p["environment"]["AIF_NETWORK_MODE"] == "priv"
    assert not c.work
    c.popen.assert_not_called()


@pytest.mark.parametrize("visibility", ["public", "private"])
def test_existing_repo_visibility_mismatch_never_changes_it(context, visibility):
    c = context
    c.data["github_visibility"] = visibility
    c.runner.repository_status = 200
    c.runner.repo["private"] = visibility != "private"
    p = c.service.prepare(c.data)
    assert not p["can_execute"]
    assert "visibility is never changed" in " ".join(p["blockers"])
    c.popen.assert_not_called()


@pytest.mark.parametrize("visibility", ["internal", "Public", "private --public", "", None, True])
def test_invalid_visibility_rejected_before_cli(context, visibility):
    context.data["github_visibility"] = visibility
    with pytest.raises(TicketError):
        context.service.prepare(context.data)
    assert not context.runner.calls


def test_visibility_and_selected_ids_bound_to_original_confirmation(context):
    c = context
    c.data.update(github_visibility="public", project_resources=["ai-search"])
    p = preview(c)
    c.data.update(github_visibility="private", project_resources=["foundry"])
    job = c.service.start(p["confirmation_id"])
    c.work.pop()()
    env = c.popen.call_args.kwargs["env"]
    assert env["GITHUB_REPOSITORY_VISIBILITY"] == "public"
    assert env["AIF_SIMPLE_PROJECT_RESOURCES_JSON"] == '["ai-search"]'
    assert c.service.get_job(job["id"])["status"] == "succeeded"


def test_changed_catalog_invalidates_prepared_selection(context):
    c = context
    p = preview(c)
    c.source["preset"]["resourceCatalog"]["project"][-1]["description"] += " Source changed."
    with pytest.raises(TicketError, match="source"):
        c.service.start(p["confirmation_id"])
    c.popen.assert_not_called()


def require_gateway(c):
    c.source["preset"]["resourceCatalog"]["hub"].append({
        "id": "application-gateway", "label": "Application Gateway WAF_v2",
        "description": "Private HTTPS frontend with an existing Key Vault certificate.",
        "required": True, "default_selected": True, "dependencies": ["virtual-network", "private-dns"],
    })
    c.source["preset"]["requiredInputs"] = [
        {"name": name, "environment": env, "description": "Required gateway metadata."}
        for name, env in sm.GATEWAY_ENV_FIELDS.items()
    ]


def test_required_gateway_missing_inputs_blocks_without_inventing_credentials(context):
    c = context
    require_gateway(c)
    p = c.service.prepare(c.data)
    assert not p["can_execute"]
    assert "required private HTTPS Application Gateway" in " ".join(p["blockers"])
    assert all(name in " ".join(p["blockers"]) for name in sm.GATEWAY_FIELDS)
    assert not any(key.startswith("AIF_APP_GATEWAY_") for key in p["environment"])
    assert "planned, not deployed or verified" in " ".join(p["warnings"])
    assert any(i["id"] == "application-gateway" for i in p["resource_catalog"]["hub"])


def test_gateway_metadata_uses_actual_declared_environment_contract(context):
    c = context
    require_gateway(c)
    c.data.update(app_gateway_backend_fqdn="backend.example.org", app_gateway_hostname="app.example.org",
                  app_gateway_certificate_secret_id="https://existing-vault.vault.azure.net/secrets/tls-certificate")
    p = preview(c)
    for field, env in sm.GATEWAY_ENV_FIELDS.items():
        assert p["environment"][env] == c.data[field]
    assert "PRIVATE KEY" not in json.dumps(p)
    c.popen.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("app_gateway_backend_fqdn", "https://example.org/"),
    ("app_gateway_backend_fqdn", "172.16.2.3"),
    ("app_gateway_hostname", "example.org"),
    ("app_gateway_hostname", "app.privatelink.example.org"),
    ("app_gateway_hostname", "$(hostname).example.org"),
    ("app_gateway_certificate_secret_id", "https://vault.vault.azure.net/secrets/cert/version123"),
    ("app_gateway_certificate_secret_id", "https://vault.vault.azure.net/secrets/cert?sig=secret"),
    ("app_gateway_certificate_secret_id", "-----BEGIN PRIVATE KEY-----"),
])
def test_gateway_fields_accept_identifiers_not_secret_values_or_shell_expressions(context, field, value):
    context.data[field] = value
    with pytest.raises(TicketError):
        context.service.prepare(context.data)
    assert not context.runner.calls


def test_prepare_exact_mapping_and_no_workspace_or_execution(context):
    c = context
    c.data.update(factory_prefix="aifxyz-", team_group_name="aifxyz-prj001-team",
                  github_repository="octocat/custom-factory", cost_center="dept42")
    p = preview(c)
    assert p["script_path"] == str(sm.SCRIPT)
    assert "--non-interactive --yes --repo-root" in p["command"]
    assert "--prepare-only" not in p["command"] and "--no-wait" not in p["command"]
    assert p["environment"] == {
        **sm.FIXED_ENV, **{env: c.data[field] for field, env in sm.ENV_FIELDS.items()},
        "AIF_SUBMODULE_REF": SHA, "AIF_SUBMODULE_BRANCH": "release/v1.24",
        "AIFACTORY_VERSION": "124", "AIFACTORY_VERSION_REVIEWED": "1",
        "GITHUB_REPOSITORY_VISIBILITY": "private",
        "AIF_SIMPLE_PROJECT_RESOURCES_JSON": '["foundry","ai-search","application-insights"]',
    }
    assert not Path(c.data["repo_root"]).exists()
    assert not c.work
    c.popen.assert_not_called()
    assert "Owner or equivalent resource + RBAC + policy" in " ".join(p["requirements"])
    assert "not fully verified" in " ".join(p["warnings"])
    assert "Stage/Prod are not deployed" in " ".join(p["effects"])
    assert "authoritative-purple-test-preset" in " ".join(p["effects"])
    with c.service.store._connect() as db:
        payload = db.execute("SELECT payload FROM simple_mode_plans").fetchone()[0]
    assert "accessToken" not in payload and "e30." not in payload


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "$(whoami)"), ("subscription_id", SUB + ";evil"),
    ("factory_prefix", "aif-;evil"), ("factory_prefix", "AIF-"),
    ("location", "swedencentral\nbad"), ("github_repository", "octocat/repo --public"),
    ("github_repository", "octocat/repo.git"), ("team_group_name", "x&calc"),
    ("team_member_email", "person@example.org;echo"), ("cost_center", "x" * 33),
    ("cost_center", 123456), ("repo_root", "\x00bad"),
])
def test_validation_rejects_injection_before_cli(context, field, value):
    c = context
    c.data[field] = value
    with pytest.raises(TicketError):
        c.service.prepare(c.data)
    assert not c.runner.calls
    c.popen.assert_not_called()


@pytest.mark.parametrize("field", ["password", "pat", "environment", "script_path", "state", "owner"])
def test_extra_fields_rejected_without_echo(context, field):
    with pytest.raises(TicketError) as error:
        context.service.prepare({**context.data, field: "super-secret"})
    assert "super-secret" not in str(error.value)
    assert not context.runner.calls


@pytest.mark.parametrize("case", ["nonempty", "nested-git", "traversal", "relative", "protected", "file", "hidden", "share"])
def test_workspace_safety(context, case):
    c = context
    path = c.root / "destination"
    if case == "nonempty":
        path.mkdir()
        (path / "keep.txt").write_text("must survive")
    elif case == "nested-git":
        path.mkdir()
        (path / ".git").mkdir()
        path = path / "child"
    elif case == "traversal":
        path = path / ".." / "escape"
    elif case == "relative":
        path = Path("relative-factory")
    elif case == "protected":
        path = sm.APP_ROOT / "child"
    elif case == "file":
        path.write_text("must survive")
    elif case == "hidden":
        path = c.root / ".azure" / "factory"
    else:
        path = Path(r"\\server\share\factory")
    p = c.service.prepare({**c.data, "repo_root": str(path)})
    assert not p["can_execute"]
    assert p["blockers"]
    c.popen.assert_not_called()


def test_existing_empty_workspace_allowed_and_bound(context):
    c = context
    Path(c.data["repo_root"]).mkdir(parents=True)
    p = preview(c)
    (Path(c.data["repo_root"]) / "new.txt").write_text("not yours")
    with pytest.raises(TicketError, match="empty"):
        c.service.start(p["confirmation_id"])
    c.popen.assert_not_called()


@pytest.mark.parametrize("mutation", ["source", "publication", "github-login", "azure-identity", "repo", "path", "tenant", "expired-token"])
def test_start_rechecks_identity_source_targets(context, mutation):
    c = context
    p = preview(c)
    if mutation == "source":
        c.source["fingerprint"] = "changed"
    elif mutation == "publication":
        c.source["blockers"] = ["Unpublished"]
    elif mutation == "github-login":
        c.runner.login = "another"
    elif mutation == "azure-identity":
        c.runner.oid = OTHER
    elif mutation == "repo":
        c.runner.repository_status = 200
    elif mutation == "path":
        Path(c.data["repo_root"]).mkdir(parents=True)
    elif mutation == "tenant":
        c.runner.tenant = OTHER
    else:
        c.runner.expiry = NOW - 1
    with pytest.raises(TicketError):
        c.service.start(p["confirmation_id"])
    assert not c.work
    c.popen.assert_not_called()


def test_source_pending_and_expired_plans_cannot_start(context):
    c = context
    c.source["blockers"] = ["Publish the updated purple bootstrap to configured source branch before creation"]
    blocked = c.service.prepare(c.data)
    assert blocked["confirmation_id"] and blocked["command"]
    assert not blocked["can_execute"]
    with pytest.raises(TicketError):
        c.service.start(blocked["confirmation_id"])
    c.source["blockers"] = []
    good = preview(c)
    c.clock[0] += 601
    with pytest.raises(TicketError, match="expired"):
        c.service.start(good["confirmation_id"])
    c.popen.assert_not_called()


def test_scope_tenant_mismatch_is_preview_blocker(context):
    context.data["tenant_id"] = OTHER
    p = context.service.prepare(context.data)
    assert not p["can_execute"]
    assert "subscription/tenant" in " ".join(p["blockers"])


@pytest.mark.parametrize("roles", [
    [{"role": "Contributor", "scope": f"/subscriptions/{SUB}"}],
    [{"role": "Owner", "scope": f"/subscriptions/{SUB}", "condition": "conditional"}],
    [{"role": "Owner", "scope": f"/subscriptions/{SUB}/resourceGroups/one"}],
])
def test_insufficient_or_conditional_roles_not_claimed_verified(context, roles):
    context.runner.roles = roles
    p = context.service.prepare(context.data)
    assert not p["can_execute"]
    assert "resource, RBAC and policy privileges" in " ".join(p["blockers"])


@pytest.mark.parametrize("names", [
    ("Contributor", "User Access Administrator"),
    ("Contributor", "Role Based Access Control Administrator", "Resource Policy Contributor"),
])
def test_separate_resource_rbac_policy_roles_allowed(context, names):
    context.runner.roles = [{"role": name, "scope": f"/subscriptions/{SUB}"} for name in names]
    preview(context)


def test_simple_mode_regions_are_limited_to_bootstrap_supported_choices(context):
    assert context.service.options()["regions"] == list(sm.SUPPORTED_REGIONS)
    context.data["location"] = "australiaeast"
    plan = context.service.prepare(context.data)
    assert not plan["can_execute"]
    assert any("supported Azure region" in message for message in plan["blockers"])
    context.popen.assert_not_called()


def test_zero_exit_without_completed_protocol_is_not_a_successful_factory(context):
    context.process.stdout = io.StringIO("AIF_SIMPLE_STAGE=project\n")
    job = context.service.start(preview(context)["confirmation_id"])
    context.work.pop()()
    result = context.service.get_job(job["id"])
    assert result["status"] == "failed"
    assert result["exit_code"] == 0
    assert "did not report a completed deployment" in result["message"]

@pytest.mark.parametrize("mutation", ["403", "nonempty", "no-admin", "public", "no-scopes", "org-member"])
def test_github_unsafe_or_unverifiable_targets_block(context, mutation):
    c = context
    c.runner.repository_status = 200
    if mutation == "403":
        c.runner.repository_status = 403
    elif mutation == "nonempty":
        c.runner.refs = [{"ref": "refs/heads/main"}]
    elif mutation == "no-admin":
        c.runner.repo["permissions"]["admin"] = False
    elif mutation == "public":
        c.runner.repo["private"] = False
    elif mutation == "no-scopes":
        c.runner.scopes = "repo"
    else:
        c.data["github_repository"] = "anorg/new-factory"
        c.runner.membership["role"] = "member"
    p = c.service.prepare(c.data)
    assert not p["can_execute"]
    assert "sensitive never echoed" not in json.dumps(p)


def test_existing_empty_repo_admin_allowed(context):
    context.runner.repository_status = 200
    preview(context)


def test_empty_repo_structured_409_is_not_generic_failure():
    cli = sm.ReadOnlyCLI(lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=http({"message": "Git Repository is empty."}, 409), stderr=""))
    assert cli.read("gh", ["api", "--include", "repos/a/b/git/matching-refs/"], allow_empty=True) == []
    with pytest.raises(TicketError):
        cli.read("gh", ["api", "user"])


def test_only_confirmed_plan_launches_exact_script_once(context):
    c = context
    with pytest.raises(TicketError):
        c.service.start("not-an-id")
    p = preview(c)
    job = c.service.start(p["confirmation_id"])
    assert job["status"] == "queued"
    assert c.service.start(p["confirmation_id"])["id"] == job["id"]
    assert len(c.work) == 1
    c.popen.assert_not_called()
    c.work.pop()()
    args, kwargs = c.popen.call_args
    assert args[0] == ["bash", str(sm.SCRIPT), "--non-interactive", "--yes", "--repo-root", sm.unix_path(c.data["repo_root"])]
    assert kwargs["shell"] is False and kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["env"]["AIF_SIMPLE_MODE"] == "true"
    completed = c.service.get_job(job["id"])
    assert completed["status"] == "succeeded" and completed["exit_code"] == 0
    assert any("project 001" in event for event in completed["events"])
    assert c.service.start(p["confirmation_id"])["id"] == job["id"]
    assert len(c.work) == 0 and c.popen.call_count == 1


def test_worker_rechecks_before_popen(context):
    c = context
    p = preview(c)
    job = c.service.start(p["confirmation_id"])
    c.source["fingerprint"] = "changed-after-queue"
    c.work.pop()()
    assert c.service.get_job(job["id"])["status"] == "failed"
    c.popen.assert_not_called()


def test_output_never_persists_raw_secrets_and_is_bounded(context):
    c = context
    secret = "ghp_testSecretNeverStoreThis000000000000"
    c.process.stdout = io.StringIO(
        "password=" + secret + "\n"
        + "AIF_SIMPLE_STAGE=common token=" + secret + "\n"
        + "AIF_SIMPLE_STAGE=" + "x" * 10000 + "\n"
        + "eyJ.testJWT.signature\n"
        + ("AIF_SIMPLE_STAGE=common\nAIF_SIMPLE_STAGE=project\n" * 75)
    )
    c.process.wait = lambda: 7
    p = preview(c)
    job = c.service.start(p["confirmation_id"])
    c.work.pop()()
    result = c.service.get_job(job["id"])
    assert result["status"] == "failed" and result["exit_code"] == 7
    assert len(result["events"]) == 100
    with c.service.store._connect() as db:
        persisted = " ".join(r[0] for r in db.execute("SELECT payload FROM simple_mode_jobs"))
    assert secret not in persisted and "testJWT" not in persisted
    assert "no automatic retry" in result["message"]


@pytest.mark.parametrize("line,expected", [
    ("  >> 07 / Orchestrator repository\n", "repository"),
    ("  >> 09 / Deployment identity\n", "identity"),
    ("  >> 15 / Common and project deployment\n", "common"),
    ("  >> 12a / Hub DNS forwarder\n", "hub"),
    ("  GitHub project run 1234567890\n", "project"),
    ("  \x1b[1;92m>>\x1b[0m 12 / Hub private DNS\n", "hub"),
    ("AIF_SIMPLE_STAGE=project\n", "project"),
    ("  >> 07 / Orchestrator repository password=neverstore\n", None),
    ("  GitHub project run ghp_NeverStoreThisCredential\n", None),
    ("  GitHub common run 12345 token=neverstore\n", None),
    ("AIF_SIMPLE_STAGE=unknown\n", None),
    ("secret >> 12 / Hub private DNS\n", None),
])
def test_actual_purple_terminal_protocol_accepts_only_safe_lines(line, expected):
    assert sm.output_stage(line) == expected


def test_popen_errors_never_echo_raw_exception(context):
    c = context
    c.popen.side_effect = OSError("password=super-secret")
    p = preview(c)
    job = c.service.start(p["confirmation_id"])
    c.work.pop()()
    result = c.service.get_job(job["id"])
    assert result["status"] == "failed" and result["exit_code"] is None
    assert "super-secret" not in json.dumps(result)


def test_watchdog_targets_only_owned_live_process(context, monkeypatch):
    c = context
    c.process.stdout = io.StringIO("")
    alive = [True]
    c.process.poll = lambda: None if alive[0] else -9
    c.process.wait = lambda: -9
    c.process.kill = Mock(side_effect=lambda: alive.__setitem__(0, False))
    kill_calls = []
    c.cli.runner = lambda argv, **kw: kill_calls.append((argv, kw))

    class ImmediateTimer:
        def __init__(self, timeout, callback):
            assert timeout == 8 * 60 * 60
            self.callback = callback

        def start(self):
            self.callback()

        def cancel(self):
            pass

    # Keep all read-only rechecks on the fake Azure/GitHub command runner.
    original_read = c.cli.read
    def read(*args, **kwargs):
        runner = c.cli.runner
        c.cli.runner = c.runner
        try:
            return original_read(*args, **kwargs)
        finally:
            c.cli.runner = runner
    monkeypatch.setattr(c.cli, "read", read)
    monkeypatch.setattr(sm.threading, "Timer", ImmediateTimer)
    p = preview(c)
    job = c.service.start(p["confirmation_id"])
    c.work.pop()()
    result = c.service.get_job(job["id"])
    assert result["status"] == "failed" and result["exit_code"] == -9
    assert "eight-hour" in result["message"]
    assert kill_calls[0][0][-4:] == ["/PID", "98765", "/T", "/F"]
    assert kill_calls[0][1]["shell"] is False
    c.process.kill.assert_called_once()


def test_concurrent_start_single_active_and_duplicate_idempotent(context):
    c = context
    p = preview(c)
    second = preview(c)
    def start(cid):
        try:
            return c.service.start(cid)
        except TicketError as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, [p["confirmation_id"], second["confirmation_id"]]))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert 409 in results and len(c.work) == 1
    first_id = next(r["id"] for r in results if isinstance(r, dict))
    consumed = p if isinstance(results[0], dict) else second
    with ThreadPoolExecutor(max_workers=3) as pool:
        duplicates = list(pool.map(start, [consumed["confirmation_id"]] * 3))
    assert all(r["id"] == first_id for r in duplicates)
    assert len(c.work) == 1


def test_owner_isolation_plans_and_jobs(context):
    c = context
    p = preview(c)
    job = c.service.start(p["confirmation_id"])
    c.runner.oid = OTHER
    for action in (lambda: c.service.start(p["confirmation_id"]), lambda: c.service.get_job(job["id"])):
        with pytest.raises(TicketError) as error:
            action()
        assert error.value.status_code == 404


def test_restart_marks_interrupted_no_relaunch_or_arbitrary_pid_kill(context):
    c = context
    p = preview(c)
    job = c.service.start(p["confirmation_id"])
    sm._INITIALIZED_DATABASES.discard(str(c.service.store.db_path.resolve()))
    sm._LIVE_JOBS.clear()
    restarted = sm.SimpleModeService(c.service.store, cli=c.cli, source=c.service.source, clock=lambda: NOW,
                                    popen=c.popen, dispatch=c.work.append)
    result = restarted.get_job(job["id"])
    assert result["status"] == "interrupted"
    assert restarted.start(p["confirmation_id"])["status"] == "interrupted"
    c.popen.assert_not_called()
    assert len(c.work) == 1
    new = restarted.prepare(c.data)
    with pytest.raises(TicketError, match="reconciliation"):
        restarted.start(new["confirmation_id"])


def test_migration_preserves_other_operations_and_ticket_tables(context):
    c = context
    with c.service._store._connect() as db:
        db.execute("CREATE TABLE private_tickets(id TEXT PRIMARY KEY, title TEXT)")
        db.execute("INSERT INTO private_tickets VALUES('existing','Keep')")
    preview(c)
    with c.service.store._connect() as db:
        assert db.execute("SELECT title FROM private_tickets WHERE id='existing'").fetchone()[0] == "Keep"
        assert db.execute("SELECT version FROM simple_mode_schema").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='operation_configs'").fetchone()


def test_ambient_launch_environment_is_allowlisted(context, monkeypatch):
    for key in ("AIF_DRY_RUN", "AIF_PREPARE_ONLY", "AIF_NO_WAIT", "ADO_PAT", "GITHUB_TOKEN", "GH_TOKEN",
                "AIF_SIMPLE_MODE", "BASH_ENV", "ENV", "SHELLOPTS", "GIT_CONFIG_COUNT"):
        monkeypatch.setenv(key, "injected-secret")
    env = sm.launch_environment({"AIF_SIMPLE_MODE": "true", "AIF_COST_CENTER": "123456"})
    assert env["AIF_SIMPLE_MODE"] == "true"
    assert "injected-secret" not in env.values()
    assert env["GH_HOST"] == "github.com"
    assert not any(k.startswith("ADO_") for k in env)


def test_source_requires_published_version_objects_not_development_checkout(context):
    c = context
    root = c.root / "purple"
    bootstrap = root / "bootstrap"
    lib = bootstrap / "lib"
    lib.mkdir(parents=True)
    script = bootstrap / "GHA-create-new-aifactory-scaleset.sh"
    script.write_text("# never execute")
    (lib / "create-new-aifactory-scaleset.sh").write_text(
        '# AIFACTORY_VERSION_CONTRACT=1\n'
        'readonly AIF_SUBMODULE_URL="https://github.com/example/purple"\n'
        'readonly AIF_SUBMODULE_BRANCH="${AIF_SUBMODULE_BRANCH:-release/v1.24}"\n'
        'AIF_SIMPLE_MODE=true\nAIF_SUBMODULE_REF=unused\n--verify-simple-mode-source\n'
        'GITHUB_REPOSITORY_VISIBILITY=private\nAIF_SIMPLE_PROJECT_RESOURCES_JSON=[]\n')
    source = sm.SourceReadiness(c.cli, script)
    assert source.check()["blockers"]
    helper = lib / "aifactory_scaleset_config.py"
    helper.write_text(
        'AIF_SIMPLE_MODE_CONTRACT_VERSION = 2\n'
        'SIMPLE_MODE_PRESET_NAME = "test-purple-preset-v2"\n'
        'SIMPLE_MODE_REQUIRED_SOURCE_PATHS = ("bootstrap", "environment_setup/aifactory")\n'
        f'resource_catalog = {CATALOG!r}\n'
        'raise AssertionError("Never execute source helper")\n'
        'def simple_mode_manifest():\n'
        '    return {"services": {"Foundry": "S0"}, "hub": {"bastion": "Developer"}, "resourceCatalog": resource_catalog}\n')
    dependencies = root / "environment_setup" / "aifactory"
    dependencies.mkdir(parents=True)
    template = dependencies / "template.bicep"
    template.write_text("// exact dependency")
    (lib / "release_version.py").write_text('# AIFACTORY_VERSION_CONTRACT=1')
    c.runner.published_files = {path.relative_to(root).as_posix(): path.read_text()
                                for path in root.rglob("*") if path.is_file()}
    first = source.check()
    assert not first["blockers"]
    assert first["commit"] == SHA
    assert first["preset"]["services"]["Foundry"] == "S0"
    assert any("show" in argv for argv, _ in c.runner.calls)
    assert not any("checkout" in argv for argv, _ in c.runner.calls)
    c.runner.source_dirty = " M bootstrap/lib/create-new-aifactory-scaleset.sh"
    assert not source.check()["blockers"]
    c.runner.source_dirty = "!! bootstrap/lib/__pycache__/"
    assert not source.check()["blockers"]
    c.runner.source_dirty = "!! bootstrap/lib/ignored-but-used.sh"
    assert not source.check()["blockers"]
    c.runner.source_dirty = ""
    c.runner.remote_sha = "b" * 40
    assert source.check()["blockers"]
    c.runner.remote_sha = SHA
    script.write_text("# edited")
    assert source.check()["fingerprint"] == first["fingerprint"]
    after_script = source.check()["fingerprint"]
    template.write_text("// dependency edited")
    assert source.check()["fingerprint"] == after_script
    helper.write_text(helper.read_text().replace("AIF_SIMPLE_MODE_CONTRACT_VERSION = 2", "AIF_SIMPLE_MODE_CONTRACT_VERSION = 1"))
    assert source.manifest()["contractVersion"] == 1
    assert not source.check()["blockers"]
    c.runner.published_files["bootstrap/lib/aifactory_scaleset_config.py"] = helper.read_text()
    assert source.check()["blockers"]


def test_injected_cli_does_not_resolve_host_commands(monkeypatch):
    monkeypatch.setattr(operations, "resolve_azure_cli", Mock(side_effect=AssertionError("Host resolver used")))
    monkeypatch.setattr(sm.shutil, "which", Mock(side_effect=AssertionError("Host tool lookup used")))
    cli = sm.ReadOnlyCLI(FakeCLI())
    assert cli.accounts()[0]["subscription_id"] == SUB


@pytest.mark.parametrize("value,branch", [("125", "release/v1.25"), ("1.100", "release/v1.100"), ("10.2", "release/v10.2"), ("main", "main")])
def test_version_is_selected_in_preview_and_bound_to_execution(context, value, branch):
    c = context
    c.data["aifactory_version"] = value
    p = preview(c)
    assert p["aifactory_version"] == value
    assert p["requested_version"] == value and p["branch"] == branch and p["resolved_ref"] == SHA
    c.service.start(p["confirmation_id"])
    c.work.pop()()
    environment = c.popen.call_args.kwargs["env"]
    assert environment["AIFACTORY_VERSION"] == value
    assert environment["AIF_SUBMODULE_BRANCH"] == branch
    assert environment["AIF_SUBMODULE_REF"] == SHA
    assert c.popen.call_args.kwargs["stdin"] == subprocess.DEVNULL


def test_post_confirmation_version_environment_tampering_fails(context):
    c = context
    p = preview(c)
    with c.service.store._connect() as db:
        row = db.execute("SELECT payload FROM simple_mode_plans WHERE id=?", (p["confirmation_id"],)).fetchone()
        payload = json.loads(row["payload"])
        payload["preview"]["environment"]["AIFACTORY_VERSION"] = "125"
        db.execute("UPDATE simple_mode_plans SET payload=? WHERE id=?", (json.dumps(payload), p["confirmation_id"]))
    with pytest.raises(TicketError, match="version changed"):
        c.service.start(p["confirmation_id"])
    c.popen.assert_not_called()


@pytest.mark.parametrize("key,value", [
    ("aifactory_version", "124"), ("requested_version", "125"),
    ("branch", "release/v1.25"), ("resolved_ref", "b" * 40),
])
@pytest.mark.parametrize("remove", [False, True])
def test_consent_rejects_changed_or_missing_preview_version_metadata(context, key, value, remove):
    c = context
    c.data["aifactory_version"] = "1.24"
    p = preview(c)
    with c.service.store._connect() as db:
        row = db.execute("SELECT payload FROM simple_mode_plans WHERE id=?", (p["confirmation_id"],)).fetchone()
        payload = json.loads(row["payload"])
        if remove:
            del payload["preview"][key]
        else:
            payload["preview"][key] = value
        db.execute("UPDATE simple_mode_plans SET payload=? WHERE id=?", (json.dumps(payload), p["confirmation_id"]))
    with pytest.raises(TicketError) as error:
        c.service.start(p["confirmation_id"])
    assert error.value.status_code == 409
    assert not c.work
    c.popen.assert_not_called()


def test_version_raw_echo_distinguishes_omission_and_equivalent_dotted_selector(context):
    c = context
    assert preview(c)["aifactory_version"] is None
    c.data["aifactory_version"] = "1.25"
    plan = preview(c)
    assert plan["aifactory_version"] == "1.25"
    assert plan["requested_version"] == "125"
    assert plan["branch"] == "release/v1.25"


def test_literal_explicit_125_returns_aifactory_version_125(context):
    context.data["aifactory_version"] = "125"
    result = context.service.prepare(context.data)
    assert result["aifactory_version"] == "125"
    assert result["requested_version"] == "125"
    assert result["can_execute"], result["blockers"]


def test_api_contract_security_and_credential_error_redaction(context, monkeypatch):
    c = context
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    monkeypatch.setattr(api, "_simple_mode_service", lambda: c.service)
    with TestClient(api.app) as client:
        for method, route, body in [
            ("get", "/options", None), ("post", "/prepare", c.data),
            ("post", "/start", {"confirmation_id": OID}), ("get", "/jobs/" + OID, None),
        ]:
            response = getattr(client, method)("/api/v1/simple-mode" + route, **({"json": body} if body else {}))
            assert response.status_code == 401
        headers = {"X-API-Key": "test-key"}
        options = client.get("/api/v1/simple-mode/options", headers=headers)
        assert set(options.json()) == {"defaults", "azure_accounts", "github_account", "regions", "requirements", "warnings", "script_path",
                                      "github_visibilities", "resource_catalog"}
        invalid = client.post("/api/v1/simple-mode/prepare", headers=headers, json={**c.data, "password": "never-echo-me"})
        assert invalid.status_code == 422 and "never-echo-me" not in invalid.text
        prepared = client.post("/api/v1/simple-mode/prepare", headers=headers, json=c.data)
        assert prepared.status_code == 200
        assert prepared.json().get("aifactory_version") is None
        assert set(prepared.json()) - {"aifactory_version"} == {
            "confirmation_id", "can_execute", "summary", "script_path", "command",
            "environment", "effects", "requirements", "warnings", "blockers", "expires_at",
            "github_visibility", "project_resources", "resource_catalog",
            "requested_version", "branch", "resolved_ref",
        }
        started = client.post("/api/v1/simple-mode/start", headers=headers,
                              json={"confirmation_id": prepared.json()["confirmation_id"]})
        assert started.status_code == 200
        assert set(started.json()) == {"id", "status", "stage", "message", "created_at", "updated_at",
                                      "exit_code", "repository_url", "repo_root", "events"}
        polled = client.get("/api/v1/simple-mode/jobs/" + started.json()["id"], headers=headers)
        assert polled.json()["id"] == started.json()["id"]
        assert c.popen.call_count == 0


def test_api_v2_public_empty_selection_and_gateway_defaults(context, monkeypatch):
    c = context
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    monkeypatch.setattr(api, "_simple_mode_service", lambda: c.service)
    with TestClient(api.app) as client:
        headers = {"X-API-Key": "test-key"}
        options = client.get("/api/v1/simple-mode/options", headers=headers).json()
        assert options["defaults"]["project_resources"] == DEFAULT_RESOURCES
        assert options["defaults"]["github_visibility"] == "private"
        assert all(options["defaults"][field] == "" for field in sm.GATEWAY_FIELDS)
        prepared = client.post("/api/v1/simple-mode/prepare", headers=headers,
                               json={**c.data, "github_visibility": "public", "project_resources": []})
        assert prepared.status_code == 200
        body = prepared.json()
        assert body["can_execute"] and body["project_resources"] == []
        assert {item["id"] for item in body["resource_catalog"]["project"]} == sm.REQUIRED_PROJECT_RESOURCES
        assert sm.PUBLIC_REPOSITORY_WARNING in body["warnings"]
        invalid = client.post("/api/v1/simple-mode/prepare", headers=headers,
                              json={**c.data, "project_resources": None})
        assert invalid.status_code == 422
        tamper = client.post("/api/v1/simple-mode/start", headers=headers,
                             json={"confirmation_id": body["confirmation_id"], "github_visibility": "private"})
        assert tamper.status_code == 422
    c.popen.assert_not_called()
    assert not c.work


def test_http_version_echo_and_exact_selection_survive_api_models(context, monkeypatch):
    c = context
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    monkeypatch.setattr(api, "_simple_mode_service", lambda: c.service)
    with TestClient(api.app) as client:
        response = client.post("/api/v1/simple-mode/prepare", headers={"X-API-Key": "test-key"},
                               json={**c.data, "aifactory_version": "1.25"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["aifactory_version"] == "1.25"
    assert body["requested_version"] == "125"
    assert body["branch"] == "release/v1.25"
    assert body["resolved_ref"] == SHA
    assert body["environment"]["AIF_SUBMODULE_REF"] == body["resolved_ref"]
    c.popen.assert_not_called()


@pytest.mark.skipif(not sm.SCRIPT.is_file(), reason="Installed purple source is not available on this host")
def test_readonly_http_preview_uses_installed_purple_contract(context, monkeypatch):
    c = context
    c.service.source = sm.SourceReadiness(c.cli)
    root = sm.SCRIPT.parent.parent
    c.runner.published_files = {
        relative: (root / relative).read_text(encoding="utf-8")
        for relative in ("bootstrap/lib/create-new-aifactory-scaleset.sh",
                         "bootstrap/lib/aifactory_scaleset_config.py",
                         "bootstrap/lib/release_version.py")
    }
    c.runner.published_files["bootstrap/lib/release_version.py"] = "# unpublished incompatible release"
    c.runner.source_dirty = (
        " M bootstrap/lib/aifactory_scaleset_config.py\n"
        " M environment_setup/aifactory/bicep/template.bicep\n"
    )
    monkeypatch.setenv(api.API_KEY_ENV, "test-key")
    monkeypatch.setattr(api, "_simple_mode_service", lambda: c.service)
    with TestClient(api.app) as client:
        headers = {"X-API-Key": "test-key"}
        options = client.get("/api/v1/simple-mode/options", headers=headers)
        assert options.status_code == 200
        prepared = client.post("/api/v1/simple-mode/prepare", headers=headers, json=c.data)
    assert prepared.status_code == 200
    body = prepared.json()
    assert body["can_execute"] is False
    assert "Publish/fetch the selected release" in " ".join(body["blockers"])
    if c.service.source.manifest():
        assert "private-ai-foundation-v2" in " ".join(body["effects"])
        assert any(item["id"] == "foundry" for item in body["resource_catalog"]["project"])
    else:
        assert body["resource_catalog"] == {"hub": [], "common": [], "project": []}
    if "AIF_SUBMODULE_REF" in body["environment"]:
        assert body["environment"]["AIF_SUBMODULE_REF"] == SHA
    assert not Path(c.data["repo_root"]).exists()
    assert not c.work
    c.popen.assert_not_called()
