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
            if path.startswith("/applications?"):
                query = parse_qs(urlsplit(path).query).get("$filter", [""])[0]
                field, _, value = query.partition(" eq ")
                return {"value": copy.deepcopy([app for app in self.apps if app.get(field) == value.strip("'")])}
            values = self.assignments if path.endswith("/appRoleAssignedTo") else self.principals
            return {"value": copy.deepcopy(values)}
        if method == "POST" and path == "/applications":
            result = {**copy.deepcopy(body), "id": APPLICATION, "appId": CLIENT}
            self.apps.append(result)
            return copy.deepcopy(result)
        if method == "PATCH":
            if self.ignore_api_patch and "api" in body:
                return None
            target = self.apps[0] if path.startswith("/applications/") else self.principals[0]
            target.update(copy.deepcopy(body))
            return None
        if method == "POST" and path == "/servicePrincipals":
            result = {**copy.deepcopy(body), "id": SERVICE}
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


@pytest.mark.parametrize("changes,message", [
    ({"source_client": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"}, "registration"),
    ({"local_tenant": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"}, "tenant"),
])
def test_runtime_identity_mismatch_stops_before_directory_changes(tmp_path, settings, changes, message):
    from aifactory_agent.browser_auth import registration_from_configuration
    source, loaded = runtime_files(tmp_path, settings, **changes)
    with pytest.raises(RuntimeError, match=message):
        registration_from_configuration(source, loaded, REDIRECT, CALLER)
