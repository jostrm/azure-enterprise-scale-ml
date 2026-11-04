from __future__ import annotations

import argparse
import json
import locale
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4


from .config import REVIEWED_ADDITIONAL_CLIENTS


OWNER = "enterprise-scale-ai-factory-agent-browser-sign-in"
DISPLAY_NAME = "Enterprise Scale AI Factory Agent"


@dataclass(frozen=True)
class BrowserRegistration:
    tenant_id: str
    redirect_uri: str
    user_object_id: str
    pre_authorized_clients: tuple[str, ...] = ()
    expected_client_id: str | None = None

    def __post_init__(self):
        for name in ("tenant_id", "user_object_id"):
            identifier = UUID(getattr(self, name))
            if not identifier.int:
                raise ValueError("Concrete tenant and user IDs are required.")
            object.__setattr__(self, name, str(identifier))
        parsed = urlsplit(self.redirect_uri)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.path != "/"
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.port not in (None, 443) or any(char.isspace() for char in self.redirect_uri)):
            raise ValueError("Use the exact Agent HTTPS root redirect without credentials, query or fragment.")
        clients = tuple(str(UUID(client)) for client in self.pre_authorized_clients)
        if len(set(clients)) != len(clients) or any(client not in REVIEWED_ADDITIONAL_CLIENTS for client in clients):
            raise ValueError("Only distinct, reviewed public clients can be pre-authorized for the Agent API.")
        object.__setattr__(self, "pre_authorized_clients", clients)
        if self.expected_client_id is not None:
            expected = UUID(str(self.expected_client_id))
            if not expected.int:
                raise ValueError("A configured Agent registration must be a concrete client ID.")
            object.__setattr__(self, "expected_client_id", str(expected))


def registration_for(settings, redirect_uri: str, user_object_id: str) -> BrowserRegistration:
    """The backend's reviewed additional clients are the only clients pre-authorized in Entra.

    An already configured client ID binds the run to that exact application: a same-named application is
    never adopted and a missing one is never silently recreated.
    """
    return BrowserRegistration(settings.tenant_id, redirect_uri, user_object_id,
                               pre_authorized_clients=tuple(str(client) for client in settings.auth.additional_client_ids),
                               expected_client_id=settings.auth.client_id or None)


def verify_runtime_clients(config_path: Path, registration: BrowserRegistration) -> None:
    """Entra pre-authorization and the deployed runtime must accept exactly the same additional clients."""
    local = config_path.parent / "config.local.json"
    if not local.exists() or local.resolve() == config_path.resolve():
        return
    configured = (json.loads(local.read_text(encoding="utf-8")).get("auth") or {}).get("additional_client_ids") or []
    if sorted(str(UUID(str(client))) for client in configured) != sorted(registration.pre_authorized_clients):
        raise RuntimeError("config.local.json lists different auth.additional_client_ids than the registration "
                           "configuration. Align them so Entra pre-authorization and the running Agent accept the same clients.")


def registration_from_configuration(config_path: Path, settings, redirect_uri: str, user_object_id: str) -> BrowserRegistration:
    """Bind the run to the runtime identity in config.local.json before any directory call.

    Running the documented example configuration after a local registration exists must reuse that exact
    application, never create or adopt another one; tenant, client and pre-authorization mismatches stop here.
    """
    registration = registration_for(settings, redirect_uri, user_object_id)
    verify_runtime_clients(config_path, registration)
    local = config_path.parent / "config.local.json"
    if not local.exists() or local.resolve() == config_path.resolve():
        return registration
    runtime = json.loads(local.read_text(encoding="utf-8"))
    tenants = {str(UUID(str(scope.get("tenant_id")))) for scope in (runtime.get("scopes") or {}).values()}
    if tenants and tenants != {registration.tenant_id}:
        raise RuntimeError("config.local.json targets another tenant than the registration configuration; nothing was changed.")
    runtime_client = (runtime.get("auth") or {}).get("client_id")
    if not runtime_client:
        return registration
    runtime_client = str(UUID(str(runtime_client)))
    if registration.expected_client_id not in (None, runtime_client):
        raise RuntimeError("config.local.json selects another Agent registration (client ID) than the registration "
                           "configuration; nothing was changed.")
    return replace(registration, expected_client_id=runtime_client)


class DirectoryPort(Protocol):
    def request(self, method: str, path: str, body: dict | None = None) -> dict | None: ...


class AzureCliDirectory:
    def __init__(self, registration: BrowserRegistration):
        self.executable = shutil.which("az")
        if not self.executable:
            raise RuntimeError("Azure CLI is required for the approved tenant setup.")
        account = self._run(["account", "show", "--query", "{tenantId:tenantId}"])
        caller = self._run(["ad", "signed-in-user", "show", "--query", "{id:id}"])
        if account["tenantId"] != registration.tenant_id or caller["id"] != registration.user_object_id:
            raise RuntimeError("The current Azure CLI tenant/caller differs from the approved registration target.")

    def _run(self, args: list[str]):
        result = subprocess.run(
            [self.executable, *args, "--output", "json", "--only-show-errors"],
            capture_output=True, text=True, encoding=locale.getencoding(), timeout=90, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "The approved Entra directory operation failed.")
        return json.loads(result.stdout) if result.stdout.strip() else None

    def request(self, method: str, path: str, body: dict | None = None):
        if method not in ("GET", "POST", "PATCH") or not path.startswith(("/applications", "/servicePrincipals")):
            raise ValueError("Only the dedicated application/service-principal setup endpoints are supported.")
        args = ["rest", "--method", method, "--uri", "https://graph.microsoft.com/v1.0" + path]
        if body is None:
            return self._run(args)
        with TemporaryDirectory(prefix="aifactory-browser-auth-") as temporary:
            manifest = Path(temporary) / "manifest.json"
            manifest.write_text(json.dumps(body), encoding="utf-8")
            return self._run([*args, "--headers", "Content-Type=application/json", "--body", "@" + str(manifest)])


class EntraRegistrationService:
    def __init__(self, directory: DirectoryPort):
        self.directory = directory

    @staticmethod
    def plan(registration: BrowserRegistration):
        return {
            "tenant_id": registration.tenant_id, "display_name": DISPLAY_NAME,
            "redirect_uri": registration.redirect_uri, "sign_in_audience": "AzureADMyOrg",
            "protocol": "authorization_code_with_PKCE", "client_secret": False,
            "requested_permissions": ["access_as_user"],
            "assigned_user_object_id": registration.user_object_id,
            "pre_authorized_clients": [{
                "app_id": client, "display_name": REVIEWED_ADDITIONAL_CLIENTS[client],
                "delegated_permissions": ["access_as_user"],
            } for client in registration.pre_authorized_clients],
            "factory_writes": False, "azure_resource_role_changes": False,
            "existing_application_changes": bool(registration.pre_authorized_clients),
        }

    def _list(self, path: str) -> list[dict]:
        result = self.directory.request("GET", path)
        if not isinstance(result, dict) or not isinstance(result.get("value"), list) or result.get("@odata.nextLink"):
            raise RuntimeError("Directory discovery is incomplete; review before creating an identity.")
        return result["value"]

    @staticmethod
    def _identifier(value) -> str:
        result = UUID(value)
        if not result.int:
            raise RuntimeError("The directory returned an invalid identifier.")
        return str(result)

    @staticmethod
    def _manifest(registration: BrowserRegistration) -> dict:
        return {
            "displayName": DISPLAY_NAME, "signInAudience": "AzureADMyOrg",
            "tags": [OWNER], "isFallbackPublicClient": False,
            "spa": {"redirectUris": [registration.redirect_uri]},
            "web": {"redirectUris": [], "implicitGrantSettings": {
                "enableAccessTokenIssuance": False, "enableIdTokenIssuance": False,
            }},
            "publicClient": {"redirectUris": []},
            "requiredResourceAccess": [],
            "api": {
                "requestedAccessTokenVersion": 2,
                "oauth2PermissionScopes": [{
                    "id": str(uuid4()), "value": "access_as_user", "type": "User", "isEnabled": True,
                    "adminConsentDisplayName": "Access the AI Factory Agent",
                    "adminConsentDescription": "Sign in to the AI Factory Agent under the user's existing scoped access.",
                    "userConsentDisplayName": "Access the AI Factory Agent",
                    "userConsentDescription": "Sign in to the AI Factory Agent. Factory changes still require separate approval.",
                }],
            },
            "appRoles": [{
                "id": str(uuid4()), "allowedMemberTypes": ["User"], "value": "Agent.User",
                "displayName": "Agent user", "isEnabled": True,
                "description": "Sign in to this Agent; backend grants independently limit scope and operations.",
            }],
        }

    def _validate_application(self, app: dict, registration: BrowserRegistration):
        if OWNER not in app.get("tags", []):
            raise RuntimeError("A same-named application is not owned by this Agent setup; it will not be modified.")
        api, web = app.get("api") or {}, app.get("web") or {}
        scopes, roles = api.get("oauth2PermissionScopes", []), app.get("appRoles", [])
        if (
            app.get("displayName") != DISPLAY_NAME or app.get("signInAudience") != "AzureADMyOrg"
            or app.get("spa", {}).get("redirectUris") != [registration.redirect_uri]
            or app.get("passwordCredentials") or app.get("keyCredentials")
            or app.get("publicClient", {}).get("redirectUris") or web.get("redirectUris")
            or any(web.get("implicitGrantSettings", {}).values())
            or app.get("isFallbackPublicClient") is True
            or api.get("requestedAccessTokenVersion") != 2
            or api.get("knownClientApplications")
            or len(scopes) != 1 or scopes[0].get("value") != "access_as_user"
            or scopes[0].get("type") != "User" or scopes[0].get("isEnabled") is not True
            or len(roles) != 1 or roles[0].get("value") != "Agent.User"
            or roles[0].get("allowedMemberTypes") != ["User"] or roles[0].get("isEnabled") is not True
        ):
            raise RuntimeError("The owned Agent registration has configuration drift; review it before changing anything.")
        for value in (app["id"], app["appId"], scopes[0]["id"], roles[0]["id"]):
            self._identifier(value)
        current = api.get("preAuthorizedApplications") or []
        if current and current != self._pre_authorizations(registration, scopes[0]["id"]):
            raise RuntimeError("The owned Agent registration has pre-authorization drift; review it before changing anything.")
        return scopes[0]["id"], roles[0]["id"]

    @staticmethod
    def _pre_authorizations(registration: BrowserRegistration, scope_id: str) -> list[dict]:
        return [{"appId": client, "delegatedPermissionIds": [scope_id]} for client in registration.pre_authorized_clients]

    def _verify_exclusive_owner(self, app: dict, registration: BrowserRegistration):
        # Tags are mutable; directory ownership proves no other principal can later add redirects or credentials.
        owners = {self._identifier(item.get("id")) for item in self._list("/applications/" + app["id"] + "/owners")}
        if owners != {registration.user_object_id}:
            raise RuntimeError("The Agent registration must be owned exclusively by the approved operator; "
                               "review its owners before changing anything.")

    def _application(self, object_id: str) -> dict:
        app = self.directory.request("GET", "/applications/" + object_id)
        if not isinstance(app, dict) or app.get("id") != object_id:
            raise RuntimeError("The Agent registration could not be re-read; nothing further was changed.")
        return app

    def apply(self, registration: BrowserRegistration) -> dict:
        if registration.expected_client_id:
            # A configured registration is located by its immutable appId; same-named lookalikes are irrelevant.
            apps = self._list("/applications?" + urlencode({"$filter": f"appId eq '{registration.expected_client_id}'"}))
            if len(apps) != 1 or apps[0].get("appId") != registration.expected_client_id:
                raise RuntimeError("The configured Agent registration (client ID " + registration.expected_client_id
                                   + ") was not found. Refusing to create or adopt a different application.")
        else:
            apps = self._list("/applications?" + urlencode({"$filter": f"displayName eq '{DISPLAY_NAME}'"}))
            if len(apps) > 1:
                raise RuntimeError("The Agent registration name is ambiguous; no application was changed.")
        app = apps[0] if apps else self.directory.request("POST", "/applications", self._manifest(registration))
        if not isinstance(app, dict):
            raise RuntimeError("Application creation was not confirmed; inspect the directory before retrying.")
        self._identifier(app.get("id"))
        self._verify_exclusive_owner(app, registration)
        scope_id, role_id = self._validate_application(app, registration)
        client_id = app["appId"]
        expected = {
            "identifierUris": ["api://" + client_id],
            "requiredResourceAccess": [{
                "resourceAppId": client_id, "resourceAccess": [{"id": scope_id, "type": "Scope"}],
            }],
        }
        if any(app.get(key) not in (None, [], value) for key, value in expected.items()):
            raise RuntimeError("The owned Agent registration has permission/identifier drift; review required.")
        if any(app.get(key) != value for key, value in expected.items()):
            self.directory.request("PATCH", "/applications/" + app["id"], expected)
        pre_authorized = self._pre_authorizations(registration, scope_id)
        if pre_authorized and not (app.get("api") or {}).get("preAuthorizedApplications"):
            # Graph replaces the complex api property and offers no If-Match here: re-read immediately before,
            # send the reviewed scope back unchanged, then confirm the exact result.
            current = self._application(app["id"])
            if current.get("appId") != client_id or (current.get("api") or {}) != (app.get("api") or {}):
                raise RuntimeError("The Agent registration changed during review; no pre-authorization was written.")
            api = {key: value for key, value in current["api"].items() if key != "preAuthorizedApplications"}
            self.directory.request("PATCH", "/applications/" + app["id"],
                                   {"api": {**api, "preAuthorizedApplications": pre_authorized}})
            confirmed = self._application(app["id"])
            self._validate_application(confirmed, registration)
            if (confirmed.get("api") or {}).get("preAuthorizedApplications") != pre_authorized:
                raise RuntimeError("The Azure CLI pre-authorization was not confirmed; inspect the registration before retrying.")
        principals = self._list("/servicePrincipals?" + urlencode({"$filter": f"appId eq '{client_id}'"}))
        if len(principals) > 1:
            raise RuntimeError("The Agent service principal is ambiguous; review required.")
        principal = principals[0] if principals else self.directory.request("POST", "/servicePrincipals", {
            "appId": client_id, "accountEnabled": True, "appRoleAssignmentRequired": True, "tags": [OWNER],
        })
        if (not isinstance(principal, dict) or principal.get("appId") != client_id
                or OWNER not in principal.get("tags", []) or principal.get("accountEnabled") is not True
                or principal.get("appRoleAssignmentRequired") is not True):
            raise RuntimeError("The owned Agent service principal is unconfirmed or has configuration drift.")
        resource_id = self._identifier(principal["id"])
        assignment = {"principalId": registration.user_object_id, "resourceId": resource_id, "appRoleId": role_id}
        assignments = self._list("/servicePrincipals/" + resource_id + "/appRoleAssignedTo")
        if any(any(item.get(key) != value for key, value in assignment.items()) for item in assignments):
            raise RuntimeError("The dedicated Agent has unexpected user assignments; review required.")
        if not assignments:
            self.directory.request("POST", "/servicePrincipals/" + resource_id + "/appRoleAssignedTo", assignment)
        return {
            "tenant_id": registration.tenant_id, "client_id": client_id, "audience": client_id,
            "required_scope": "access_as_user", "scope_uri": "api://" + client_id + "/access_as_user",
            "scope_id": scope_id, "application_object_id": app["id"], "service_principal_id": resource_id,
            "redirect_uri": registration.redirect_uri, "assigned_user_object_id": registration.user_object_id,
            "pre_authorized_clients": list(registration.pre_authorized_clients),
        }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--redirect-uri", required=True)
    parser.add_argument("--user-object-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from .config import load_settings
    settings = load_settings(args.config)
    registration = registration_from_configuration(args.config, settings, args.redirect_uri, args.user_object_id)
    if not any(str(grant.object_id) == registration.user_object_id for grant in settings.auth.grants):
        raise ValueError("The approved user must already have an explicit Agent access grant.")
    if not args.apply:
        print(json.dumps(EntraRegistrationService.plan(registration), indent=2))
        return
    result = EntraRegistrationService(AzureCliDirectory(registration)).apply(registration)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    config["auth"].update({key: result[key] for key in ("client_id", "audience", "required_scope")})
    target = args.config.parent / "config.local.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing["auth"].get("client_id") not in (None, result["client_id"]):
            raise RuntimeError("The existing local configuration selects another identity; it was not changed.")
        config = existing
        config["auth"].update({key: result[key] for key in ("client_id", "audience", "required_scope")})
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    output = args.config.parent / ".build" / "browser-auth.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "configuration": str(target)}, indent=2))


if __name__ == "__main__":
    main()
