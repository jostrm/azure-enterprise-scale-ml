"""Offline contract tests: neither Azure nor GitHub/ADO is contacted."""

import base64
import copy
import importlib.util
import io
import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("factory_enrollment", ROOT / "bootstrap" / "lib" / "factory_enrollment.py")
en = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(en)
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CLIENT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
PRINCIPAL = "dddddddd-dddd-dddd-dddd-dddddddddddd"
OPERATOR = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
FACTORY = "11111111-1111-1111-1111-111111111111"
SCALE = "22222222-2222-2222-2222-222222222222"
ADO_TENANT = "33333333-3333-3333-3333-333333333333"
ADO_SUB = "55555555-5555-5555-5555-555555555555"
PROJECT = "44444444-4444-4444-4444-444444444444"
CONTRIBUTOR = "b24988ac-6180-42a0-ab88-20f7382dd24c"
GROUP = f"/subscriptions/{SUB}/resourcegroups/owned"


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("LIVE COMMANDS AND HTTP ARE FORBIDDEN")
    monkeypatch.setattr(en.subprocess, "run", fail)
    monkeypatch.setattr(en, "build_opener", fail)
    monkeypatch.setattr(en.time, "sleep", fail)


@pytest.fixture
def workspace():
    path = ROOT / (".enrollment-offline-" + str(uuid4()))
    (path / "azurefactory").mkdir(parents=True)
    document = {
        "schema_version": 2, "generation": "reviewed", "configurations": {},
        "factories": [{"id": FACTORY, "kind": "ai", "prefix": "acme-ai", "region": "swedencentral",
                       "scale_sets": [{"id": SCALE, "environment": "stage", "suffix": "001",
                                       "tenant_id": TENANT, "subscription_id": SUB, "orchestrator": "gha"}]}],
        "bindings": {},
    }
    (path / "azurefactory" / "register.json").write_bytes(en.canonical(document))
    try:
        yield path
    finally:
        shutil.rmtree(path)


def document(path):
    return json.loads((path / "azurefactory" / "register.json").read_text())


def save(path, value):
    (path / "azurefactory" / "register.json").write_bytes(en.canonical(value))


def options(kind="gha"):
    return {"repository": "https://github.com/org/repo" if kind == "gha" else "https://dev.azure.com/org/project/_git/repo",
            "ref": "refs/heads/main", "shared_remote": True, "writer_id": "stage-writer",
            "auth_namespace": "factory-stage", "runner": {"kind": "hosted", "os": "linux", "image": "ubuntu-24.04"},
            "resource_group_ids": [GROUP], "common_dependency_ids": [], "public_network_access": "Disabled",
            "deployment_roles": [{"scope": GROUP, "role_definition_id": CONTRIBUTOR}],
            **({"ado_tenant_id": ADO_TENANT} if kind == "ado" else {})}


def request(path, kind="gha", **overrides):
    if kind == "ado":
        doc = document(path)
        doc["factories"][0]["scale_sets"][0]["orchestrator"] = kind
        save(path, doc)
    return en.load_request(path, FACTORY, SCALE, "stage", options(kind) | overrides)


class Response(io.BytesIO):
    def __init__(self, status, body=None, headers=None):
        super().__init__(body if isinstance(body, bytes) else en.canonical(body) if body is not None else b"")
        self.status = status
        self.headers = headers or {}


class Fake:
    """Fake command executor plus HTTP service, retaining state across ensures."""

    def __init__(self, req, provisioned=True):
        self.request = req
        self.commands, self.calls, self.writes = [], [], []
        self.resources = {}
        self.identity_properties = {"tenantId": TENANT, "clientId": CLIENT, "principalId": PRINCIPAL}
        self.blobs = {}
        self.etag = 0
        self.denies = []
        self.management_permissions = [{"actions": ["*"], "notActions": [], "dataActions": []}]
        self.fail = {}
        self.concurrent_enrollment = False
        self.concurrent_container = False
        self.github_environment = {"id": 123, "name": req["route"]["auth_namespace"], "protection_rules": []}
        self.concurrent_variable = None
        self.variables = {}
        self.ado_endpoint = None
        self.oidc_default = True
        self.token_tenant = TENANT
        self.identity_subscription_tenant = TENANT
        self.token_audience = None
        self.ado_accounts = [
            {"id": SUB, "tenantId": TENANT, "state": "Enabled", "accountName": "operator@example.test"},
            {"id": ADO_SUB, "tenantId": ADO_TENANT, "state": "Enabled", "accountName": "ado@example.test"},
        ]
        self.name_available = True
        for scope in {GROUP, req["account_id"].split("/providers/")[0], req["identity_id"].split("/providers/")[0]}:
            self.resources[scope] = {"id": scope, "location": "swedencentral",
                                     "tags": {"aifactory.factory_id": FACTORY, "aifactory.scaleset_id": SCALE},
                                     "properties": {"provisioningState": "Succeeded"}}
        for role, perms in ((CONTRIBUTOR, [{"actions": ["*"], "notActions": [
                "Microsoft.Authorization/*/write"], "dataActions": []}]),
                            (en.DATA_ROLE, [{"actions": ["Microsoft.Storage/storageAccounts/blobServices/containers/*"],
                                             "dataActions": ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"]}])):
            identifier = f"/subscriptions/{SUB}/providers/microsoft.authorization/roledefinitions/{role}"
            self.resources[identifier] = {"id": identifier, "properties": {"permissions": perms}}
        self.cloud = en.Cloud(req, command_runner=self.run, opener=self)
        if provisioned:
            self.provision_prerequisites()

    def _token(self, audience, tenant):
        claims = {"tid": tenant, "aud": audience, "oid": OPERATOR, "exp": time.time() + 3600}
        middle = base64.urlsafe_b64encode(en.canonical(claims)).decode().rstrip("=")
        return "header." + middle + ".signature"

    def run(self, argv, **kwargs):
        self.commands.append((copy.deepcopy(argv), kwargs.get("input")))
        assert kwargs["shell"] is False
        if argv[0] == "az":
            assert not any(x in argv for x in ("login", "set", "delete", "--account-key", "--sas-token"))
            args = argv[1:]
            if args[:2] == ["account", "show"]:
                selected = args[args.index("--subscription") + 1]
                tenant = self.token_tenant if selected == SUB else self.identity_subscription_tenant
                return SimpleNamespace(returncode=0, stdout=en.canonical({"id": selected, "tenantId": tenant,
                                                                          "name": "Stage subscription"}), stderr=b"")
            if args[:2] == ["account", "get-access-token"]:
                audience = args[args.index("--resource") + 1]
                selected = args[args.index("--subscription") + 1] if "--subscription" in args else None
                tenant = self.token_tenant
                if audience == en.ADO_AUDIENCE:
                    account = next((item for item in self.ado_accounts if item["id"] == selected), None)
                    tenant = account["tenantId"] if account else self.token_tenant
                return SimpleNamespace(returncode=0, stdout=en.canonical({
                    "accessToken": self._token(self.token_audience or audience, tenant)}), stderr=b"")
            if args[:2] == ["account", "list"]:
                assert "--all" in args
                return SimpleNamespace(returncode=0, stdout=en.canonical(self.ado_accounts), stderr=b"")
            if args[:2] == ["identity", "show"]:
                identifier = args[args.index("--ids") + 1]
                resource = self.resources[identifier]
                return SimpleNamespace(returncode=0, stdout=en.canonical({"id": identifier, **resource["properties"]}), stderr=b"")
            if args[:3] == ["storage", "account", "check-name"]:
                assert args[args.index("--subscription") + 1] == SUB
                return SimpleNamespace(returncode=0, stdout=en.canonical({"nameAvailable": self.name_available}), stderr=b"")
            raise AssertionError(argv)
        assert argv[:2] == ["gh", "api"]
        method = argv[argv.index("--method") + 1]
        endpoint = argv[argv.index("--method") + 2]
        body = json.loads(kwargs["input"]) if kwargs["input"] is not None else None
        key = (method, endpoint)
        if key in self.fail:
            status, result = self.fail[key], {}
        elif endpoint == "repos/org/repo":
            status, result = 200, {"full_name": "org/repo", "permissions": {"admin": True}}
        elif endpoint.endswith("/actions/oidc/customization/sub"):
            status, result = 200, {"use_default": self.oidc_default}
        elif "/variables/" in endpoint:
            name = endpoint.rsplit("/", 1)[1]
            status = 200 if name in self.variables else 404
            result = {"name": name, "value": self.variables[name]} if name in self.variables else {}
        elif endpoint.endswith("/variables"):
            assert method == "POST"
            if self.concurrent_variable == body["name"]:
                self.variables[body["name"]] = "concurrently-created-value"
            if body["name"] in self.variables:
                status, result = 409, {}
            else:
                self.writes.append(("gh", method, endpoint, body))
                self.variables[body["name"]] = body["value"]
                status, result = 201, {}
        elif "/environments/" in endpoint:
            if method == "PUT":
                # GitHub ignores conditional PUT headers: it is an upsert.
                self.github_environment = {"name": "factory-stage", "protection_rules": []}
                self.writes.append(("gh", method, endpoint, body))
                status, result = 200, self.github_environment
            else:
                status, result = (200, self.github_environment) if self.github_environment else (404, {})
        else:
            raise AssertionError(argv)
        text = f"HTTP/2.0 {status}\r\nContent-Type: application/json\r\n\r\n" + json.dumps(result)
        return SimpleNamespace(returncode=0 if status < 400 else 1, stdout=text.encode(), stderr=b"SECRET CLOUD ERROR")

    def open(self, req, timeout):
        method, url = req.get_method(), req.full_url
        parsed = urlsplit(url)
        headers = {k.lower(): v for k, v in req.header_items()}
        assert headers["authorization"].startswith("Bearer header.")
        body = json.loads(req.data) if req.data and req.data.startswith(b"{") else req.data
        self.calls.append((method, url, copy.deepcopy(body), headers))
        identifier = unquote(parsed.path).lower()
        if (method, identifier) in self.fail:
            return Response(self.fail[(method, identifier)], {"error": "SECRET HTTP BODY"})
        if parsed.hostname == "management.azure.com":
            if method == "GET":
                if identifier.endswith("/permissions"):
                    return Response(200, {"value": self.management_permissions})
                if identifier.endswith("/roleassignments"):
                    return Response(200, {"value": [v for k, v in self.resources.items() if "/roleassignments/" in k]})
                if identifier.endswith("/denyassignments"):
                    return Response(200, {"value": self.denies})
                if identifier.endswith("/federatedidentitycredentials"):
                    return Response(200, {"value": [v for k, v in self.resources.items()
                                                   if k.startswith(identifier + "/")]})
                if identifier.endswith("/microsoft.storage/storageaccounts"):
                    return Response(200, {"value": [v for k, v in self.resources.items()
                                                   if "/storageaccounts/" in k and k.count("/") == 8]})
                return Response(200, self.resources[identifier], {"ETag": '"arm-' + identifier + '"'}) if identifier in self.resources else Response(404)
            assert method == "PUT", "No DELETE, PATCH, login, account switch or replacement!"
            # Model documented ARM upserts, not an invented conditional-create
            # guarantee; the core requires serialized-provisioning acknowledgment.
            self.writes.append(("arm", method, identifier, copy.deepcopy(body)))
            value = dict(body, id=identifier)
            if "/userassignedidentities/" in identifier and "/federatedidentitycredentials/" not in identifier:
                value["properties"] = copy.deepcopy(self.identity_properties)
            elif "/roleassignments/" in identifier:
                value["properties"]["scope"] = identifier.split("/providers/microsoft.authorization/roleassignments/")[0]
            self.resources[identifier] = value
            return Response(201, value)
        if parsed.hostname == "dev.azure.com":
            tenant = json.loads(base64.urlsafe_b64decode(headers["authorization"].split(".")[1] + "=="))["tid"]
            assert tenant == ADO_TENANT
            if "/_apis/projects/" in identifier:
                return Response(200, {"id": PROJECT, "name": "project"})
            if "/_apis/git/repositories/" in identifier:
                return Response(200, {"name": "repo", "project": {"id": PROJECT}})
            if method == "GET":
                return Response(200, {"count": 1 if self.ado_endpoint else 0, "value": [self.ado_endpoint] if self.ado_endpoint else []})
            assert method == "POST" and not self.ado_endpoint
            assert body["authorization"]["parameters"]["serviceprincipalid"] == CLIENT
            assert body["serviceEndpointProjectReferences"][0]["projectReference"] == {"id": PROJECT, "name": "project"}
            self.ado_endpoint = copy.deepcopy(body)
            self.ado_endpoint["data"].update(workloadIdentityFederationIssuer="https://vstoken.dev.azure.com/remote-issued-org-id",
                                             workloadIdentityFederationSubject="sc://real-org/project/factory-stage")
            self.writes.append(("ado", method, identifier, body))
            return Response(200, self.ado_endpoint)
        assert parsed.hostname == urlsplit(self.request["coordinates"]["account_url"]).hostname
        container_id = self.request["account_id"] + "/blobservices/default/containers/" + self.request["coordinates"]["container"]
        if parsed.query == "restype=container":
            if method == "HEAD":
                return Response(200 if container_id in self.resources else 404, headers={"ETag": '"container"'})
            assert method == "PUT" and not body
            assert "if-none-match" not in headers and "x-ms-blob-public-access" not in headers
            if self.concurrent_container:
                self.resources[container_id] = {"id": container_id, "properties": {"publicAccess": "Blob"}}
            if container_id in self.resources:
                return Response(409)
            self.resources[container_id] = {"id": container_id, "properties": {"publicAccess": "None"}}
            self.writes.append(("storage", method, "container:" + self.request["coordinates"]["container"], body))
            return Response(201)
        blob = unquote(parsed.path).split("/", 2)[2]
        if method in ("GET", "HEAD"):
            if blob not in self.blobs:
                return Response(404)
            value, etag = self.blobs[blob]
            if method == "HEAD":
                length = len(value) if isinstance(value, bytes) else len(en.canonical(value))
                return Response(200, headers={"ETag": etag, "content-length": str(length)})
            return Response(200, value, {"ETag": etag})
        assert method == "PUT"
        if self.concurrent_enrollment and blob == self.request["coordinates"]["coordination_blob"]:
            return Response(412)
        if "if-none-match" in headers:
            if blob in self.blobs:
                return Response(412)
        else:
            assert "if-match" in headers
            if blob not in self.blobs or self.blobs[blob][1] != headers["if-match"]:
                return Response(412)
        self.etag += 1
        self.blobs[blob] = copy.deepcopy(body if body is not None else b""), f'"blob-{self.etag}"'
        self.writes.append(("storage", method, blob, copy.deepcopy(body)))
        return Response(201)

    def existing_identity(self):
        self.resources[self.request["identity_id"]] = {
            "id": self.request["identity_id"], "properties": copy.deepcopy(self.identity_properties)}

    def existing_storage(self):
        self.resources[self.request["account_id"]] = {
            "id": self.request["account_id"], "properties": {
                "allowSharedKeyAccess": False, "allowBlobPublicAccess": False, "supportsHttpsTrafficOnly": True,
                "minimumTlsVersion": "TLS1_2", "publicNetworkAccess": "Disabled", "networkAcls": {"defaultAction": "Deny"}}}
        if en._common_mode(self.request):
            self.resources[self.request["account_id"]]["properties"].update(
                isHnsEnabled=True, allowSharedKeyAccess=True)
        identifier = self.request["account_id"] + "/blobservices/default/containers/" + self.request["coordinates"]["container"]
        self.resources[identifier] = {"id": identifier, "properties": {"publicAccess": "None"}}

    def provision_prerequisites(self):
        """Fixture state provisioned independently, never by the helper."""
        self.existing_identity()
        self.existing_storage()
        route = self.request["route"]
        issuer = "https://token.actions.githubusercontent.com"
        subject = "repo:org/repo:environment:" + route["auth_namespace"]
        if route["kind"] == "ado":
            issuer = "https://vstoken.dev.azure.com/remote-issued-org-id"
            subject = "sc://real-org/project/" + route["auth_namespace"]
            self.ado_endpoint = {
                "id": PROJECT, "name": route["auth_namespace"], "type": "azurerm", "isReady": True, "isShared": False,
                "authorization": {"scheme": "WorkloadIdentityFederation", "parameters": {
                    "tenantid": TENANT, "serviceprincipalid": self.identity_properties["clientId"]}},
                "data": {"subscriptionId": SUB, "workloadIdentityFederationIssuer": issuer,
                         "workloadIdentityFederationSubject": subject},
                "serviceEndpointProjectReferences": [{"projectReference": {"id": PROJECT, "name": "project"}}]}
        identifier = self.request["identity_id"] + "/federatedidentitycredentials/af-" + en.digest(route)[:24]
        self.resources[identifier] = {"id": identifier, "properties": {
            "issuer": issuer, "subject": subject, "audiences": ["api://AzureADTokenExchange"]}}
        storage_scope = (self.request["account_id"] + "/blobservices/default/containers/" +
                         self.request["coordinates"]["container"])
        roles = [(self.identity_properties["principalId"], grant["scope"], grant["role_definition_id"])
                 for grant in self.request["deployment_roles"]]
        roles += [(principal, storage_scope, f"/subscriptions/{SUB}/providers/microsoft.authorization/roledefinitions/{en.DATA_ROLE}")
                  for principal in (OPERATOR, self.identity_properties["principalId"])]
        for principal, scope, definition in roles:
            identifier = scope + "/providers/microsoft.authorization/roleassignments/" + str(en.uuid5(
                en.NAMESPACE_URL, scope + ":" + principal + ":" + definition))
            self.resources[identifier] = {"id": identifier, "properties": {
                "scope": scope, "principalId": principal, "roleDefinitionId": definition}}


def enroll(req, fake, ack=True):
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=ack)
    assert not fake.cloud.read_only is False
    return en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                     acknowledge_exclusive_writer_governance=ack)


def common_options(**overrides):
    return {
        "coordination_storage_mode": "factory-common",
        "coordination_account_id": f"/subscriptions/{SUB}/resourcegroups/common/providers/microsoft.storage/storageaccounts/esmlsaltedcommon001",
        **overrides,
    }


def common_creation():
    return {
        "location": "swedencentral", "kind": "StorageV2", "sku": {"name": "Standard_GRS"},
        "tags": {"canonical": "frozen-common-plan"}, "identity": {"type": "None"},
        "properties": {
            "isHnsEnabled": True, "allowSharedKeyAccess": True, "allowBlobPublicAccess": False,
            "supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2", "accessTier": "Hot",
            "publicNetworkAccess": "Disabled",
            "networkAcls": {"defaultAction": "Deny", "bypass": "AzureServices", "ipRules": [], "virtualNetworkRules": []},
        },
    }


def canonical_common_parameters():
    return {"location": "swedencentral", "locationSuffix": "sdc", "env": "test",
            "commonLakeNamePrefixMax8chars": "mrvel", "commonResourceSuffix": "-001",
            "tags": {"owner": "canonical-common-plan"}}


def naming_identity(name, group):
    return {"id": group + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/" + name,
            "properties": {"tenantId": TENANT, "clientId": CLIENT, "principalId": PRINCIPAL}}


@pytest.mark.parametrize("kind", ["cmk", "project", "aca", "evaluated-no-mi"])
def test_pure_common_resolver_uses_authoritative_salt_not_random_mi_suffix(workspace, kind):
    group = f"/subscriptions/{SUB}/resourcegroups/common"
    params = canonical_common_parameters()
    account = group + "/providers/microsoft.storage/storageaccounts/mrvelx46jfesml001test"
    kwargs = {"tenant_id": TENANT}
    if kind == "evaluated-no-mi":
        kwargs["evaluated_account_id"] = account
    else:
        name = ("id-cmn-cmk-test-x46jf-001" if kind == "cmk" else
                "mi-" + ("aca-" if kind == "aca" else "") + "prj017-sdc-test-x46jfc2ebe6a898-001")
        evidence = naming_identity(name, group if kind == "cmk" else GROUP)
        kwargs.update(naming_identity=evidence, naming_identity_id=evidence["id"])
        if kind != "cmk":
            kwargs["project_naming"] = {"resource_group_id": GROUP, "projectNumber": "017",
                                       "resourceSuffix": "-002", "keepMIandKVsuffixAs001": True}
    before = copy.deepcopy((params, kwargs))
    resolved = en.resolve_factory_common_storage(group, params, **kwargs)
    assert resolved["coordination_account_id"] == account
    assert (params, kwargs) == before
    body = resolved["coordination_account_creation"]
    assert body["sku"] == {"name": "Standard_ZRS"}
    assert body["properties"]["encryption"]["keySource"] == "Microsoft.Storage"
    assert body["properties"]["keyPolicy"] == {"keyExpirationPeriodInDays": 14}
    assert body["properties"]["networkAcls"] == {
        "defaultAction": "Deny", "bypass": "AzureServices", "ipRules": [], "virtualNetworkRules": []}
    req = request(workspace, **resolved)
    fake = Fake(req, provisioned=False)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert fake.resources[account]["properties"] == body["properties"]
    assert not any("c2ebe6a898" in write[2] or "lake3" in write[2] for write in fake.writes)


@pytest.mark.parametrize("case,code", [
    ("missing-evidence", "canonical-common-naming-evidence-required"),
    ("no-identity-read", "canonical-naming-identity-read-required"),
    ("wrong-tenant", "canonical-naming-identity-tenant"),
    ("wrong-id", "canonical-naming-identity-id"),
    ("wrong-rg", "canonical-naming-identity-scope"),
    ("afwriter", "canonical-naming-identity-pattern"),
    ("wrong-env", "canonical-naming-identity-pattern"),
    ("contradictory-evidence", "canonical-common-naming-evidence-conflict"),
    ("wrong-evaluated-rg", "canonical-common-account-scope-conflict"),
    ("manual-salt", "canonical-common-parameters-required"),
    ("cmk", "common-cmk-identity-key-access"),
    ("unknown-override", "canonical-common-parameters-required"),
    ("unresolved-prefix", "invalid-canonical-common-naming-parameters"),
    ("invalid-whitelist", "invalid-canonical-common-ip-whitelist"),
])
def test_pure_common_resolver_blocks_unproven_or_conflicting_creation(case, code):
    group = f"/subscriptions/{SUB}/resourcegroups/common"
    params = canonical_common_parameters()
    identity = naming_identity("id-cmn-cmk-test-x46jf-001", group)
    kwargs = {"tenant_id": TENANT, "naming_identity": identity, "naming_identity_id": identity["id"]}
    if case == "missing-evidence":
        kwargs = {"tenant_id": TENANT}
    elif case == "no-identity-read":
        kwargs.pop("naming_identity")
    elif case == "wrong-tenant":
        identity["properties"]["tenantId"] = ADO_TENANT
    elif case == "wrong-id":
        kwargs["naming_identity_id"] += "other"
    elif case == "wrong-rg":
        group = GROUP
    elif case in ("afwriter", "wrong-env"):
        identity["id"] = identity["id"].rsplit("/", 1)[0] + "/" + (
            "afwriter-0123456789abcdef" if case == "afwriter" else "id-cmn-cmk-dev-x46jf-001")
        kwargs["naming_identity_id"] = identity["id"]
    elif case == "contradictory-evidence":
        kwargs["evaluated_account_id"] = group + "/providers/Microsoft.Storage/storageAccounts/mrvelabcdeesml001test"
    elif case == "wrong-evaluated-rg":
        kwargs["evaluated_account_id"] = GROUP + "/providers/Microsoft.Storage/storageAccounts/mrvelx46jfesml001test"
    elif case == "manual-salt":
        params["salt"] = "abcde"
    elif case == "cmk":
        params["cmk"] = True
    elif case == "unknown-override":
        params["datalakeName_param"] = "ignored-by-canonical-bicep"
    elif case == "unresolved-prefix":
        params["commonLakeNamePrefixMax8chars"] = "<todo>"
    elif case == "invalid-whitelist":
        params["IPwhiteList"] = "not-an-ip"
    with pytest.raises(en.EnrollmentError, match=code):
        en.resolve_factory_common_storage(group, params, **kwargs)


def test_common_resolver_custom_frozen_parameters_and_name_length():
    group = f"/subscriptions/{SUB}/resourcegroups/common"
    params = canonical_common_parameters() | {
        "commonLakeNamePrefixMax8chars": "custom", "commonResourceAbbreviation": "data",
        "commonResourceSuffix": "-003", "env": "prod", "skuNameStorage": "Standard_GRS",
        "IPwhiteList": "203.0.113.9,198.51.100.0/24"}
    identity = naming_identity("id-cmn-cmk-prod-abcde-003", group)
    resolved = en.resolve_factory_common_storage(
        group, params, tenant_id=TENANT, naming_identity=identity, naming_identity_id=identity["id"])
    assert resolved["coordination_account_id"].endswith("/customabcdedata003prod")
    assert resolved["coordination_account_creation"]["sku"]["name"] == "Standard_GRS"
    assert resolved["coordination_account_creation"]["properties"]["networkAcls"]["ipRules"] == [
        {"action": "Allow", "value": "203.0.113.9"}, {"action": "Allow", "value": "198.51.100.0/24"}]
    params["commonResourceAbbreviation"] = "toolongabbr"
    with pytest.raises(en.EnrollmentError, match="invalid-canonical-common-account-name"):
        en.resolve_factory_common_storage(
            group, params, tenant_id=TENANT, naming_identity=identity, naming_identity_id=identity["id"])


def test_common_resolver_matches_canonical_bicep_not_unused_override():
    bicep = ROOT / "environment_setup" / "aifactory" / "bicep"
    common = (bicep / "esml-common" / "main" / "13-rgLevel.bicep").read_text()
    naming = (bicep / "modules" / "common" / "CmnAIfactoryNaming.bicep").read_text()
    lake = (bicep / "modules" / "dataLake.bicep").read_text()
    assert "var uniqueInAIFenv = substring(uniqueString(esmlCommonResourceGroup.id), 0, 5)" in common
    assert "var datalakeName = '${commonLakeNamePrefixMax8chars}${uniqueInAIFenv}${commonResourceAbbreviation}${replace(commonResourceSuffix,'-','')}${env}'" in common
    assert "param skuNameStorage string = 'Standard_ZRS'" in common
    assert "param commonResourceAbbreviation string = 'esml'" in common
    assert "var miPrjName = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${miSuffix}'" in naming
    for clause in ("param keyExpirationPeriodInDays int = 14", "publicNetworkAccess:'Disabled'",
                   "isHnsEnabled: true", "allowSharedKeyAccess: true"):
        assert clause in lake


@pytest.mark.parametrize("container_exists", [False, True])
def test_common_reuses_shared_key_adls_and_never_touches_lake3(workspace, container_exists):
    req = request(workspace, **common_options())
    fake = Fake(req)
    container = en._container_id(req)
    if not container_exists:
        del fake.resources[container]
    lake = req["account_id"] + "/blobservices/default/containers/lake3"
    lake_body = {"id": lake, "properties": {"publicAccess": "None", "metadata": {"business": "preserve"}}}
    fake.resources[lake] = copy.deepcopy(lake_body)
    account_body = copy.deepcopy(fake.resources[req["account_id"]])
    register = (workspace / "azurefactory" / "register.json").read_bytes()
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert review["can_ensure"] and review["coordination"]["container"] == "factorymeta"
    assert review["coordination"]["storage_mode"] == "factory-common"
    assert review["coordination"]["coordination_blob"] == "coordination.json"
    assert "account-and-key-administrators-can-bypass-or-destroy-coordination" in review["warnings"]
    assert review["lifecycle_protection"]["resource_group_id"].endswith("/common")
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert fake.resources[lake] == lake_body and fake.resources[req["account_id"]] == account_body
    assert not any(write[2] in (lake, req["account_id"]) for write in fake.writes)
    assert sum(write[0] == "arm" and write[2] == container for write in fake.writes) == (not container_exists)
    count = len(fake.writes)
    assert enroll(req, fake)["status"] == "unchanged"
    assert len(fake.writes) == count
    assert (workspace / "azurefactory" / "register.json").read_bytes() == register
    assert all("listkeys" not in url.lower() and "sig=" not in url.lower() for _, url, *_ in fake.calls)
    assert not any("lake3" in url for _, url, *_ in fake.calls)


def test_common_missing_creates_only_exact_canonical_hns_account_before_metadata_rbac(workspace):
    body = common_creation()
    req = request(workspace, **common_options(coordination_account_creation=body))
    fake = Fake(req, provisioned=False)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    account_writes = [write for write in fake.writes if write[0] == "arm" and "/storageaccounts/" in write[2]
                     and "/blobservices/" not in write[2]]
    assert len(account_writes) == 1 and account_writes[0][2:] == (req["account_id"], body)
    assert not any("aflock" in str(write) or "lake3" in str(write) for write in fake.writes)
    container = en._container_id(req)
    container_index = next(index for index, write in enumerate(fake.writes) if write[2] == container)
    data_grants = [(index, write) for index, write in enumerate(fake.writes)
                   if write[0] == "arm" and "/roleassignments/" in write[2]
                   and write[3]["properties"]["roleDefinitionId"].endswith(en.DATA_ROLE)]
    assert len(data_grants) == 2
    assert all(index > container_index and write[2].startswith(container + "/providers/") for index, write in data_grants)
    first_blob = next(index for index, write in enumerate(fake.writes) if write[0] == "storage")
    assert all(index < first_blob for index, _ in data_grants)
    assert result["lifecycle_protection"]["account_id"] == req["account_id"]
    count = len(fake.writes)
    assert enroll(req, fake)["status"] == "unchanged"
    assert len(fake.writes) == count


def test_common_missing_requires_exact_id_and_reviewed_creation_policy(workspace):
    with pytest.raises(en.EnrollmentError, match="canonical-common-account-id-required"):
        request(workspace, coordination_storage_mode="factory-common")
    req = request(workspace, **common_options())
    fake = Fake(req, provisioned=False)
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert "canonical-common-account-creation-required" in review["blockers"]
    assert not review["can_ensure"] and not fake.writes
    with pytest.raises(en.EnrollmentError, match="business-container"):
        request(workspace, **common_options(container="lake3"))
    with pytest.raises(en.EnrollmentError, match="coordination-resource-group-conflict"):
        request(workspace, **common_options(coordination_resource_group_id=GROUP))


@pytest.mark.parametrize("field,value,expected", [
    ("isHnsEnabled", False, "canonical-security"),
    ("allowBlobPublicAccess", True, "canonical-security"),
    ("allowSharedKeyAccess", None, "canonical-security"),
    ("minimumTlsVersion", "TLS1_0", "canonical-security"),
    ("publicNetworkAccess", "Enabled", "private-network"),
    ("networkAcls", {"defaultAction": "Allow", "bypass": "AzureServices"}, "private-network"),
])
def test_common_creation_rejects_noncanonical_security(workspace, field, value, expected):
    body = common_creation()
    body["properties"][field] = value
    with pytest.raises(en.EnrollmentError, match=expected):
        request(workspace, **common_options(coordination_account_creation=body))


@pytest.mark.parametrize("field,value,expected", [
    ("isHnsEnabled", False, "hns-required"),
    ("allowBlobPublicAccess", True, "security-policy"),
    ("supportsHttpsTrafficOnly", False, "security-policy"),
    ("minimumTlsVersion", "TLS1_0", "security-policy"),
    ("publicNetworkAccess", "Enabled", "network-policy-conflict"),
    ("networkAcls", {"defaultAction": "Allow"}, "private-network-policy"),
])
def test_common_reuse_security_conflict_never_updates_storage(workspace, field, value, expected):
    req = request(workspace, **common_options())
    fake = Fake(req)
    fake.resources[req["account_id"]]["properties"][field] = value
    with pytest.raises(en.EnrollmentError, match=expected):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


@pytest.mark.parametrize("target,method,status", [
    ("account", "GET", 403), ("container", "GET", 403), ("data", "HEAD", 403), ("data", "HEAD", 401),
])
def test_common_denied_or_inaccessible_is_never_missing(workspace, target, method, status):
    req = request(workspace, **common_options())
    fake = Fake(req)
    identifier = {"account": req["account_id"], "container": en._container_id(req), "data": "/factorymeta"}[target]
    fake.fail[(method, identifier)] = status
    with pytest.raises(en.EnrollmentError, match=(
            "private-routing-dns-or-entra-access-required" if target == "data" else f"remote-request-failed-{status}")):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_common_private_creation_blocked_until_routing_without_public_fallback(workspace, monkeypatch):
    req = request(workspace, **common_options(coordination_account_creation=common_creation()))
    fake = Fake(req, provisioned=False)
    fake.fail[("HEAD", "/factorymeta")] = 403
    monkeypatch.setattr(en.time, "sleep", lambda _: None)
    result = enroll(req, fake)
    assert result["status"] == "blocked" and result["reconciliation_required"]
    assert result["error"].startswith("common-storage-private-routing-dns-or-entra-access-required:")
    assert not result["binding_candidate"] and not fake.blobs and not fake.variables
    assert fake.resources[req["account_id"]]["properties"]["publicNetworkAccess"] == "Disabled"
    assert len([write for write in fake.writes if write[2] == req["account_id"]]) == 1
    del fake.fail[("HEAD", "/factorymeta")]
    assert enroll(req, fake)["enrollment_complete"]


def test_common_unreachable_private_endpoint_is_actionable_without_writes(workspace, monkeypatch):
    req = request(workspace, **common_options())
    fake = Fake(req)
    original = fake.open

    def disconnected(http_request, timeout):
        if ".blob.core.windows.net" in http_request.full_url:
            raise en.URLError("private endpoint DNS unavailable")
        return original(http_request, timeout)

    monkeypatch.setattr(fake, "open", disconnected)
    with pytest.raises(en.EnrollmentError, match="common-storage-private-routing-dns-or-entra-access-required:remote-request-uncertain"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_common_container_management_permission_is_separate_from_data_grant(workspace):
    req = request(workspace, **common_options())
    fake = Fake(req)
    del fake.resources[en._container_id(req)]
    fake.management_permissions = [{"actions": [], "dataActions": ["*"]}]
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"]
    assert "operator-common-container-arm-create-permission-required" in review["blockers"]
    assert not fake.writes


@pytest.mark.parametrize("resource,compatible", [("account", True), ("account", False), ("container", True), ("container", False)])
def test_common_concurrent_create_rechecks_and_never_overwrites(workspace, resource, compatible, monkeypatch):
    req = request(workspace, **common_options(coordination_account_creation=common_creation()))
    fake = Fake(req, provisioned=False)
    fake.existing_identity()
    if resource == "container":
        fake.existing_storage()
        del fake.resources[en._container_id(req)]
    original = en._create_arm
    identifier = req["account_id"] if resource == "account" else en._container_id(req)
    concurrent = (dict(common_creation(), id=identifier) if resource == "account"
                  else {"id": identifier, "properties": {"publicAccess": "None"}})
    if not compatible:
        concurrent["properties"]["isHnsEnabled" if resource == "account" else "publicAccess"] = False if resource == "account" else "Blob"

    def appear(cloud, target, api, body):
        if target == identifier:
            fake.resources[target] = copy.deepcopy(concurrent)
        return original(cloud, target, api, body)

    monkeypatch.setattr(en, "_create_arm", appear)
    result = enroll(req, fake)
    assert result["enrollment_complete"] is compatible, result
    assert not any(write[2] == identifier for write in fake.writes)
    assert fake.resources[identifier] == concurrent
    if not compatible:
        assert not fake.blobs and not fake.variables


def test_common_preserves_existing_namespace_and_rejects_split_locks(workspace):
    req = request(workspace, **common_options(container="reviewed-meta", coordination_blob="stable/enrollment.json"))
    fake = Fake(req)
    result = enroll(req, fake)
    doc = document(workspace)
    doc["bindings"] = {FACTORY: {"gha": result["binding_candidate"]}}
    save(workspace, doc)
    same = request(workspace, **common_options())
    assert same["coordinates"] == req["coordinates"]
    with pytest.raises(en.EnrollmentError, match="overlapping-coordination-namespaces-conflict"):
        request(workspace, **common_options(container="factorymeta"))
    with pytest.raises(en.EnrollmentError, match="overlapping-coordination-namespaces-conflict"):
        request(workspace, **common_options(coordination_account_id=req["account_id"] + "other"))


@pytest.mark.parametrize("deleting_group", [False, True])
def test_lifecycle_refuses_destroying_lease_storage_or_its_resource_group(workspace, deleting_group):
    spec = importlib.util.spec_from_file_location("enrollment_lifecycle_guard", ROOT / "bootstrap" / "lib" / "factory_lifecycle.py")
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    req = request(workspace, **common_options())
    group = req["account_id"].split("/providers/")[0]
    value = {"locks": req["coordinates"], "deletion": {
        "resource_groups": [{"id": group, "delete": deleting_group}],
        "resources": [{"id": req["account_id"], "delete": not deleting_group}],
    }}
    with pytest.raises(lifecycle.Blocked, match="coordination-.*-delete-forbidden"):
        lifecycle.protect_coordination_storage(value)
        value["deletion"]["resources"][0]["id"] = req["account_id"] + "unrelated"
        value["deletion"]["resources"][0]["delete"] = True
        value["deletion"]["resource_groups"][0]["delete"] = True
        lifecycle.protect_coordination_storage(value)
    value["deletion"]["resources"][0]["delete"] = False
    value["deletion"]["resource_groups"][0]["delete"] = False
    lifecycle.protect_coordination_storage(value)


def test_plan_is_cloud_read_only_and_does_not_print_secrets(workspace):
    req = request(workspace)
    fake = Fake(req)
    before = (workspace / "azurefactory" / "register.json").read_bytes()
    result = en.plan(req, cloud=fake.cloud)
    assert not result["can_ensure"]
    assert not result["enrollment_complete"]
    assert "exclusive-writer-governance-attestation-required" in result["blockers"]
    acknowledged = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert acknowledged["can_ensure"] and not acknowledged["enrollment_complete"]
    assert not acknowledged["blockers"]
    assert not fake.writes
    assert all(method in ("GET", "HEAD") for method, *_ in fake.calls)
    for review in (result, acknowledged):
        assert "SECRET" not in en.canonical(review).decode()
        assert "accessToken" not in en.canonical(review).decode()
    assert before == (workspace / "azurefactory" / "register.json").read_bytes()


@pytest.mark.parametrize("kind", ["gha", "ado"])
def test_safe_additions_and_second_fresh_ensure_has_zero_writes(workspace, kind):
    req = request(workspace, kind)
    fake = Fake(req)
    before = (workspace / "azurefactory" / "register.json").read_bytes()
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert result["status"] == "changed"
    assert not result["runtime_ready"] and result["publication_required"]
    binding = result["binding_candidate"]
    assert binding["deployment_object_id"] == PRINCIPAL != CLIENT
    assert binding["runner"]["os"] == "linux"
    assert set(binding) == {"contract_version", "orchestrator", "repository", "ref", "shared_remote",
                            "writer_id", "auth_namespace", "deployment_object_id", "runner", "locks", "targets"}
    enrollment = fake.blobs["coordination.json"][0]
    assert enrollment["writers"]["stage-writer"]["deployment_object_id"] == PRINCIPAL
    assert enrollment["scopes"][GROUP]["allow_delete"] is False
    assert binding["locks"]["coordination_hash"] == en.digest(enrollment)
    count = len(fake.writes)
    result = enroll(req, fake)
    assert result["status"] == "unchanged", result
    assert len(fake.writes) == count
    assert before == (workspace / "azurefactory" / "register.json").read_bytes()
    for argv, _ in fake.commands:
        assert "header." not in " ".join(argv)
        assert "graph" not in " ".join(argv)
    assert not any(x[0] == "arm" for x in fake.writes)
    assignments = [x for x in fake.resources.values() if "/roleassignments/" in x["id"]]
    assert {x["properties"]["principalId"] for x in assignments} == {PRINCIPAL, OPERATOR}
    assert all(x["properties"]["principalId"] != CLIENT for x in assignments)
    if kind == "gha":
        assert fake.variables["AZURE_CLIENT_ID"] == CLIENT
    else:
        fic = [x for x in fake.resources.values() if "/federatedidentitycredentials/" in x["id"]][0]
        assert fic["properties"]["issuer"] == fake.ado_endpoint["data"]["workloadIdentityFederationIssuer"]
        assert fic["properties"]["subject"] == fake.ado_endpoint["data"]["workloadIdentityFederationSubject"]
        assert "login.microsoftonline.com" not in fic["properties"]["issuer"]


def test_existing_identity_verified_via_arm_and_az_show(workspace):
    initial = request(workspace)
    req = request(workspace, identity_id=initial["identity_id"])
    fake = Fake(req)
    fake.existing_identity()
    result = en.plan(req, cloud=fake.cloud)
    assert "create-user-assigned-managed-identity" not in result["actions"]
    assert result["identity"]["client_id"] == CLIENT
    assert any(argv[1:3] == ["identity", "show"] for argv, _ in fake.commands)
    fake.resources[req["identity_id"]]["properties"]["principalId"] = CLIENT
    with pytest.raises(en.EnrollmentError, match="identifiers-conflict"):
        en.plan(req, cloud=fake.cloud)


@pytest.mark.parametrize("code", [401, 403, 409, 429, 500])
def test_arm_errors_are_never_absence(workspace, code):
    req = request(workspace)
    fake = Fake(req)
    fake.fail[("GET", req["identity_id"])] = code
    with pytest.raises(en.EnrollmentError, match=f"remote-request-failed-{code}"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_403_github_environment_never_replaced(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.fail[("GET", "repos/org/repo/environments/factory-stage")] = 403
    with pytest.raises(en.EnrollmentError, match="github-request-failed-403"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_attestation_is_not_implicitly_written(workspace):
    req = request(workspace)
    fake = Fake(req)
    review = en.plan(req, cloud=fake.cloud)
    assert not review["can_ensure"] and not review["enrollment_complete"]
    assert "exclusive-writer-governance-attestation-required" in review["blockers"]
    commands, calls = len(fake.commands), len(fake.calls)
    for consent in ({}, {"acknowledge_exclusive_writer_governance": False}):
        with pytest.raises(en.EnrollmentError, match="exclusive-writer-governance-attestation-required"):
            en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud, **consent)
    assert not fake.writes and not fake.blobs and not fake.variables
    assert len(fake.commands) == commands and len(fake.calls) == calls
    assert fake.cloud.read_only and not fake.cloud.serialized_provisioning
    result = enroll(req, fake, ack=True)
    assert result["enrollment_complete"], result


def test_existing_untagged_groups_are_blockers_not_retagged(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.resources[GROUP]["tags"] = {}
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert "existing-resource-group-ownership-not-proven:" + GROUP in review["blockers"]
    with pytest.raises(en.EnrollmentError, match="prerequisites-blocked"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not fake.writes
    assert fake.resources[GROUP]["tags"] == {}


def test_exact_environment_tenant_subscription_and_ambiguity(workspace):
    with pytest.raises(en.EnrollmentError, match="environment-mismatch"):
        en.load_request(workspace, FACTORY, SCALE, "dev", options())
    doc = document(workspace)
    doc["factories"][0]["scale_sets"].append(copy.deepcopy(doc["factories"][0]["scale_sets"][0]))
    save(workspace, doc)
    with pytest.raises(en.EnrollmentError, match="exact-registered-scaleset"):
        request(workspace)
    doc["factories"][0]["scale_sets"].pop()
    save(workspace, doc)
    req = request(workspace)
    fake = Fake(req)
    fake.token_tenant = ADO_TENANT
    with pytest.raises(en.EnrollmentError, match="selected-account-tenant-mismatch"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_plan_and_local_changes_invalidate_approval_before_writes(workspace):
    req = request(workspace)
    fake = Fake(req)
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    fake.resources[req["identity_id"]]["tags"] = {"changed": "externally"}
    with pytest.raises(en.EnrollmentError, match="plan-or-live-state-changed"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not fake.writes
    doc = document(workspace)
    doc["generation"] = "changed"
    save(workspace, doc)
    with pytest.raises(en.EnrollmentError, match="consumer-or-request-changed"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not fake.writes


def test_no_yes_or_changed_governance_consent(workspace):
    req = request(workspace)
    fake = Fake(req)
    review = en.plan(req, cloud=fake.cloud)
    with pytest.raises(en.EnrollmentError, match="explicit-yes"):
        en.ensure(req, review["plan_hash"], cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    with pytest.raises(en.EnrollmentError, match="plan-or-live-state-changed"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert not fake.writes


def test_existing_fic_conflict_is_never_patched(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_identity()
    name = req["identity_id"] + "/federatedidentitycredentials/af-" + en.digest(req["route"])[:24]
    fake.resources[name] = {"id": name, "properties": {
        "issuer": "https://foreign.example", "subject": "someone-else", "audiences": ["api://AzureADTokenExchange"]}}
    with pytest.raises(en.EnrollmentError, match="federated-credential-conflict"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_storage_policy_not_weakened_or_network_enabled(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_storage()
    fake.resources[req["account_id"]]["properties"]["allowSharedKeyAccess"] = True
    with pytest.raises(en.EnrollmentError, match="security-policy-not-compatible"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes
    fake.resources[req["account_id"]]["properties"]["allowSharedKeyAccess"] = False
    fake.resources[req["account_id"]]["properties"]["publicNetworkAccess"] = "Enabled"
    with pytest.raises(en.EnrollmentError, match="network-policy-conflict"):
        en.plan(req, cloud=fake.cloud)


def test_existing_github_environment_protection_is_unchanged(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_identity()
    protected = {"name": "factory-stage", "protection_rules": [{"type": "required_reviewers", "reviewers": ["operator"]}],
                 "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}}
    fake.github_environment = copy.deepcopy(protected)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert fake.github_environment == protected
    assert not any(x[0] == "gh" and x[1] == "PUT" for x in fake.writes)


def test_variable_conflict_and_custom_subject_are_blocked(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_identity()
    fake.github_environment = {"name": "factory-stage"}
    fake.variables["AZURE_CLIENT_ID"] = PRINCIPAL
    with pytest.raises(en.EnrollmentError, match="github-variable-conflict"):
        en.plan(req, cloud=fake.cloud)
    fake.variables.clear()
    fake.oidc_default = False
    with pytest.raises(en.EnrollmentError, match="custom-oidc-subject"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_etag_race_never_becomes_ready_or_retries_overwrite(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.concurrent_enrollment = True
    result = enroll(req, fake)
    assert result["status"] == "blocked" and result["reconciliation_required"]
    assert result["error"] == "remote-request-failed-412"
    assert not result["enrollment_complete"] and result["binding_candidate"] is None
    assert "coordination.json" not in fake.blobs
    calls = [x for x in fake.calls if x[0] == "PUT" and x[1].endswith("/coordination.json")]
    assert len(calls) == 1


def test_add_only_merge_preserves_other_writer_scopes_and_etag(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_identity()
    fake.existing_storage()
    other_scope = f"/subscriptions/{SUB}/resourcegroups/other"
    old = {"schema": 1, "protocol": "aifactory-physical-lock-v1", "enforcement": "all-writers-exclusive", "revision": 8,
           "writers": {"other-writer": {"kind": "ado", "repository": "https://dev.azure.com/org/other/_git/repo",
                                         "shared_remote": False}},
           "scopes": {other_scope: {"writers": ["other-writer"], "common_dependencies": []}}}
    fake.blobs["coordination.json"] = copy.deepcopy(old), '"original-etag"'
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    merged = fake.blobs["coordination.json"][0]
    assert merged["scopes"][other_scope] == old["scopes"][other_scope]
    assert merged["writers"]["other-writer"] == old["writers"]["other-writer"]
    assert merged["revision"] == 9
    put = [x for x in fake.calls if x[0] == "PUT" and x[1].endswith("coordination.json")]
    assert len(put) == 1 and put[0][3]["if-match"] == '"original-etag"'


def test_foreign_scope_and_writer_conflicts_cannot_be_replaced(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_identity()
    identity = en._identity(fake.resources[req["identity_id"]], req)
    value = en.merge_enrollment(None, req, identity)
    value["scopes"][GROUP]["target"]["factory_id"] = PROJECT
    with pytest.raises(en.EnrollmentError, match="existing-scope-conflict"):
        en.merge_enrollment(value, req, identity)
    value = en.merge_enrollment(None, req, identity)
    value["writers"]["stage-writer"]["deployment_object_id"] = CLIENT
    with pytest.raises(en.EnrollmentError, match="existing-writer-conflict"):
        en.merge_enrollment(value, req, identity)


def test_shared_dependencies_must_already_have_reviewed_writer(workspace):
    common = f"/subscriptions/{SUB}/resourcegroups/common"
    req = request(workspace, common_dependency_ids=[common])
    fake = Fake(req)
    fake.existing_identity()
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"]
    assert "common-dependency-writer-must-be-independently-enrolled" in review["blockers"]


def test_deterministic_namespace_is_not_factory_or_provider_partitioned(workspace):
    first = request(workspace)
    doc = document(workspace)
    doc["factories"][0]["id"] = PROJECT
    doc["factories"][0]["scale_sets"][0]["orchestrator"] = "ado"
    save(workspace, doc)
    second = en.load_request(workspace, PROJECT, SCALE, "stage", options("ado"))
    assert first["coordinates"] == second["coordinates"]
    assert first["account_id"] == second["account_id"]
    assert en.lock_blob(GROUP.upper()) == en.lock_blob(GROUP)
    assert en.default_coordination(SUB, TENANT) != en.default_coordination(SUB, ADO_TENANT)


def test_overlapping_provider_bindings_must_use_same_namespace(workspace):
    req = request(workspace)
    doc = document(workspace)
    doc["bindings"] = {FACTORY: {"ado": {
        "contract_version": 1, "orchestrator": "ado", "writer_id": "other-writer",
        "repository": "https://dev.azure.com/org/project/_git/repo", "ref": "refs/heads/main", "shared_remote": True,
        "locks": {"account_url": "https://foreignstore.blob.core.windows.net", "container": "factory-locks",
                  "coordination_blob": "coordination.json", "coordination_hash": "a" * 64, "revision": 1},
        "targets": [{"scale_set_id": SCALE, "resource_group_ids": [GROUP]}]}}}
    save(workspace, doc)
    with pytest.raises(en.EnrollmentError, match="overlapping-coordination"):
        request(workspace, coordination_account_id=req["account_id"])


@pytest.mark.parametrize("runner", [
    {"kind": "hosted", "os": "windows", "image": "windows-latest"},
    {"kind": "self-hosted", "os": "windows", "pool": "Windows VM"},
    {"kind": "self-hosted", "os": "linux", "labels": ["self-hosted"]},
])
def test_windows_prerequisite_vm_never_changes_linux_runtime_contract(workspace, runner):
    with pytest.raises(en.EnrollmentError, match="runner"):
        request(workspace, runner=runner)


def test_subscription_role_grants_and_unapproved_rg_creation_forbidden(workspace):
    with pytest.raises(en.EnrollmentError, match="invalid-resource-group-id"):
        request(workspace, deployment_roles=[{"scope": "/subscriptions/" + SUB, "role_definition_id": CONTRIBUTOR}])
    with pytest.raises(en.EnrollmentError, match="wider-group-creation-approval"):
        request(workspace, create_resource_group_ids=[GROUP])
    req = request(workspace, create_resource_group_ids=[GROUP], approved_group_creation_scope="/subscriptions/" + SUB)
    fake = Fake(req)
    del fake.resources[GROUP]
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    # An approved missing group is an executable create-or-update action, not a blocker.
    assert review["can_ensure"], review
    assert "create-resource-group:" + GROUP in review["actions"]
    assert not any(code.startswith("arm-create-only-contract-unverified") for code in review["blockers"])
    # Without the serialized-provisioning acknowledgment the upsert is refused with zero writes.
    with pytest.raises(en.EnrollmentError, match="exclusive-writer-governance-attestation-required"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud)
    assert not fake.writes and GROUP not in fake.resources
    # With the acknowledgment the approved group is created and tagged for ownership.
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert fake.resources[GROUP]["tags"] == {"aifactory.factory_id": FACTORY, "aifactory.scaleset_id": SCALE}
    assert any(write[0] == "arm" and write[2] == GROUP for write in fake.writes)


@pytest.mark.parametrize("method", ["DELETE", "PATCH"])
def test_cloud_delete_and_update_are_forbidden(workspace, method):
    req = request(workspace)
    fake = Fake(req)
    fake.cloud.read_only = False
    with pytest.raises(en.EnrollmentError, match="forbidden"):
        fake.cloud.http(method, en.ARM + GROUP, en.ARM + "/")
    assert not fake.calls


def test_storage_tokens_are_correct_audience_and_never_argv(workspace):
    req = request(workspace)
    fake = Fake(req)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    tokens = [argv for argv, _ in fake.commands if argv[1:3] == ["account", "get-access-token"]]
    assert any(en.STORAGE in argv for argv in tokens)
    for _, url, _, headers in fake.calls:
        if ".blob.core.windows.net/" in url:
            assert headers["x-ms-date"].endswith(" GMT")
            encoded = headers["authorization"].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            assert claims["aud"] == en.STORAGE
    assert all(not any("Bearer" in arg or "header." in arg for arg in argv) for argv, _ in fake.commands)


def test_invalid_token_audience_blocks_before_storage(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.token_audience = "https://graph.microsoft.com/"
    with pytest.raises(en.EnrollmentError, match="token-audience"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.calls and not fake.writes


def test_ado_uses_cached_tenant_account_without_changing_azure_default(workspace):
    req = request(workspace, "ado")
    fake = Fake(req)
    fake.ado_accounts.append({**fake.ado_accounts[1], "id": "66666666-6666-6666-6666-666666666666",
                              "accountName": "ADO@example.test"})
    fake.cloud.token(en.ADO_AUDIENCE, ADO_TENANT)
    fake.cloud.token(en.ADO_AUDIENCE, ADO_TENANT)
    fake.cloud.token(en.ARM + "/")
    tokens = [argv for argv, _ in fake.commands if argv[1:3] == ["account", "get-access-token"]]
    ado_tokens = [argv for argv in tokens if en.ADO_AUDIENCE in argv]
    assert len(ado_tokens) == 1
    assert ado_tokens[0][ado_tokens[0].index("--subscription") + 1] == ADO_SUB
    assert "--tenant" not in ado_tokens[0]
    assert tokens[-1][tokens[-1].index("--subscription") + 1] == SUB
    assert not fake.calls and not fake.writes


@pytest.mark.parametrize("change,code", [
    ("missing", "ado-tenant-account-unavailable"),
    ("disabled", "ado-tenant-account-unavailable"),
    ("blank-identity", "ado-account-identity-unverified"),
    ("ambiguous", "ado-tenant-account-ambiguous"),
    ("invalid-id", "invalid-guid"),
    ("invalid-metadata", "ado-account-metadata-invalid"),
])
def test_ado_account_selection_fails_closed_before_token_request(workspace, change, code):
    req = request(workspace, "ado")
    fake = Fake(req)
    if change == "missing":
        fake.ado_accounts.pop()
    elif change == "disabled":
        fake.ado_accounts[1]["state"] = "Disabled"
    elif change == "blank-identity":
        fake.ado_accounts[1]["accountName"] = ""
    elif change == "ambiguous":
        fake.ado_accounts.append({**fake.ado_accounts[1], "accountName": "other@example.test"})
    elif change == "invalid-id":
        fake.ado_accounts[1]["id"] = "not-an-id"
    else:
        fake.ado_accounts = {}
    with pytest.raises(en.EnrollmentError, match=code):
        fake.cloud.token(en.ADO_AUDIENCE, ADO_TENANT)
    assert all(argv[1:3] != ["account", "get-access-token"] for argv, _ in fake.commands)
    assert not fake.calls and not fake.writes


def test_ado_selected_account_token_still_requires_expected_tenant(workspace):
    req = request(workspace, "ado")
    fake = Fake(req)
    fake._token = lambda audience, tenant: Fake._token(fake, audience, TENANT)
    with pytest.raises(en.EnrollmentError, match="token-tenant-or-lifetime-mismatch"):
        fake.cloud.token(en.ADO_AUDIENCE, ADO_TENANT)
    assert not fake.calls and not fake.writes


def test_default_cli_runner_resolves_windows_command_extension(monkeypatch):
    command = r"C:\Program Files\Azure CLI\az.cmd"
    monkeypatch.setattr(en.shutil, "which", lambda name: command if name == "az" else None)
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(en.subprocess, "run", run)
    cloud = en.Cloud({}, opener=SimpleNamespace())
    assert cloud.az("account", "list", "--all") == {}
    assert calls[0][0] == [command, "account", "list", "--all", "--only-show-errors", "--output", "json"]
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 120


def test_default_cli_runner_reports_missing_executable(monkeypatch):
    monkeypatch.setattr(en.shutil, "which", lambda name: None)
    with pytest.raises(en.EnrollmentError, match="command-unavailable-or-failed"):
        en.Cloud({}, opener=SimpleNamespace()).az("account", "list", "--all")


def test_missing_org_auth_and_arm_prerequisites_never_return_ready(workspace):
    req = request(workspace, "ado")
    fake = Fake(req)
    fake.fail[("GET", "/org/_apis/projects/project")] = 403
    with pytest.raises(en.EnrollmentError, match="remote-request-failed-403"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes
    fake.fail.clear()
    # A missing coordination account is a documented create action, not a blocker.
    del fake.resources[req["account_id"]]
    del fake.resources[req["account_id"] + "/blobservices/default/containers/" + req["coordinates"]["container"]]
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert review["can_ensure"], review
    assert "create-secure-coordination-account" in review["actions"]
    assert not any(code.startswith("arm-create-only-contract-unverified") for code in review["blockers"])
    # An unreadable ARM state is still a hard error and is never inferred as absence.
    fake.fail[("GET", req["account_id"])] = 500
    with pytest.raises(en.EnrollmentError, match="remote-request-failed-500"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_zero_byte_lock_no_clobber_and_unexpected_content_blocks(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_storage()
    fake.blobs[en.lock_blob(GROUP)] = b"not-a-lock", '"other"'
    with pytest.raises(en.EnrollmentError, match="must-be-empty"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_closed_json_duplicate_keys_and_secret_options_rejected(workspace):
    with pytest.raises(en.EnrollmentError, match="duplicate-json-key"):
        en.parse_json(b'{"schema":1,"schema":2}')
    with pytest.raises(en.EnrollmentError, match="unknown-enrollment-option"):
        request(workspace, client_secret="synthetic-do-not-print")


def test_generated_enrollment_matches_actual_scoped_lifecycle_schema(workspace):
    spec = importlib.util.spec_from_file_location("enrollment_lifecycle_contract", ROOT / "bootstrap" / "lib" / "factory_lifecycle.py")
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    req = request(workspace)
    fake = Fake(req)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    binding = result["binding_candidate"]
    manifest = {"target": req["target"], "route": req["route"], "operation": "deploy-project", "deployment": {},
                "identity": {"deployment_object_id": PRINCIPAL},
                "locks": {"provider": "azure-blob-lease", **binding["locks"], "scopes": req["scopes"],
                          "common_dependencies": req["common_dependencies"]}}
    cloud = SimpleNamespace(request=lambda method, url, audience, **kwargs: (
        200, {}, fake.blobs["coordination.json"][0]))
    leases = lifecycle.BlobLocks(cloud, manifest)
    leases.verify_enrollment()
    assert lifecycle.BlobLocks.blob_name(GROUP.upper()) == en.lock_blob(GROUP)


def test_existing_identity_other_subscription_requires_same_tenant(workspace):
    identifier = f"/subscriptions/{PROJECT}/resourceGroups/identities/providers/Microsoft.ManagedIdentity/userAssignedIdentities/shared"
    req = request(workspace, identity_id=identifier)
    fake = Fake(req)
    fake.existing_identity()
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert any(argv[1:3] == ["identity", "show"] and argv[argv.index("--subscription") + 1] == PROJECT
               for argv, _ in fake.commands)
    fake.identity_subscription_tenant = ADO_TENANT
    with pytest.raises(en.EnrollmentError, match="identity-subscription-tenant-mismatch"):
        en.plan(req, cloud=fake.cloud)


def test_data_plane_403_stops_before_attestation(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.fail[("PUT", "/factory-locks/" + en.lock_blob(GROUP))] = 403
    result = enroll(req, fake)
    assert result["status"] == "blocked" and result["reconciliation_required"], result
    assert result["error"] == "remote-request-failed-403"
    assert "coordination.json" not in fake.blobs
    assert result["binding_candidate"] is None


def test_existing_ado_endpoint_wrong_identity_never_modified(workspace):
    req = request(workspace, "ado")
    fake = Fake(req)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    fake.ado_endpoint["authorization"]["parameters"]["serviceprincipalid"] = PRINCIPAL
    count = len(fake.writes)
    with pytest.raises(en.EnrollmentError, match="service-endpoint-identity-conflict"):
        en.plan(req, cloud=fake.cloud)
    assert len(fake.writes) == count


def test_ado_response_entra_issuer_is_preserved_not_constructed(workspace):
    req = request(workspace, "ado")
    fake = Fake(req)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    fake.ado_endpoint["data"]["workloadIdentityFederationIssuer"] = "https://login.microsoftonline.com/real-issued-tenant/v2.0"
    fake.ado_endpoint["data"]["workloadIdentityFederationSubject"] = "opaque-provider-issued-subject"
    provider = en._provider(fake.cloud, req, result["identity"])
    assert en._fic_properties(provider) == {
        "issuer": "https://login.microsoftonline.com/real-issued-tenant/v2.0", "subject": "opaque-provider-issued-subject",
        "audiences": ["api://AzureADTokenExchange"]}


def test_binding_candidate_preserves_unselected_targets(workspace):
    req = request(workspace)
    fake = Fake(req)
    result = enroll(req, fake)
    binding = copy.deepcopy(result["binding_candidate"])
    other = {"scale_set_id": PROJECT, "resource_group_ids": [f"/subscriptions/{SUB}/resourcegroups/other"],
             "common_dependency_ids": [],
             "execution": {"writer_id": "other-writer", "auth_namespace": "other-auth", "deployment_object_id": CLIENT,
                           "runner": {"kind": "hosted", "os": "linux", "image": "ubuntu-22.04"}}}
    binding["targets"].append(copy.deepcopy(other))
    doc = document(workspace)
    doc["bindings"] = {FACTORY: {"gha": binding}}
    save(workspace, doc)
    req2 = request(workspace)
    candidate = en.binding_candidate(req2, result["identity"], fake.blobs["coordination.json"][0])
    assert candidate["targets"][1] == other
    assert document(workspace)["bindings"][FACTORY]["gha"] == binding
    other_req = copy.deepcopy(req2)
    other_req["route"]["auth_namespace"] = "attempted-replacement"
    with pytest.raises(en.EnrollmentError, match="existing-binding-target-conflict"):
        en.binding_candidate(other_req, result["identity"], fake.blobs["coordination.json"][0])


def test_actual_container_public_access_is_blocked_without_updates(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_storage()
    identifier = req["account_id"] + "/blobservices/default/containers/" + req["coordinates"]["container"]
    fake.resources[identifier]["properties"]["publicAccess"] = "Blob"
    with pytest.raises(en.EnrollmentError, match="container-public-access"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_cli_unsafe_calls_are_not_a_backdoor(workspace):
    fake = Fake(request(workspace))
    with pytest.raises(en.EnrollmentError, match="unreviewed-cli-command"):
        fake.cloud.az("group", "delete", "--name", "anything")
    assert not fake.commands


def test_storage_global_name_collision_blocks_before_any_creation(workspace):
    req = request(workspace)
    fake = Fake(req, provisioned=False)
    fake.name_available = False
    with pytest.raises(en.EnrollmentError, match="global-name-unavailable"):
        en.plan(req, cloud=fake.cloud)
    assert not fake.writes


def test_noncanonical_existing_enrollment_cannot_partition_physical_lock(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_identity()
    identity = en._identity(fake.resources[req["identity_id"]], req)
    existing = en.merge_enrollment(None, req, identity)
    existing["scopes"][GROUP.upper()] = existing["scopes"].pop(GROUP)
    with pytest.raises(en.EnrollmentError, match="noncanonical-existing-enrollment-scope"):
        en.merge_enrollment(existing, req, identity)


def test_missing_github_environment_blocks_every_mutation(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.github_environment = None
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"]
    assert "github-environment-must-be-preprovisioned-no-atomic-create" in review["blockers"]
    assert "create-github-environment" not in review["actions"]
    with pytest.raises(en.EnrollmentError, match="prerequisites-blocked"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not fake.writes
    # An environment appearing in the GET/PUT gap cannot be overwritten even by
    # a direct provider call with the originally absent snapshot.
    provider = en._provider(fake.cloud, req, None)
    protected = {"name": "factory-stage", "protection_rules": [{"type": "required_reviewers"}]}
    fake.github_environment = copy.deepcopy(protected)
    fake.cloud.read_only = False
    with pytest.raises(en.EnrollmentError, match="preprovisioned"):
        en._create_provider(fake.cloud, req, {"provider": provider}, {"client_id": CLIENT})
    with pytest.raises(en.EnrollmentError, match="replacement-forbidden"):
        fake.cloud.gh("PUT", provider["path"], {})
    assert fake.github_environment == protected and not fake.writes


def test_github_variable_concurrent_duplicate_fails_without_overwrite(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.concurrent_variable = "AZURE_CLIENT_ID"
    result = enroll(req, fake)
    assert result["status"] == "blocked"
    assert result["error"] == "github-request-failed-409"
    assert result["binding_candidate"] is None and not result["enrollment_complete"]
    assert fake.variables == {"AZURE_CLIENT_ID": "concurrently-created-value"}
    attempts = [argv for argv, _ in fake.commands if argv[0] == "gh" and "POST" in argv]
    assert len(attempts) == 1
    assert not any("PUT" in argv or "PATCH" in argv or "If-None-Match: *" in argv
                   for argv, _ in fake.commands if argv[0] == "gh")


@pytest.mark.parametrize("conflict", [
    "different-writer", "target", "dependencies", "malformed", "unknown-writer", "existing-writer",
])
def test_missing_identity_validates_existing_enrollment_before_all_writes(workspace, conflict):
    req = request(workspace)
    fake = Fake(req, provisioned=False)
    fake.existing_storage()
    existing = en.merge_enrollment(None, req, {"principal_id": PRINCIPAL})
    if conflict == "existing-writer":
        expected = "existing-writer-without-verified-identity"
    else:
        writer = existing["writers"].pop("stage-writer")
        writer["auth_namespace"] = "another-auth"
        existing["writers"]["another-writer"] = writer
        existing["scopes"][GROUP]["writers"] = ["another-writer"]
        expected = "existing-scope-conflict"
        if conflict == "target":
            existing["scopes"][GROUP]["target"]["factory_id"] = PROJECT
        elif conflict == "dependencies":
            existing["scopes"][GROUP]["common_dependencies"] = [GROUP + "-missing"]
            expected = "invalid-existing-scope-dependencies"
        elif conflict == "malformed":
            existing["schema"] = 2
            expected = "invalid-existing-enrollment"
        elif conflict == "unknown-writer":
            existing["writers"].clear()
            expected = "invalid-existing-scope-writers"
    fake.blobs["coordination.json"] = copy.deepcopy(existing), '"existing"'
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"] and expected in review["blockers"]
    with pytest.raises(en.EnrollmentError, match="prerequisites-blocked"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not fake.writes
    assert fake.blobs["coordination.json"][0] == existing


def test_new_disjoint_target_accepts_independent_identity_under_shared_binding(workspace):
    first = request(workspace)
    fake = Fake(first)
    enrolled = enroll(first, fake)
    assert enrolled["enrollment_complete"], enrolled
    first_enrollment = copy.deepcopy(fake.blobs["coordination.json"][0])
    old_binding = copy.deepcopy(enrolled["binding_candidate"])
    doc = document(workspace)
    second_scale = dict(doc["factories"][0]["scale_sets"][0], id=PROJECT, suffix="002")
    doc["factories"][0]["scale_sets"].append(second_scale)
    doc["bindings"] = {FACTORY: {"gha": old_binding}}
    save(workspace, doc)
    second_group = GROUP + "-second"
    second_options = options() | {
        "writer_id": "second-writer", "auth_namespace": "second-environment", "resource_group_ids": [second_group],
        "deployment_roles": [{"scope": second_group, "role_definition_id": CONTRIBUTOR}]}
    second = en.load_request(workspace, FACTORY, PROJECT, "stage", second_options)
    assert second["identity_id"] != first["identity_id"]
    fake.request = second
    fake.cloud = en.Cloud(second, command_runner=fake.run, opener=fake)
    fake.resources[second_group] = {
        "id": second_group, "tags": {"aifactory.factory_id": FACTORY, "aifactory.scaleset_id": PROJECT}}
    fake.github_environment = {"id": 456, "name": "second-environment", "protection_rules": []}
    fake.variables = {}
    fake.identity_properties = {
        "tenantId": TENANT, "clientId": "55555555-5555-5555-5555-555555555555",
        "principalId": "66666666-6666-6666-6666-666666666666"}
    review = en.plan(second, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    # The disjoint target's own identity/FIC/roles/lease are creatable, not blockers.
    assert review["can_ensure"], review
    assert "create-user-assigned-managed-identity" in review["actions"]
    assert not any(code.startswith("arm-create-only-contract-unverified") for code in review["blockers"])
    result = enroll(second, fake)
    assert result["enrollment_complete"], result
    candidate = result["binding_candidate"]
    assert candidate["targets"][0] == old_binding["targets"][0]
    assert candidate["deployment_object_id"] == PRINCIPAL
    assert candidate["targets"][1]["execution"] == {
        "writer_id": "second-writer", "auth_namespace": "second-environment",
        "deployment_object_id": fake.identity_properties["principalId"], "runner": second["route"]["runner"]}
    assert fake.blobs["coordination.json"][0]["scopes"][GROUP] == first_enrollment["scopes"][GROUP]
    assert fake.blobs["coordination.json"][0]["writers"]["stage-writer"] == first_enrollment["writers"]["stage-writer"]
    writes = len(fake.writes)
    assert enroll(second, fake)["status"] == "unchanged"
    assert len(fake.writes) == writes


def test_selected_existing_binding_still_requires_verified_identity(workspace):
    req = request(workspace)
    fake = Fake(req)
    binding = enroll(req, fake)["binding_candidate"]
    doc = document(workspace)
    doc["bindings"] = {FACTORY: {"gha": binding}}
    save(workspace, doc)
    req = request(workspace)
    empty = Fake(req, provisioned=False)
    review = en.plan(req, cloud=empty.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"]
    assert "existing-binding-without-verified-identity" in review["blockers"]
    with pytest.raises(en.EnrollmentError, match="prerequisites-blocked"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=empty.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not empty.writes


def deny(scope, actions=None, data_actions=None, **properties):
    return {"properties": {
        "scope": scope, "permissions": [{"actions": actions or [], "dataActions": data_actions or []}],
        "principals": [{"id": "00000000-0000-0000-0000-000000000000", "type": "SystemDefined"}],
        "excludePrincipals": [], "doNotApplyToChildScopes": False, **properties}}


@pytest.mark.parametrize("identity_exists", [False, True])
@pytest.mark.parametrize("case", [
    "delete-only", "noninherited-subscription", "unrelated-principal", "excluded-operator",
    "not-actions", "not-data-actions",
])
def test_nonapplicable_denies_preserve_add_only_enrollment(workspace, identity_exists, case):
    req = request(workspace)
    fake = Fake(req, provisioned=identity_exists)
    scope = "/subscriptions/" + SUB
    if case == "delete-only":
        value = deny(scope, ["*/delete"], ["*/delete"])
    elif case == "noninherited-subscription":
        value = deny(scope, ["*"], ["*"], doNotApplyToChildScopes=True)
    elif case == "unrelated-principal":
        value = deny(scope, ["Microsoft.Authorization/roleAssignments/write"],
                     principals=[{"id": PROJECT, "type": "User"}])
    elif case == "excluded-operator":
        value = deny(scope, ["Microsoft.Authorization/roleAssignments/write"],
                     excludePrincipals=[{"id": OPERATOR, "type": "User"}])
    elif case == "not-actions":
        value = deny(scope, ["*"])
        value["properties"]["permissions"][0]["notActions"] = ["*/read", "*/write", "*/action"]
    else:
        value = deny(scope, data_actions=["*"])
        value["properties"]["permissions"][0]["notDataActions"] = ["*/read", "*/write"]
    fake.denies = [value]
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert "deny-assignment-requires-independent-rights-review" not in review["blockers"], review
    # A non-applicable deny never turns a creatable target into a blocker, whether the
    # identity already exists or the whole target is provisioned green-field this run.
    assert review["can_ensure"], review
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert fake.denies == [value]


@pytest.mark.parametrize("case", [
    "operator-write", "writer-deployment", "lease-data", "excluded-operator-not-writer",
    "unresolved-group", "unknown-principal-type", "excluded-group-unresolved", "conditional-deny",
    "malformed-permissions", "identity-parent", "inherited-management-group", "resource-write", "resource-family",
    "deployment-wrapper-exempt",
])
def test_applicable_or_unresolved_denies_block_every_mutation(workspace, case):
    req = request(workspace)
    fake = Fake(req)
    fake.existing_identity()
    scope = "/subscriptions/" + SUB
    if case == "operator-write":
        identifier = next(key for key in fake.resources if "/roleassignments/" in key)
        del fake.resources[identifier]
        value = deny(scope, ["Microsoft.Authorization/roleAssignments/write"],
                     principals=[{"id": OPERATOR, "type": "User"}])
    elif case == "writer-deployment":
        value = deny(GROUP, ["Microsoft.Resources/deployments/write"],
                     principals=[{"id": PRINCIPAL, "type": "ServicePrincipal"}])
    elif case == "lease-data":
        value = deny(req["account_id"], data_actions=[
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"])
    elif case == "excluded-operator-not-writer":
        value = deny(scope, ["*/write"], excludePrincipals=[{"id": OPERATOR, "type": "User"}])
    elif case == "unresolved-group":
        value = deny(scope, ["*/write"], principals=[{"id": PROJECT, "type": "Group"}])
    elif case == "unknown-principal-type":
        value = deny(scope, ["*/write"], principals=[{"id": PROJECT}])
    elif case == "excluded-group-unresolved":
        value = deny(scope, ["*/write"], excludePrincipals=[{"id": PROJECT, "type": "Group"}])
    elif case == "conditional-deny":
        value = deny(scope, ["*/write"], condition="unresolved")
    elif case == "malformed-permissions":
        value = deny(scope, permissions=None)
    elif case == "identity-parent":
        identifier = next(key for key in fake.resources if "/federatedidentitycredentials/" in key)
        del fake.resources[identifier]
        value = deny(req["identity_id"], ["Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials/write"])
    elif case == "resource-write":
        value = deny(GROUP + "/providers/microsoft.compute/virtualmachines/existing", ["Microsoft.Compute/virtualMachines/write"])
    elif case == "resource-family":
        value = deny(GROUP, ["Microsoft.Compute/*"])
    elif case == "deployment-wrapper-exempt":
        value = deny(GROUP, ["*"])
        value["properties"]["permissions"][0]["notActions"] = ["Microsoft.Resources/deployments/*"]
    else:
        value = deny("/providers/Microsoft.Management/managementGroups/parent", ["*/write"])
    fake.denies = [value]
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"], review
    assert "deny-assignment-requires-independent-rights-review" in review["blockers"]
    with pytest.raises(en.EnrollmentError, match="prerequisites-blocked"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not fake.writes


@pytest.mark.parametrize("resource", ["group", "identity", "storage", "federation", "role"])
def test_missing_arm_prerequisites_are_created_under_serialized_provisioning(workspace, resource):
    req = request(workspace, create_resource_group_ids=[GROUP],
                  approved_group_creation_scope="/subscriptions/" + SUB)
    fake = Fake(req)
    identifiers = {
        "group": GROUP, "identity": req["identity_id"], "storage": req["account_id"],
        "federation": next(key for key in fake.resources if "/federatedidentitycredentials/" in key),
        "role": next(key for key in fake.resources if "/roleassignments/" in key),
    }
    identifier = identifiers[resource]
    del fake.resources[identifier]
    if resource == "storage":
        del fake.resources[req["account_id"] + "/blobservices/default/containers/" + req["coordinates"]["container"]]
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    # A missing ARM object is an executable create-or-update action, never a blocker.
    assert review["can_ensure"], review
    assert review["actions"]
    assert not any(code.startswith("arm-create-only-contract-unverified") for code in review["blockers"])
    # No fabricated conditional guarantee: the upsert is refused while the plan is
    # read-only, and again without a serialized-provisioning acknowledgment. An
    # invented If-None-Match header cannot bypass either gate.
    assert fake.cloud.serialized_provisioning is False
    with pytest.raises(en.EnrollmentError, match="plan-mutation-forbidden"):
        fake.cloud.arm("PUT", identifier, en.ROLE_API, data={}, headers={"If-None-Match": "*"})
    fake.cloud.read_only = False
    for operation in (
            lambda: en._create_arm(fake.cloud, identifier, en.ROLE_API, {}),
            lambda: fake.cloud.arm("PUT", identifier, en.ROLE_API, data={}, headers={"If-None-Match": "*"}),
            lambda: fake.cloud.http("PUT", en.ARM + identifier, en.ARM + "/", data={}, headers={"If-None-Match": "*"})):
        with pytest.raises(en.EnrollmentError, match="arm-serialized-provisioning-required"):
            operation()
    assert not fake.writes and identifier not in fake.resources
    fake.cloud.read_only = True
    # With the acknowledgment the missing object is created and the run converges.
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    assert identifier in fake.resources
    assert any(write[0] == "arm" and write[2] == identifier for write in fake.writes)
    count = len(fake.writes)
    assert enroll(req, fake)["status"] == "unchanged"
    assert len(fake.writes) == count


def test_green_field_creates_everything_and_grants_operator_before_container(workspace):
    req = request(workspace, create_resource_group_ids=[GROUP],
                  approved_group_creation_scope="/subscriptions/" + SUB)
    fake = Fake(req, provisioned=False)
    result = enroll(req, fake)
    assert result["enrollment_complete"], result
    kinds = {(write[0], write[1]) for write in fake.writes}
    assert ("arm", "PUT") in kinds and ("storage", "PUT") in kinds
    operator_grant = next(index for index, write in enumerate(fake.writes)
                          if write[0] == "arm" and "/roleassignments/" in write[2]
                          and write[3]["properties"]["principalId"] == OPERATOR)
    container = next(index for index, write in enumerate(fake.writes)
                     if write[0] == "storage" and str(write[2]).startswith("container:"))
    # The operator's blob-data role must be granted before the data-plane container create.
    assert operator_grant < container, fake.writes
    # A second reconcile is a pure no-op.
    writes = len(fake.writes)
    assert enroll(req, fake)["status"] == "unchanged"
    assert len(fake.writes) == writes


def test_create_arm_never_overwrites_and_converges(workspace):
    req = request(workspace)
    fake = Fake(req, provisioned=False)
    fake.cloud.read_only = False
    fake.cloud.serialized_provisioning = True
    identity_id = req["identity_id"]
    created = en._create_arm(fake.cloud, identity_id, en.IDENTITY_API, {"location": "swedencentral"})
    assert identity_id in fake.resources and created["properties"]["clientId"] == CLIENT
    puts = [write for write in fake.writes if write[0] == "arm" and write[1] == "PUT"]
    assert len(puts) == 1
    # A matching resource that appeared in the read-before-write gap converges with no
    # second, overwriting PUT: the concurrently created object is preserved verbatim.
    again = en._create_arm(fake.cloud, identity_id, en.IDENTITY_API, {"location": "must-not-apply"})
    assert again["location"] == "swedencentral"
    assert len([write for write in fake.writes if write[0] == "arm" and write[1] == "PUT"]) == 1
    fake.cloud.read_only = True
    fake.cloud.serialized_provisioning = False


def test_propagating_storage_put_retries_only_fresh_operator_grant(monkeypatch):
    sleeps = []
    monkeypatch.setattr(en.time, "sleep", lambda seconds: sleeps.append(seconds))

    class Stub:
        def __init__(self, outcomes):
            self.outcomes, self.attempts = list(outcomes), 0

        def storage(self, method, blob=None, data=None, headers=None, allowed=(200,)):
            self.attempts += 1
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, int):
                raise en.EnrollmentError("remote-request-failed-" + str(outcome))
            return outcome

    # A 403 is retried as RBAC replication only when this run created the operator grant.
    stub = Stub([403, 403, (201, {}, b"")])
    assert en._propagating_storage_put(stub, None, b"", None, (201,), True) == (201, {}, b"")
    assert stub.attempts == 3 and sleeps == [5, 5]
    # Without a fresh operator grant a 403 is never masked as propagation; it surfaces at once.
    stub = Stub([403])
    with pytest.raises(en.EnrollmentError, match="remote-request-failed-403"):
        en._propagating_storage_put(stub, None, b"", None, (201,), False)
    assert stub.attempts == 1
    # A non-authorization failure is never retried, even while a grant is propagating.
    stub = Stub([409])
    with pytest.raises(en.EnrollmentError, match="remote-request-failed-409"):
        en._propagating_storage_put(stub, None, b"", None, (201,), True)
    assert stub.attempts == 1


def test_excluded_operator_and_writer_are_not_blocked_by_blob_lease_deny(workspace):
    req = request(workspace)
    fake = Fake(req)
    fake.denies = [deny(req["account_id"], data_actions=[
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"],
        excludePrincipals=[{"id": OPERATOR, "type": "User"}, {"id": PRINCIPAL, "type": "ServicePrincipal"}])]
    result = enroll(req, fake)
    assert result["enrollment_complete"], result


def test_actual_arm_and_azure_cli_identity_shapes_agree_without_graph(workspace):
    req = request(workspace)
    rest = {"id": req["identity_id"], "name": req["identity_id"].rsplit("/", 1)[1],
            "location": "swedencentral", "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
            "tags": {}, "systemData": None,
            "properties": {"tenantId": TENANT, "clientId": CLIENT, "principalId": PRINCIPAL}}
    cli = {key: copy.deepcopy(value) for key, value in rest.items() if key != "properties"}
    cli.update(rest["properties"])
    cli["resourceGroup"] = req["identity_id"].split("/")[4]
    assert en._identity(rest, req) == en._identity(cli, req) == {
        "id": req["identity_id"], "tenant_id": TENANT, "client_id": CLIENT, "principal_id": PRINCIPAL}


@pytest.mark.parametrize("left,right,excluded,overlaps", [
    ("*", "*", (), True),
    ("*/delete", "*", (), False),
    ("*", "*", ("*",), False),
    ("*", "*", ("*/write",), False),
    ("*", "*", ("Microsoft.Resources/deployments/*",), True),
    ("Microsoft.Compute/*", "Microsoft.Resources/*", (), False),
    ("Microsoft.Compute/*", "Microsoft.Compute/virtualMachines/write", (), True),
    ("Microsoft.Compute/*", "*", ("Microsoft.Compute/*",), False),
    ("Microsoft.Compute/*", "*", ("Microsoft.Compute/virtualMachines/*",), True),
    ("Microsoft.*/*", "*", ("Microsoft.Compute/*", "Microsoft.Resources/*"), True),
    ("*Compute*/*/wr*", "*", ("*/read",), True),
])
def test_effective_write_permission_intersections_do_not_guess_wildcard_exemptions(left, right, excluded, overlaps):
    assert en._permission_patterns_overlap((left, right, "*/write"), excluded) is overlaps


@pytest.mark.parametrize("race", [False, True])
def test_private_container_uses_real_create_only_data_plane_contract(workspace, race):
    req = request(workspace)
    fake = Fake(req)
    container = req["account_id"] + "/blobservices/default/containers/" + req["coordinates"]["container"]
    del fake.resources[container]
    fake.concurrent_container = race
    result = enroll(req, fake)
    if race:
        assert result["status"] == "blocked"
        assert result["error"] == "remote-request-failed-409"
        assert not result["enrollment_complete"]
        assert fake.resources[container]["properties"]["publicAccess"] == "Blob"
        assert not fake.writes
    else:
        assert result["enrollment_complete"], result
        assert fake.resources[container]["properties"]["publicAccess"] == "None"
        count = len(fake.writes)
        assert enroll(req, fake)["status"] == "unchanged"
        assert len(fake.writes) == count
    writes = [call for call in fake.calls if call[0] == "PUT" and "restype=container" in call[1]]
    assert len(writes) == 1 and "if-none-match" not in writes[0][3]
    assert not any(call[0] == "arm" for call in fake.writes)


def test_container_create_requires_operator_control_plane_action(workspace):
    req = request(workspace)
    fake = Fake(req)
    container = req["account_id"] + "/blobservices/default/containers/" + req["coordinates"]["container"]
    del fake.resources[container]
    data_role = f"/subscriptions/{SUB}/providers/microsoft.authorization/roledefinitions/{en.DATA_ROLE}"
    fake.resources[data_role]["properties"]["permissions"][0]["actions"] = []
    review = en.plan(req, cloud=fake.cloud, acknowledge_exclusive_writer_governance=True)
    assert not review["can_ensure"] and "operator-container-create-permission-not-verified" in review["blockers"]
    with pytest.raises(en.EnrollmentError, match="prerequisites-blocked"):
        en.ensure(req, review["plan_hash"], yes=True, cloud=fake.cloud,
                  acknowledge_exclusive_writer_governance=True)
    assert not fake.writes
