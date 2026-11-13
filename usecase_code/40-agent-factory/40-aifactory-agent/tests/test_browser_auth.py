import copy
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from aifactory_agent.browser_auth import AzureCliDirectory, BrowserRegistration, EntraRegistrationService, OWNER
from test_security import CALLER, CLIENT, TENANT, settings


REDIRECT = "https://factory-agent.example.azurecontainerapps.io/"
APPLICATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SERVICE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class FakeDirectory:
    def __init__(self):
        self.apps = []
        self.principals = []
        self.assignments = []
        self.calls = []
        self.owners = [CALLER]
        self.before_application_read = None
        self.ignore_api_patch = False

    def request(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == "GET" and path.startswith("/applications/") and path.endswith("/owners"):
            return {"value": [{"@odata.type": "#microsoft.graph.user", "id": owner} for owner in self.owners]}
        if method == "GET" and path.startswith("/applications/"):
            if self.before_application_read:
                self.before_application_read(self)
            return copy.deepcopy(next(app for app in self.apps if app["id"] == path.split("/")[2]))
        if method == "GET":
            if path.startswith(("/applications?", "/servicePrincipals?")):
                query = parse_qs(urlsplit(path).query).get("$filter", [""])[0]
                field, _, value = query.partition(" eq ")
                values = self.apps if path.startswith("/applications?") else self.principals
                return {"value": copy.deepcopy([item for item in values if item.get(field) == value.strip("'")])}
            if path.endswith("/appRoleAssignedTo"):
                resource = path.split("/")[2]
                return {"value": copy.deepcopy([item for item in self.assignments if item["resourceId"] == resource])}
            return {"value": copy.deepcopy(self.principals)}
        if method == "POST" and path == "/applications":
            # The first application keeps the historic IDs; later ones (another project) get their own.
            number = len(self.apps)
            result = {**copy.deepcopy(body), "id": APPLICATION if not number else f"{number:08x}-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                      "appId": CLIENT if not number else f"{number:08x}-cccc-4ccc-8ccc-cccccccccccc"}
            self.apps.append(result)
            return copy.deepcopy(result)
        if method == "PATCH":
            if self.ignore_api_patch and "api" in body:
                return None
            target = next(app for app in self.apps if app["id"] == path.split("/")[2])
            target.update(copy.deepcopy(body))
            return None
        if method == "POST" and path == "/servicePrincipals":
            number = len(self.principals)
            result = {**copy.deepcopy(body), "id": SERVICE if not number else f"{number:08x}-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
            self.principals.append(result)
            return copy.deepcopy(result)
        if method == "POST" and path.endswith("/appRoleAssignedTo"):
            self.assignments.append(copy.deepcopy(body))
            return copy.deepcopy(body)
        raise AssertionError(f"Unexpected directory operation: {method} {path}")


def registration():
    return BrowserRegistration(tenant_id=TENANT, redirect_uri=REDIRECT, user_object_id=CALLER)


def test_plan_is_single_tenant_pkce_and_has_no_graph_or_arm_permissions():
    directory = FakeDirectory()
    plan = EntraRegistrationService(directory).plan(registration())
    assert plan["tenant_id"] == TENANT and plan["redirect_uri"] == REDIRECT
    assert plan["client_secret"] is False and plan["factory_writes"] is False
    assert plan["requested_permissions"] == ["access_as_user"]
    assert plan["assigned_user_object_id"] == CALLER
    assert directory.calls == []


def test_registration_creates_only_owned_app_api_spa_and_this_user_assignment():
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    result = service.apply(registration())
    app, principal = directory.apps[0], directory.principals[0]
    assert app["signInAudience"] == "AzureADMyOrg"
    assert app["spa"]["redirectUris"] == [REDIRECT]
    assert app["api"]["requestedAccessTokenVersion"] == 2
    assert app["identifierUris"] == ["api://" + CLIENT]
    assert app["tags"] == [OWNER]
    assert "passwordCredentials" not in app and "keyCredentials" not in app
    assert app["requiredResourceAccess"] == [{
        "resourceAppId": CLIENT,
        "resourceAccess": [{"id": app["api"]["oauth2PermissionScopes"][0]["id"], "type": "Scope"}],
    }]
    assert app["api"]["oauth2PermissionScopes"][0]["value"] == "access_as_user"
    assert principal["appRoleAssignmentRequired"] is True
    assert directory.assignments == [{
        "principalId": CALLER, "resourceId": SERVICE, "appRoleId": app["appRoles"][0]["id"],
    }]
    assert result["client_id"] == result["audience"] == CLIENT
    assert result["scope_uri"] == "api://" + CLIENT + "/access_as_user"
    UUID(result["scope_id"])


def test_second_apply_is_read_only_and_does_not_duplicate_or_reset_registration():
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    first = service.apply(registration())
    count = len(directory.calls)
    assert service.apply(registration()) == first
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


@pytest.mark.parametrize("changes", [
    {"tags": []}, {"spa": {"redirectUris": ["https://other.example/"]}},
    {"signInAudience": "AzureADMultipleOrgs"}, {"passwordCredentials": [{"id": "unexpected"}]},
])
def test_owned_or_unowned_drift_requires_review_not_silent_mutation(changes):
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(registration())
    directory.apps[0].update(changes)
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="drift|owned"):
        service.apply(registration())
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


@pytest.mark.parametrize("redirect", [
    "http://factory.example/", "https://factory.example/?next=elsewhere",
    "https://user:password@factory.example/", "https://factory.example/callback",
])
def test_redirect_is_exact_https_root_without_credentials_or_query(redirect):
    with pytest.raises(ValueError):
        BrowserRegistration(tenant_id=TENANT, redirect_uri=redirect, user_object_id=CALLER)


def test_directory_cli_uses_platform_encoding_for_azure_cli_output(monkeypatch):
    from types import SimpleNamespace
    calls = []
    def run(arguments, **options):
        calls.append(options)
        return SimpleNamespace(returncode=0, stdout='{"displayName": "Joakim \\u00c5str\\u00f6m"}', stderr="")
    monkeypatch.setattr("aifactory_agent.browser_auth.subprocess.run", run)
    monkeypatch.setattr("aifactory_agent.browser_auth.locale.getencoding", lambda: "cp1252")
    directory = AzureCliDirectory.__new__(AzureCliDirectory)
    directory.executable = "az"
    assert directory._run(["ad", "signed-in-user", "show"])["displayName"].startswith("Joakim")
    assert calls[0]["encoding"] == "cp1252"


AZURE_CLI = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


def cli_registration():
    return BrowserRegistration(tenant_id=TENANT, redirect_uri=REDIRECT, user_object_id=CALLER,
                               pre_authorized_clients=(AZURE_CLI,))


def test_plan_discloses_reviewed_azure_cli_pre_authorization_without_directory_calls():
    directory = FakeDirectory()
    plan = EntraRegistrationService(directory).plan(cli_registration())
    assert plan["pre_authorized_clients"] == [{
        "app_id": AZURE_CLI, "display_name": "Microsoft Azure CLI", "delegated_permissions": ["access_as_user"],
    }]
    assert plan["existing_application_changes"] is True
    assert plan["client_secret"] is False and plan["factory_writes"] is False
    assert plan["azure_resource_role_changes"] is False
    assert EntraRegistrationService.plan(registration())["pre_authorized_clients"] == []
    assert directory.calls == []


def test_apply_pre_authorizes_only_reviewed_cli_and_preserves_api_scope():
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    first = service.apply(registration())
    scopes = copy.deepcopy(directory.apps[0]["api"]["oauth2PermissionScopes"])
    count = len(directory.calls)
    result = service.apply(cli_registration())
    patches = [call for call in directory.calls[count:] if call[0] != "GET"]
    assert patches == [("PATCH", "/applications/" + APPLICATION, {"api": {
        **{key: value for key, value in directory.apps[0]["api"].items() if key != "preAuthorizedApplications"},
        "preAuthorizedApplications": [{"appId": AZURE_CLI, "delegatedPermissionIds": [first["scope_id"]]}],
    }})]
    api = directory.apps[0]["api"]
    assert api["oauth2PermissionScopes"] == scopes and api["requestedAccessTokenVersion"] == 2
    assert api["preAuthorizedApplications"] == [{"appId": AZURE_CLI, "delegatedPermissionIds": [first["scope_id"]]}]
    assert result["pre_authorized_clients"] == [AZURE_CLI]
    assert directory.assignments == [{"principalId": CALLER, "resourceId": SERVICE, "appRoleId": directory.apps[0]["appRoles"][0]["id"]}]
    count = len(directory.calls)
    assert service.apply(cli_registration()) == result
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


@pytest.mark.parametrize("existing", [
    [{"appId": "11111111-1111-4111-8111-111111111111", "delegatedPermissionIds": ["scope"]}],
    [{"appId": AZURE_CLI, "delegatedPermissionIds": ["other-scope"]}],
])
def test_unexpected_pre_authorization_is_drift_not_overwritten(existing):
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(registration())
    directory.apps[0]["api"]["preAuthorizedApplications"] = existing
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="drift"):
        service.apply(cli_registration())
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


def test_existing_cli_pre_authorization_requires_matching_configuration():
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(cli_registration())
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="drift"):
        service.apply(registration())
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


@pytest.mark.parametrize("clients", [("11111111-1111-4111-8111-111111111111",), (AZURE_CLI, AZURE_CLI), ("cli",)])
def test_only_reviewed_distinct_clients_can_be_pre_authorized(clients):
    with pytest.raises(ValueError):
        BrowserRegistration(tenant_id=TENANT, redirect_uri=REDIRECT, user_object_id=CALLER,
                            pre_authorized_clients=clients)


def test_configured_additional_clients_drive_the_registration(settings):
    from aifactory_agent.browser_auth import registration_for
    current = settings.model_copy(update={"auth": settings.auth.model_copy(update={"additional_client_ids": [UUID(AZURE_CLI)]})})
    expected = BrowserRegistration(tenant_id=TENANT, redirect_uri=REDIRECT, user_object_id=CALLER,
                                   pre_authorized_clients=(AZURE_CLI,), expected_client_id=CLIENT)
    assert registration_for(current, REDIRECT, CALLER) == expected
    assert registration_for(settings, REDIRECT, CALLER) == BrowserRegistration(
        tenant_id=TENANT, redirect_uri=REDIRECT, user_object_id=CALLER, expected_client_id=CLIENT)


@pytest.mark.parametrize("owners", [["dddddddd-dddd-4ddd-8ddd-dddddddddddd"],
                                    [CALLER, "dddddddd-dddd-4ddd-8ddd-dddddddddddd"], []])
def test_same_named_application_needs_the_operator_as_exclusive_owner(owners):
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(registration())
    directory.owners = owners
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="owner"):
        service.apply(cli_registration())
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


def test_configured_registration_is_never_replaced_or_swapped_by_name():
    directory = FakeDirectory()
    bound = BrowserRegistration(tenant_id=TENANT, redirect_uri=REDIRECT, user_object_id=CALLER,
                                expected_client_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    with pytest.raises(RuntimeError, match="configured"):
        EntraRegistrationService(directory).apply(bound)
    assert directory.calls and all(method == "GET" for method, _, _ in directory.calls)
    EntraRegistrationService(directory).apply(registration())
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="configured"):
        EntraRegistrationService(directory).apply(bound)
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


def test_configured_registration_is_found_by_its_immutable_app_id():
    directory = FakeDirectory()
    EntraRegistrationService(directory).apply(registration())
    directory.apps.append({**copy.deepcopy(directory.apps[0]), "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                           "appId": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"})
    count = len(directory.calls)
    bound = BrowserRegistration(tenant_id=TENANT, redirect_uri=REDIRECT, user_object_id=CALLER, expected_client_id=CLIENT)
    assert EntraRegistrationService(directory).apply(bound)["client_id"] == CLIENT
    lookup = directory.calls[count][1]
    assert lookup.startswith("/applications?") and "appId" in parse_qs(urlsplit(lookup).query)["$filter"][0]


def test_pre_authorization_rereads_before_and_verifies_after_the_patch():
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(registration())
    def concurrent_change(current):
        current.apps[0]["api"]["knownClientApplications"] = []
        current.apps[0]["api"]["acceptMappedClaims"] = True
        current.before_application_read = None
    directory.before_application_read = concurrent_change
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="changed"):
        service.apply(cli_registration())
    assert not any(method == "PATCH" for method, _, _ in directory.calls[count:])
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(registration())
    directory.ignore_api_patch = True
    with pytest.raises(RuntimeError, match="not confirmed"):
        service.apply(cli_registration())


def test_runtime_configuration_must_accept_the_same_pre_authorized_clients(tmp_path):
    import json
    from aifactory_agent.browser_auth import verify_runtime_clients
    source = tmp_path / "config.example.json"
    local = tmp_path / "config.local.json"
    source.write_text("{}", encoding="utf-8")
    verify_runtime_clients(source, cli_registration())
    local.write_text(json.dumps({"auth": {"additional_client_ids": [AZURE_CLI]}}), encoding="utf-8")
    verify_runtime_clients(source, cli_registration())
    verify_runtime_clients(local, cli_registration())
    with pytest.raises(RuntimeError, match="additional_client_ids"):
        verify_runtime_clients(source, registration())
    local.write_text(json.dumps({"auth": {}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="additional_client_ids"):
        verify_runtime_clients(source, cli_registration())


def runtime_files(tmp_path, settings, *, local_client=CLIENT, local_tenant=TENANT, source_client=None, clients=()):
    import json
    source_values = settings.model_dump(mode="json")
    source_values["auth"].update(client_id=source_client, audience=source_client, additional_client_ids=list(clients))
    local_values = copy.deepcopy(source_values)
    local_values["auth"].update(client_id=local_client, audience=local_client)
    for scope in local_values["scopes"].values():
        scope["tenant_id"] = local_tenant
    (tmp_path / "config.example.json").write_text(json.dumps(source_values), encoding="utf-8")
    (tmp_path / "config.local.json").write_text(json.dumps(local_values), encoding="utf-8")
    return tmp_path / "config.example.json", settings.model_validate(source_values)


def test_example_configuration_binds_to_the_runtime_registration_before_any_directory_call(tmp_path, settings):
    from aifactory_agent.browser_auth import registration_from_configuration
    source, loaded = runtime_files(tmp_path, settings, clients=(AZURE_CLI,))
    bound = registration_from_configuration(source, loaded, REDIRECT, CALLER)
    assert bound.expected_client_id == CLIENT and bound.pre_authorized_clients == (AZURE_CLI,)


PROJECT_001 = "https://aifactory-agent-project001-dev.nicegrass-1a2b3c4d.swedencentral.azurecontainerapps.io/"
PROJECT_002 = "https://aifactory-agent-project002-dev.nicegrass-1a2b3c4d.swedencentral.azurecontainerapps.io/"
OTHER_FACTORY = "https://aifactory-agent-project001-dev.bluesky-9f8e7d6c.swedencentral.azurecontainerapps.io/"


def for_redirect(redirect, **values):
    return BrowserRegistration(tenant_id=TENANT, redirect_uri=redirect, user_object_id=CALLER, **values)


def test_registration_name_identifies_the_project_app_and_its_environment():
    from aifactory_agent.browser_auth import display_name_for
    expected = "Enterprise Scale AI Factory Agent (aifactory-agent-project001-dev.nicegrass-1a2b3c4d)"
    assert display_name_for(PROJECT_001) == expected
    assert for_redirect(PROJECT_001).display_name == expected
    assert EntraRegistrationService.plan(for_redirect(PROJECT_001))["display_name"] == expected
    directory = FakeDirectory()
    result = EntraRegistrationService(directory).apply(for_redirect(PROJECT_001))
    assert directory.apps[0]["displayName"] == expected and result["display_name"] == expected


def test_each_project_and_factory_in_one_tenant_gets_its_own_registration():
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    results = [service.apply(for_redirect(redirect)) for redirect in (PROJECT_001, PROJECT_002, OTHER_FACTORY)]
    assert len({result["client_id"] for result in results}) == 3
    assert [app["spa"]["redirectUris"] for app in directory.apps] == [[PROJECT_001], [PROJECT_002], [OTHER_FACTORY]]
    assert len({app["displayName"] for app in directory.apps}) == 3
    count = len(directory.calls)
    assert [service.apply(for_redirect(redirect)) for redirect in (PROJECT_001, PROJECT_002, OTHER_FACTORY)] == results
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


def test_another_factorys_legacy_named_registration_is_left_alone():
    """aif-160, 2026-11-13: the tenant already held another Factory's "Enterprise Scale AI Factory Agent"."""
    from aifactory_agent.browser_auth import LEGACY_DISPLAY_NAME
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(for_redirect(OTHER_FACTORY, display_name=LEGACY_DISPLAY_NAME))
    legacy = copy.deepcopy(directory.apps[0])
    count = len(directory.calls)
    result = service.apply(for_redirect(PROJECT_001))
    assert directory.apps[0] == legacy
    assert not any(method == "PATCH" and legacy["id"] in path for method, path, _ in directory.calls[count:])
    assert result["client_id"] != legacy["appId"] and result["redirect_uri"] == PROJECT_001
    assert directory.apps[1]["displayName"] == for_redirect(PROJECT_001).display_name


def test_existing_legacy_registration_for_this_address_is_still_reused():
    from aifactory_agent.browser_auth import LEGACY_DISPLAY_NAME
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    first = service.apply(for_redirect(PROJECT_001, display_name=LEGACY_DISPLAY_NAME))
    count = len(directory.calls)
    assert service.apply(for_redirect(PROJECT_001))["client_id"] == first["client_id"]
    assert service.apply(for_redirect(PROJECT_001, expected_client_id=first["client_id"]))["client_id"] == first["client_id"]
    assert len(directory.apps) == 1 and all(method == "GET" for method, _, _ in directory.calls[count:])


def test_legacy_registration_keeps_the_owner_and_drift_checks():
    from aifactory_agent.browser_auth import LEGACY_DISPLAY_NAME
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(for_redirect(PROJECT_001, display_name=LEGACY_DISPLAY_NAME))
    directory.owners = ["dddddddd-dddd-4ddd-8ddd-dddddddddddd"]
    with pytest.raises(RuntimeError, match="owner"):
        service.apply(for_redirect(PROJECT_001))
    directory.owners = [CALLER]
    directory.apps[0]["tags"] = []
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="owned"):
        service.apply(for_redirect(PROJECT_001))
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


def test_two_legacy_registrations_for_this_address_are_ambiguous():
    from aifactory_agent.browser_auth import LEGACY_DISPLAY_NAME
    directory = FakeDirectory()
    service = EntraRegistrationService(directory)
    service.apply(for_redirect(PROJECT_001, display_name=LEGACY_DISPLAY_NAME))
    directory.apps.append({**copy.deepcopy(directory.apps[0]), "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                           "appId": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"})
    count = len(directory.calls)
    with pytest.raises(RuntimeError, match="ambiguous"):
        service.apply(for_redirect(PROJECT_001))
    assert all(method == "GET" for method, _, _ in directory.calls[count:])


def test_explicit_display_name_is_used_and_checked():
    directory = FakeDirectory()
    result = EntraRegistrationService(directory).apply(for_redirect(PROJECT_001, display_name="Team A Agent Chat"))
    assert directory.apps[0]["displayName"] == result["display_name"] == "Team A Agent Chat"
    for name in ("", "  ", "it's", "tab\there", "x" * 257):
        with pytest.raises(ValueError):
            for_redirect(PROJECT_001, display_name=name)


def test_display_name_option_reaches_the_registration(tmp_path, settings):
    from aifactory_agent.browser_auth import parser, registration_for, registration_from_configuration
    arguments = parser().parse_args(["--config", "x.json", "--redirect-uri", PROJECT_001, "--user-object-id", CALLER,
                                     "--display-name", "Team A Agent Chat"])
    assert arguments.display_name == "Team A Agent Chat"
    assert parser().parse_args(["--config", "x.json", "--redirect-uri", PROJECT_001,
                                "--user-object-id", CALLER]).display_name is None
    assert registration_for(settings, PROJECT_001, CALLER, display_name="Team A Agent Chat").display_name == "Team A Agent Chat"
    source, loaded = runtime_files(tmp_path, settings)
    bound = registration_from_configuration(source, loaded, PROJECT_001, CALLER, display_name="Team A Agent Chat")
    assert bound.display_name == "Team A Agent Chat" and bound.expected_client_id == CLIENT


@pytest.mark.parametrize("changes,message", [
    ({"source_client": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"}, "registration"),
    ({"local_tenant": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"}, "tenant"),
])
def test_runtime_identity_mismatch_stops_before_directory_changes(tmp_path, settings, changes, message):
    from aifactory_agent.browser_auth import registration_from_configuration
    source, loaded = runtime_files(tmp_path, settings, **changes)
    with pytest.raises(RuntimeError, match=message):
        registration_from_configuration(source, loaded, REDIRECT, CALLER)
