"""Explicit, journaled pilot rollout stages. Plan is the default; no automatic write retry."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from release import canonical, digest, verify_release


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from aifactory_mcp.registration import ApplicationRole, RegistrationTarget, build_registration_plan

TARGET = {
    "subscription": "f0fe8b33-73bf-41e4-9997-e3920d793c06",
    "tenant": "c157e61b-4a1e-488c-9a0c-d9a23e864a65",
    "resourceGroupName": "spider-esml-project001-sdc-dev-001-rg",
    "location": "swedencentral",
    "environmentName": "aif-mcp-project001-dev-env",
    "appName": "aifactory-mcp-project001-dev",
    "identityName": "mi-aifactory-mcp-dev",
    "registryName": "acrcommonbltscsdc001dev",
    "registryResourceGroupName": "spider-esml-common-sdc-dev-001",
    "keyVaultName": "kv-p001-sdc-dev-bltsc01",
    "apiKeySecretName": "aifactory-mcp-api-key-dev",
    "scopeKey": "project001-dev",
    "foundryAccount": "aif2bltscaae001dev",
    "foundryProject": "aif2-p001bltdev",
    "projectPrincipal": "78fcb1e6-30cf-477e-ba9a-4d935b547252",
    "projectClient": "2de2956f-6c3b-410c-95bd-8a9403f9686f",
    "operator": "4e6f97b5-7140-40eb-b030-c31d73072197",
    "connection": "aifactory-governed-mcp",
}
SESSION = "903d4df9-68db-49f1-84ab-91d97d7bab1f"
OWNER = "aifactory-mcp"
ENTRA_NAME = "AI Factory Governed MCP - Spider project001 dev"
ENTRA_TAGS = [OWNER, "session:" + SESSION]
ARM = "https://management.azure.com"
GRAPH = "https://graph.microsoft.com/v1.0"
GROUP_ID = f"/subscriptions/{TARGET['subscription']}/resourceGroups/{TARGET['resourceGroupName']}"
APP_ID = GROUP_ID + "/providers/Microsoft.App/containerApps/" + TARGET["appName"]
PROJECT_ID = (GROUP_ID + "/providers/Microsoft.CognitiveServices/accounts/" + TARGET["foundryAccount"]
              + "/projects/" + TARGET["foundryProject"])
STAGES = ("identity", "secret", "foundation", "publish", "application", "connection")


def seal(value: dict) -> dict:
    return {**value, "plan_hash": digest(canonical(value))}


def require_approval(plan: dict, approved_hash: str | None) -> None:
    unsigned = {key: value for key, value in plan.items() if key != "plan_hash"}
    if plan.get("plan_hash") != digest(canonical(unsigned)):
        raise ValueError("The rollout plan hash is invalid.")
    if plan.get("target") != TARGET:
        raise ValueError("The rollout target differs from the approved pilot.")
    if not approved_hash or approved_hash != plan["plan_hash"]:
        raise ValueError("The exact reviewed plan hash is required as explicit approval.")


def validate_image(image: str, repository: str) -> str:
    pattern = re.escape(TARGET["registryName"] + ".azurecr.io/" + repository) + r"@sha256:[a-f0-9]{64}"
    if not isinstance(image, str) or not re.fullmatch(pattern, image):
        raise ValueError("Use an exact digest in the approved private registry repository.")
    return image


def run(command: list[str], *, timeout=300) -> str:
    executable = shutil.which(command[0])
    if not executable:
        raise RuntimeError("The required executable is unavailable.")
    resolved = [executable, *command[1:]]
    if Path(executable).suffix.lower() in {".cmd", ".bat"}:
        # Azure CLI on Windows is a batch shim. Invoke its own Python directly
        # so neither PATH extension lookup nor shell metacharacter parsing is needed.
        python = Path(executable).parent.parent / "python.exe"
        if command[0] != "az" or Path(executable).name.lower() != "az.cmd" or not python.is_file():
            raise RuntimeError("An unsupported batch launcher cannot be executed safely.")
        resolved = [str(python), "-I", "-m", "azure.cli", *command[1:]]
    result = subprocess.run(resolved, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"The {command[0]} command failed with exit code {result.returncode}; no retry was attempted.")
    return result.stdout.strip()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + str(uuid4()) + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Journal:
    def __init__(self, path: Path, plan_hash: str):
        self.path, self.plan_hash = path, plan_hash
        self.data = self._read()

    def _read(self):
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "plan_hash": self.plan_hash, "stages": {}, "results": {},
        }
        if data.get("plan_hash") != self.plan_hash:
            raise ValueError("The journal belongs to a different plan.")
        return data

    def _update(self, stage: str, status: str, result=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError("A journal update is in progress; inspect before retrying.") from None
        try:
            self.data = self._read()
            previous = self.data["stages"].get(stage)
            if status == "started" and previous is not None:
                raise ValueError("This stage was already claimed; inspect its resources and journal, do not replay.")
            if status == "completed" and previous != "started":
                raise ValueError("Only a claimed stage may be completed.")
            self.data["stages"][stage] = status
            if result is not None:
                self.data["results"][stage] = result
            atomic_json(self.path, self.data)
        finally:
            os.close(fd)
            lock.unlink()

    def claim(self, stage):
        self._update(stage, "started")

    def complete(self, stage, result):
        self._update(stage, "completed", result)


class Cloud(Protocol):
    def request(self, method: str, url: str, body: dict | None = None, *, headers=None) -> dict: ...

    def create_api_secret(self) -> dict: ...


class AzureCloud:
    def __init__(self):
        from azure.identity import AzureCliCredential
        self.credential = AzureCliCredential(tenant_id=TARGET["tenant"])

    def request(self, method: str, url: str, body=None, *, headers=None) -> dict:
        import httpx
        if url.startswith(ARM + "/"):
            audience = ARM + "/.default"
        elif url.startswith(GRAPH + "/"):
            audience = "https://graph.microsoft.com/.default"
        else:
            raise ValueError("Unsupported deployment API endpoint.")
        token = self.credential.get_token(audience).token
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = client.request(method, url, json=body,
                                      headers={**(headers or {}), "Authorization": "Bearer " + token})
        if response.status_code == 404 and method == "GET":
            return {}
        if response.status_code >= 300:
            raise RuntimeError(f"Deployment API returned HTTP {response.status_code}; inspect before retrying.")
        return response.json() if response.content else {}

    def create_api_secret(self) -> dict:
        from azure.core.exceptions import ResourceNotFoundError
        from azure.keyvault.secrets import SecretClient
        with SecretClient(vault_url=f"https://{TARGET['keyVaultName']}.vault.azure.net",
                          credential=self.credential) as vault:
            try:
                current = vault.get_secret(TARGET["apiKeySecretName"])
            except ResourceNotFoundError:
                current = None
            if current is not None:
                raise ValueError("The dedicated API-key secret already exists; inspect rather than overwrite.")
            created = vault.set_secret(TARGET["apiKeySecretName"], secrets.token_hex(32),
                                       tags={"managed-by": OWNER, "session": SESSION})
            return {"secret_id": created.id}


def _owned(resource: dict) -> None:
    tags = resource.get("tags") or {}
    if (not isinstance(tags, dict) or tags.get("aifactory.managed_by") != OWNER
            or tags.get("app-onboard-session-id") != SESSION):
        raise ValueError("Existing Azure resource ownership does not match this rollout.")


def _collection(data: dict) -> list[dict]:
    if data.get("@odata.nextLink") or data.get("nextLink") or not isinstance(data.get("value"), list):
        raise ValueError("A complete bounded resource collection is required.")
    return data["value"]


def pilot_config(base: dict) -> dict:
    config = copy.deepcopy(base)
    config["factory"].update(writes_enabled=False, factory_id=None, scale_set_id=None, project_id=None,
                             operation_signing_secret_url=None, api_key_secret_url=None)
    config["actions"] = {"enabled_skills": []}
    config["costs"] = config["workloads"] = {}
    config["auth"].update(
        client_id="6d2e5357-f4c1-4ea0-b9c9-62c6699c0bb8",
        audience="6d2e5357-f4c1-4ea0-b9c9-62c6699c0bb8",
        grants=[{"object_id": caller, "scopes": [TARGET["scopeKey"]], "permissions": ["factory.read"]}
                for caller in (TARGET["operator"], TARGET["projectPrincipal"])],
    )
    return config


def parameters(config_json: str, auth_json: str, url: str, *, application: bool, images=None) -> dict:
    keys = ("resourceGroupName", "location", "environmentName", "appName", "identityName",
            "registryName", "registryResourceGroupName", "keyVaultName", "apiKeySecretName", "scopeKey")
    values = {key: TARGET[key] for key in keys}
    values.update(
        resourceUrl=url, deployApplication=application, sessionId=SESSION,
        deployedBy="Joakim Ostrom", createdAt="2026-10-04T20:49:51.017Z",
        agentConfigJson=config_json, applicationAuthJson=auth_json,
    )
    if images:
        values.update(mcpImage=images["mcp"], apiImage=images["api"])
    return {key: {"value": value} for key, value in values.items()}


def source_hashes() -> dict:
    return {
        path.relative_to(ROOT).as_posix(): digest(path.read_bytes())
        for folder in (ROOT / "infra", ROOT / "deploy")
        for path in sorted(folder.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {
            ".py", ".ps1", ".bicep", ".json", ".txt",
        }
    }


def create_plan(release: Path, mcp_image: str, api_image: str, base_config: Path) -> dict:
    manifest = verify_release(release)
    image_ids = {}
    for name, image in (("mcp", mcp_image), ("api", api_image)):
        image_id = run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise ValueError("A locally validated immutable image ID is required.")
        label = run(["docker", "image", "inspect", image_id, "--format",
                     '{{index .Config.Labels "aifactory.release"}}'])
        if label != manifest["release_hash"]:
            raise ValueError("The local image is not bound to the selected release.")
        image_ids[name] = image_id
    config = pilot_config(json.loads(base_config.read_text(encoding="utf-8")))
    expected_scope = {
        "tenant_id": TARGET["tenant"], "subscription_id": TARGET["subscription"],
        "resource_group": TARGET["resourceGroupName"], "factory": "spider", "project": "001", "environment": "dev",
    }
    if config.get("scopes") != {TARGET["scopeKey"]: expected_scope}:
        raise ValueError("The base configuration does not match the exact approved pilot scope.")
    return seal({
        "schema_version": 1, "target": TARGET, "release": str(release.resolve()),
        "release_hash": manifest["release_hash"], "local_image_ids": image_ids,
        "source_hashes": source_hashes(), "pilot_config": config,
        "stages": list(STAGES),
        "effects": [
            "Create one dedicated Entra API app/SP and read-role assignment for the exact Foundry project identity.",
            "Create one dedicated Key Vault secret; preserve all existing secrets.",
            "Create scoped hosting identity and pull/secret-read assignments in existing resource groups.",
            "Push only the reviewed local images to the approved registry repositories.",
            "Deploy one new two-container app in the existing internal environment.",
            "Create a distinct MCP connection; do not modify existing agents, connections or tools.",
        ],
    })


def preflight(cloud: Cloud) -> str:
    operator = cloud.request("GET", GRAPH + "/me?$select=id")
    if operator.get("id") != TARGET["operator"]:
        raise ValueError("Sign in as the reviewed deployment operator.")
    project = cloud.request("GET", ARM + PROJECT_ID + "?api-version=2025-06-01")
    if (project.get("identity", {}).get("principalId") != TARGET["projectPrincipal"]
            or project.get("identity", {}).get("tenantId") != TARGET["tenant"]):
        raise ValueError("The Foundry project identity changed.")
    environment = cloud.request("GET", ARM + GROUP_ID + "/providers/Microsoft.App/managedEnvironments/"
                                + TARGET["environmentName"] + "?api-version=2026-07-01")
    properties = environment.get("properties") or {}
    if properties.get("vnetConfiguration", {}).get("internal") is not True:
        raise ValueError("The approved environment is not internal.")
    vault = cloud.request("GET", ARM + GROUP_ID + "/providers/Microsoft.KeyVault/vaults/"
                          + TARGET["keyVaultName"] + "?api-version=2026-05-15")
    if (vault.get("properties", {}).get("enableRbacAuthorization") is not True
            or vault.get("properties", {}).get("publicNetworkAccess") != "Disabled"):
        raise ValueError("The approved Key Vault must remain private and RBAC-enabled.")
    registry = cloud.request("GET", ARM + f"/subscriptions/{TARGET['subscription']}/resourceGroups/"
                             + TARGET["registryResourceGroupName"] + "/providers/Microsoft.ContainerRegistry/registries/"
                             + TARGET["registryName"] + "?api-version=2025-11-01")
    if (registry.get("properties", {}).get("publicNetworkAccess") != "Disabled"
            or registry.get("properties", {}).get("adminUserEnabled") is not False):
        raise ValueError("The approved registry must remain private with admin credentials disabled.")
    domain = properties.get("defaultDomain", "")
    if not re.fullmatch(r"[a-z0-9-]+\.swedencentral\.azurecontainerapps\.io", domain):
        raise ValueError("The existing environment has an unexpected DNS domain.")
    for name, kind in ((TARGET["appName"], "Microsoft.App/containerApps"),
                       (TARGET["identityName"], "Microsoft.ManagedIdentity/userAssignedIdentities")):
        api = "2026-07-01" if "containerApps" in kind else "2024-11-30"
        existing = cloud.request("GET", f"{ARM}{GROUP_ID}/providers/{kind}/{name}?api-version={api}")
        if existing:
            _owned(existing)
    return f"https://{TARGET['appName']}.{domain}/mcp"


def registration(application_id: str, url: str) -> dict:
    role_id = uuid5(NAMESPACE_URL, PROJECT_ID + "/aifactory-governed-mcp/read")
    return build_registration_plan(RegistrationTarget(
        subscription_id=TARGET["subscription"], tenant_id=TARGET["tenant"],
        resource_group=TARGET["resourceGroupName"], foundry_account=TARGET["foundryAccount"],
        foundry_project=TARGET["foundryProject"], project_principal_id=TARGET["projectPrincipal"],
        project_client_id=TARGET["projectClient"], mcp_application_id=application_id,
        mcp_url=url, service_name=TARGET["appName"],
    ), scope_key=TARGET["scopeKey"], existing_application_role=ApplicationRole(role_id))


def verify_identity(identity: dict, cloud: Cloud) -> None:
    app = cloud.request("GET", GRAPH + "/applications/" + identity["application_object_id"])
    role_id = str(uuid5(NAMESPACE_URL, PROJECT_ID + "/aifactory-governed-mcp/read"))
    if (app.get("appId") != identity["application_id"] or app.get("displayName") != ENTRA_NAME
            or not set(ENTRA_TAGS) <= set(app.get("tags") or [])
            or app.get("api", {}).get("requestedAccessTokenVersion") != 2
            or app.get("passwordCredentials") or app.get("keyCredentials")):
        raise ValueError("The dedicated Entra application no longer matches the reviewed identity.")
    roles = app.get("appRoles") or []
    if len(roles) != 1 or any(roles[0].get(key) != value for key, value in {
        "id": role_id, "value": "AiFactory.Mcp.Read", "allowedMemberTypes": ["Application"], "isEnabled": True,
    }.items()):
        raise ValueError("The dedicated Entra application role changed.")
    if not any(claim.get("name") == "idtyp" for claim in app.get("optionalClaims", {}).get("accessToken", [])):
        raise ValueError("The application identity-type claim is not configured.")
    sp = cloud.request("GET", GRAPH + "/servicePrincipals/" + identity["service_principal_id"])
    if (sp.get("appId") != identity["application_id"] or sp.get("appRoleAssignmentRequired") is not True
            or not set(ENTRA_TAGS) <= set(sp.get("tags") or [])):
        raise ValueError("The dedicated service principal changed.")


def published_images(plan: dict, images: dict) -> dict:
    for name, repository in (("mcp", "aifactory-mcp"), ("api", "aifactory-api")):
        validate_image(images[name], repository)
        references = json.loads(run(["docker", "image", "inspect", plan["local_image_ids"][name],
                                     "--format", "{{json .RepoDigests}}"]))
        if images[name] not in (references or []):
            raise ValueError("The published digest is not bound to the reviewed local image.")
    return images


def execute_stage(phase: str, plan: dict, journal: Journal, cloud: Cloud, url: str) -> dict:
    if phase == "identity":
        existing = _collection(cloud.request(
            "GET", GRAPH + "/applications?$filter=displayName eq '" + ENTRA_NAME + "'&$top=2",
        ))
        if existing:
            raise ValueError("An Entra app with the rollout name already exists; inspect rather than overwrite.")
        role = ApplicationRole(uuid5(NAMESPACE_URL, PROJECT_ID + "/aifactory-governed-mcp/read")).to_dict()
        app = cloud.request("POST", GRAPH + "/applications", {
            "displayName": ENTRA_NAME, "signInAudience": "AzureADMyOrg", "tags": ENTRA_TAGS,
            "api": {"requestedAccessTokenVersion": 2}, "appRoles": [role],
            "optionalClaims": {"accessToken": [{"name": "idtyp", "essential": True}]},
        })
        sp = cloud.request("POST", GRAPH + "/servicePrincipals", {
            "appId": app["appId"], "tags": ENTRA_TAGS, "appRoleAssignmentRequired": True,
        })
        assigned = cloud.request("POST", GRAPH + f"/servicePrincipals/{TARGET['projectPrincipal']}/appRoleAssignments", {
            "principalId": TARGET["projectPrincipal"], "resourceId": sp["id"], "appRoleId": role["id"],
        })
        return {"application_id": app["appId"], "application_object_id": app["id"],
                "service_principal_id": sp["id"], "role_assignment_id": assigned["id"]}
    if phase == "secret":
        return cloud.create_api_secret()
    if phase in {"foundation", "application"}:
        identity = journal.data["results"]["identity"]
        prepared = registration(identity["application_id"], url)
        values = parameters(json.dumps(plan["pilot_config"]), json.dumps(prepared["application_auth"]), url,
                            application=phase == "application",
                            images=published_images(plan, journal.data["results"]["publish"])
                            if phase == "application" else None)
        path = journal.path.with_name("deployment.parameters.json")
        atomic_json(path, {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                           "contentVersion": "1.0.0.0", "parameters": values})
        result = json.loads(run([
            "az", "deployment", "sub", "create", "--subscription", TARGET["subscription"],
            "--location", TARGET["location"], "--name", "aifactory-mcp-" + phase + "-" + plan["plan_hash"][:8],
            "--template-file", str(ROOT / "infra" / "main.bicep"), "--parameters", "@" + str(path),
            "--query", "properties.{state:provisioningState,outputs:outputs}", "-o", "json",
        ], timeout=1800))
        if result.get("state") != "Succeeded":
            raise RuntimeError("Infrastructure deployment has not confirmed success.")
        return result
    if phase == "publish":
        run(["az", "acr", "login", "--name", TARGET["registryName"], "--subscription", TARGET["subscription"]])
        images = {}
        for key, repository in (("mcp", "aifactory-mcp"), ("api", "aifactory-api")):
            image_id = plan["local_image_ids"][key]
            actual = run(["docker", "image", "inspect", image_id, "--format", "{{.Id}}"])
            if actual != image_id:
                raise ValueError("A reviewed local image is unavailable or changed.")
            tagged = TARGET["registryName"] + ".azurecr.io/" + repository + ":" + plan["release_hash"][:16]
            run(["docker", "tag", image_id, tagged])
            run(["docker", "push", tagged], timeout=1800)
            references = json.loads(run(["docker", "image", "inspect", tagged, "--format", "{{json .RepoDigests}}"]))
            matches = [item for item in references if item.startswith(TARGET["registryName"] + ".azurecr.io/" + repository + "@")]
            if len(matches) != 1:
                raise RuntimeError("The pushed image digest is absent or ambiguous.")
            images[key] = validate_image(matches[0], repository)
        return images
    if phase == "connection":
        import httpx
        app = cloud.request("GET", ARM + APP_ID + "?api-version=2026-07-01")
        _owned(app)
        properties = app.get("properties", {})
        if (properties.get("provisioningState") != "Succeeded"
                or "https://" + properties.get("configuration", {}).get("ingress", {}).get("fqdn", "") + "/mcp" != url):
            raise ValueError("The actual deployed MCP endpoint does not match the reviewed private endpoint.")
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            if client.get(url.removesuffix("/mcp") + "/health/ready").status_code != 200:
                raise RuntimeError("The new MCP/API service is not ready.")
            if client.post(url, json={}).status_code != 401:
                raise RuntimeError("The new MCP service did not enforce authentication.")
        prepared = registration(journal.data["results"]["identity"]["application_id"], url)
        request = prepared["connection_request"]
        if cloud.request("GET", request["url"]):
            raise ValueError("The named Foundry connection already exists; do not replace it.")
        cloud.request("PUT", request["url"], request["body"], headers=request["headers"])
        actual = cloud.request("GET", request["url"])
        properties = actual.get("properties", {})
        if any(properties.get(key) != request["body"]["properties"][key]
               for key in ("target", "authType", "audience", "category")):
            raise RuntimeError("The new connection could not be confirmed.")
        return {"connection_id": request["resource_id"], "agent_tool_for_separate_review": prepared["agent_tool"],
                "agent_modified": False}
    raise ValueError("Unsupported rollout stage.")


def rollback(plan: dict, journal: Journal, cloud: Cloud, approval: str | None) -> dict:
    preview = seal({"target": TARGET, "deployment_plan_hash": plan["plan_hash"],
                    "effects": ["Disable only the new MCP service principal", "Request stop of only the new MCP Container App"],
                    "delete_resources": False})
    if not approval:
        return preview
    if approval != preview["plan_hash"]:
        raise ValueError("The exact rollback approval hash is required.")
    identity = journal.data["results"].get("identity")
    if not identity:
        raise ValueError("The created MCP identity has not been recorded; inspect before rollback.")
    sp_url = GRAPH + "/servicePrincipals/" + identity["service_principal_id"]
    sp = cloud.request("GET", sp_url)
    if sp.get("appId") != identity["application_id"] or not set(ENTRA_TAGS) <= set(sp.get("tags") or []):
        raise ValueError("The new service principal ownership could not be confirmed.")
    app = cloud.request("GET", ARM + APP_ID + "?api-version=2026-07-01")
    if app:
        _owned(app)
    journal.claim("rollback")
    cloud.request("PATCH", sp_url, {"accountEnabled": False})
    if cloud.request("GET", sp_url).get("accountEnabled") is not False:
        raise RuntimeError("Identity disablement could not be confirmed.")
    if app:
        cloud.request("POST", ARM + APP_ID + "/stop?api-version=2026-07-01")
    result = {"identity_disabled": True, "app_stop_requested": bool(app), "resources_deleted": False}
    journal.complete("rollback", result)
    return result


def parser():
    result = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--phase", choices=("plan", "preflight", *STAGES, "rollback"), default="plan")
    result.add_argument("--plan", type=Path)
    result.add_argument("--release", type=Path)
    result.add_argument("--base-config", type=Path)
    result.add_argument("--mcp-image")
    result.add_argument("--api-image")
    result.add_argument("--approval-hash")
    result.add_argument("--rollback-approval-hash")
    return result


def main():
    options = parser().parse_args()
    if options.phase == "plan":
        if not all((options.release, options.base_config, options.mcp_image, options.api_image)):
            raise ValueError("Planning requires a sealed release, base configuration and both validated local images.")
        plan = create_plan(options.release, options.mcp_image, options.api_image, options.base_config)
        if options.plan:
            if options.plan.exists():
                raise ValueError("Select a new plan path; existing plans are not overwritten.")
            atomic_json(options.plan, plan)
        print(json.dumps(plan, indent=2))
        return
    if options.plan is None:
        raise ValueError("An explicit reviewed plan file is required.")
    plan = json.loads(options.plan.read_text(encoding="utf-8"))
    require_approval(plan, plan.get("plan_hash") if options.phase in {"preflight", "rollback"} else options.approval_hash)
    journal = Journal(options.plan.with_suffix(".journal.json"), plan["plan_hash"])
    # Emergency containment depends on the sealed plan, journal and live ownership,
    # not on build artifacts that may have been cleaned up or patched.
    if options.phase == "rollback":
        if not options.rollback_approval_hash:
            print(json.dumps(rollback(plan, journal, None, None), indent=2))
            return
        cloud = AzureCloud()
        try:
            print(json.dumps(rollback(plan, journal, cloud, options.rollback_approval_hash), indent=2))
        finally:
            cloud.credential.close()
        return
    if source_hashes() != plan["source_hashes"] or verify_release(Path(plan["release"]))["release_hash"] != plan["release_hash"]:
        raise ValueError("Deployment source or release changed; prepare and review a new plan.")
    cloud = AzureCloud()
    try:
        url = preflight(cloud)
        if options.phase == "preflight":
            output = {"status": "preflight_passed", "resource_url": url, "cloud_mutations": False}
        else:
            index = STAGES.index(options.phase)
            if any(journal.data["stages"].get(stage) != "completed" for stage in STAGES[:index]):
                raise ValueError("Complete and confirm all preceding stages before this one.")
            if options.phase != "identity":
                verify_identity(journal.data["results"]["identity"], cloud)
            journal.claim(options.phase)
            output = execute_stage(options.phase, plan, journal, cloud, url)
            journal.complete(options.phase, output)
        print(json.dumps(output, indent=2))
    finally:
        cloud.credential.close()


if __name__ == "__main__":
    from azure.core.exceptions import AzureError
    from httpx import HTTPError

    try:
        main()
    except (ValueError, RuntimeError, OSError, AzureError, HTTPError, subprocess.TimeoutExpired):
        print("Rollout stopped. Inspect the saved plan, journal and scoped resources; do not blindly retry.", file=sys.stderr)
        raise SystemExit(1)
