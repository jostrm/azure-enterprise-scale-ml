"""Defender for Cloud defaults for Key Vault, offline: Azure RBAC on every vault, an expiry on every secret and key.

Purple used to grant Key Vault access with access policies unless a factory opted into groups-v1. Every vault
now uses Azure RBAC, and every former access-policy grant is the equivalent role assignment for the same
principal, made by modules/kvRbacPrincipals.bicep. Every secret and key purple creates expires one year after the
deployment (keyVaultSecretExpiry; the rule is secretExpiresAfter in modules/common/keyVaultDefaults.json), and so
does every secret the scripts set.
"""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import pytest

from base.arm_expressions import arm_value, compile_bicep, copy_loop, resources


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
DEFAULTS = BICEP / "modules/common/keyVaultDefaults.json"
RBAC = BICEP / "modules/kvRbacPrincipals.bicep"
KEY_VAULT = BICEP / "modules/keyVault.bicep"
KEY = BICEP / "modules/keyVaultKey.bicep"
EXPIRES_AFTER = "P1Y"
# The rule, inlined in every template that creates secrets or keys: ARM allows no variables() in a parameter
# default, so the templates cannot read keyVaultDefaults.json there. These tests pin every copy to it.
EXPIRY_PARAM = "param keyVaultSecretExpiry int = dateTimeToEpoch(dateTimeAdd(utcNow(), 'P1Y'))"
EXPIRY_DEFAULT = "[dateTimeToEpoch(dateTimeAdd(utcNow(), 'P1Y'))]"
EXPIRES_EPOCH = 1831075200  # stands in for the deploy-time value

ROLES = {
    "administrator": "00482a5a-887f-4fb3-b363-3b7fe8e74483",
    "secretsOfficer": "b86a8fe4-44ce-4948-aee5-eccb2c155cd7",
    "secretsUser": "4633458b-17de-408a-b874-0445c86b69e6",
    "cryptoUser": "12338af0-0e69-4776-bea7-57ae8d297424",
    "cryptoServiceEncryptionUser": "e147488a-f6f5-4113-8e2d-b22465e65bf6",
    "certificatesOfficer": "a4417e6f-fecd-4de8-b567-7b0420556985",
}
# Owned by the session that changes the VM modules in parallel; their secrets get the expiry there.
VM_MODULES = {"modules/virtualMachinePrivate.bicep", "modules/virtualMachinePublic.bicep",
              "esml-common/modules-common/avdSessionHost.bicep"}
REMOVED_MODULES = ("kvCmnAccessPolicys.bicep", "kvAccessPolicy.bicep", "kvRbacKeyVault.bicep")

DATABRICKS = "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6"
VAULT_ID = "/subscriptions/s/resourceGroups/rg-cmn/providers/Microsoft.KeyVault/vaults/kv-cmn"
ARM = {
    "resourceId": lambda *parts: VAULT_ID,
    "subscriptionResourceId": lambda kind, name: f"/providers/{kind}/{name}",
    "tryGet": lambda item, key: item.get(key) if isinstance(item, dict) else None,
    "coalesce": lambda *items: next((item for item in items if item is not None), None),
}


def bicep_sources():
    """Purple's own Bicep: the accelerator templates (not debug copies), the MCP and the use-case infra."""
    paths = [*BICEP.rglob("*.bicep"), *(ROOT / "mcp/infra").rglob("*.bicep"),
             *(ROOT / "usecase_code").rglob("*.bicep")]
    return sorted(path for path in paths if "debug" not in path.relative_to(ROOT).parts
                  and ".build" not in path.relative_to(ROOT).parts)


def blocks(source, kind):
    """Each `resource <name> '<kind>@<version>' = ...` block that creates (not references) a resource."""
    for match in re.finditer(rf"^resource (\w+) '{re.escape(kind)}@[^']+'(?! existing)[^\n]*$", source, re.M):
        end = source.find("\n}", match.end())
        yield match[1], source[match.start():end]


def module_blocks(source, module):
    for match in re.finditer(rf"^module (\w+) '[^']*/{re.escape(module)}'[^\n]*$", source, re.M):
        end = source.find("\n}", match.end())
        yield match[1], match[0], source[match.end():end]


def param(body, name):
    found = re.search(rf"^\s+{name}:\s*(.+?)\s*(?://.*)?$", body, re.M)
    return found and found[1]


# --- the one expiry rule ----------------------------------------------------------------------------------

def test_expiry_rule_is_one_year_after_the_deployment():
    defaults = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    assert defaults["secretExpiresAfter"] == EXPIRES_AFTER
    assert f"dateTimeAdd(utcNow(), '{EXPIRES_AFTER}')" in EXPIRY_PARAM
    assert defaults["roleDefinitionIds"] == ROLES


# --- every vault uses Azure RBAC ----------------------------------------------------------------------------

def test_no_template_grants_access_policies():
    offenders = [path.relative_to(ROOT).as_posix() for path in bicep_sources()
                 if "Microsoft.KeyVault/vaults/accessPolicies" in path.read_text(encoding="utf-8")]
    assert offenders == []


def test_every_vault_purple_creates_enables_rbac():
    vaults = []
    for path in bicep_sources():
        for name, body in blocks(path.read_text(encoding="utf-8"), "Microsoft.KeyVault/vaults"):
            vaults.append(path.relative_to(BICEP).as_posix())
            assert re.search(r"^\s+enableRbacAuthorization: true\b", body, re.M), f"{path.name}: {name}"
            assert not re.search(r"^\s+accessPolicies:", body, re.M), f"{path.name}: {name}"
    assert "modules/keyVault.bicep" in vaults


def test_key_vault_module_compiles_to_rbac_without_access_policies():
    template = compile_bicep(KEY_VAULT)
    vault = next(item for item in resources(template) if item["type"] == "Microsoft.KeyVault/vaults")
    assert vault["properties"]["enableRbacAuthorization"] is True
    assert "accessPolicies" not in vault["properties"]
    assert "accessPolicies" not in template["parameters"]


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_access_policy_and_duplicate_vault_modules_are_gone(module):
    assert not (BICEP / "modules" / module).exists()
    callers = [path.name for path in bicep_sources() if f"/{module}'" in path.read_text(encoding="utf-8")]
    assert callers == []


# --- kvRbacPrincipals.bicep: the RBAC replacement for the access-policy module ------------------------------
# The principal rule (GUID filter, trim, lower-case, de-duplicate) is in test_kv_access_policy_principals.py.

def assignments(principal_id, additional_ids, role="secretsUser", principal_type=""):
    template = compile_bicep(RBAC)
    parameters = {"keyVaultResourceName": "kv-cmn", "principalId": principal_id, "keyVaultRole": role,
                  "additionalPrincipalIds": additional_ids, "principalType": principal_type}
    loop = next(item for item in resources(template) if item["type"] == "Microsoft.Authorization/roleAssignments")
    return copy_loop(loop, parameters, template, ("principalId", "roleDefinitionId", "principalType"), ARM)


def test_rbac_module_stays_classic_arm():
    # 13-rgLevel and the other classic callers keep their 'existing' semantics only with a classic module.
    assert "languageVersion" not in compile_bicep(RBAC)


@pytest.mark.parametrize("role,role_id", ROLES.items())
def test_role_name_selects_the_built_in_key_vault_role(role, role_id):
    (item,) = assignments(DATABRICKS, [], role)
    assert item["roleDefinitionId"] == f"/providers/Microsoft.Authorization/roleDefinitions/{role_id}"
    # Same seed as kvRbacSingleAssignment.bicep without a suffix: one name per vault, principal and role,
    # so two templates granting the same role to the same principal never collide (RoleAssignmentExists).
    assert item["name"] == f"guid({VAULT_ID}|{DATABRICKS}|{role_id})"


def test_principal_type_is_left_to_azure_unless_given():
    # Technical admins are users or groups; Azure resolves the type when it is omitted.
    assert assignments(DATABRICKS, [])[0]["principalType"] is None
    assert assignments(DATABRICKS, [], principal_type="ServicePrincipal")[0]["principalType"] == "ServicePrincipal"


# --- every former access-policy grant is now the equivalent role assignment --------------------------------
# Access-policy secret permissions -> role: get or get/list -> Key Vault Secrets User;
# get/list/set or all -> Key Vault Secrets Officer (no narrower built-in role exists).

GRANTS = {
    "esml-common/main/13-rgLevel.bicep": {
        ("kvNameCommon", "databricksOID", "secretsUser", "ServicePrincipal"),
        ("kvNameCommon", "externalKv.getSecret(commonServicePrincipleOIDKey)", "secretsUser", "ServicePrincipal"),
        ("kvNameCommon", "adf.outputs.principalId", "secretsUser", "ServicePrincipal"),
        ("kvNameCommon", "technicalContactId", "secretsOfficer", ""),
        ("kvNameCommonAdmin", "technicalContactId", "secretsOfficer", ""),
        ("kvNameCommonAdmin", "externalKv.getSecret(commonServicePrincipleOIDKey)", "secretsUser",
         "ServicePrincipal"),
        ("kvNameCommonAdmin", "adf.outputs.principalId", "secretsUser", "ServicePrincipal"),
    },
    "esml-genai-1/02-core-infrastructure.bicep": {
        ("kvNameCommon", "technicalContactId", "secretsUser", ""),
        ("kvNameCommon", "externalKv!.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)", "secretsUser",
         "ServicePrincipal"),
    },
    "esml-project/22-main.bicep": {
        ("kv1.outputs.keyvaultName", "technicalContactId", "secretsOfficer", ""),
        ("kv2.outputs.keyvaultName", "technicalContactId", "secretsOfficer", ""),
        ("kvNameCommon", "technicalContactId", "secretsUser", ""),
        ("kv1.outputs.keyvaultName", "externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)",
         "secretsUser", "ServicePrincipal"),
        ("kv1.outputs.keyvaultName", "adf.outputs.principalId", "secretsUser", "ServicePrincipal"),
        ("kv1.outputs.keyvaultName", "databricksOID", "secretsUser", "ServicePrincipal"),
        ("kvNameCommon", "externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName)", "secretsUser",
         "ServicePrincipal"),
        # The classic AML workspace got an implicit access policy on its vault; RBAC needs the role explicitly.
        ("kv1.outputs.keyvaultName", "aml!.outputs.principalId", "administrator", "ServicePrincipal"),
        ("kv2!.outputs.keyvaultName", "aml!.outputs.principalIdManaged", "administrator", "ServicePrincipal"),
    },
    "esml-util/25-add-user-to-bastion.bicep": {
        ("cmndevKeyvault", "users_and_serviceprincipals[0]", "secretsUser", ""),
    },
}


def grants(relative):
    found = set()
    for name, _, body in module_blocks((BICEP / relative).read_text(encoding="utf-8"), "kvRbacPrincipals.bicep"):
        role = param(body, "keyVaultRole").strip("'")
        principal_type = (param(body, "principalType") or "''").strip("'")
        vault = param(body, "keyVaultResourceName")
        found.add((vault, param(body, "principalId"), role, principal_type))
        assert param(body, "additionalPrincipalIds") is not None, name
    return found


@pytest.mark.parametrize("relative", GRANTS)
def test_former_access_policy_grants_are_role_assignments(relative):
    expected = GRANTS[relative]
    actual = grants(relative)
    # 02-core's common vault grant names the vault by either spelling, kvNameCommon or commonKv.name.
    actual = {(("kvNameCommon" if vault == "commonKv.name" else vault), *rest) for vault, *rest in actual}
    assert actual == expected


def test_human_grants_still_follow_the_persona_mode():
    # groups-v1 grants people through the persona bridge; only the legacy mode grants the admin lists here.
    common = (BICEP / "esml-common/main/13-rgLevel.bicep").read_text(encoding="utf-8")
    for _, header, _ in module_blocks(common, "kvRbacPrincipals.bicep"):
        assert "!personaGroupsEnabled" in header, header
    core = (BICEP / "esml-genai-1/02-core-infrastructure.bicep").read_text(encoding="utf-8")
    for _, header, _ in module_blocks(core, "kvRbacPrincipals.bicep"):
        assert "groups-v1" in header, header


def test_postgres_cmk_identity_gets_the_crypto_role_instead_of_an_access_policy():
    source = (BICEP / "modules/databases/postgreSQL/pgFlexibleServer.bicep").read_text(encoding="utf-8")
    (_, body), = [item for item in blocks(source, "Microsoft.Authorization/roleAssignments")]
    assert "if (useCMK)" in body.splitlines()[0]
    assert "cryptoServiceEncryptionUser" in body
    assert "cmkIdentity!.properties.principalId" in body


# --- every secret and key purple creates expires one year after the deployment -----------------------------

# Entry templates that call secret or key modules pass their own keyVaultSecretExpiry down, so one deployment
# parameter sets the expiry everywhere; each module keeps the same default for its other callers.
SECRET_MODULES = ("keyVault", "kvSecretsPrj", "kvSecretsCmn", "keyVaultKey", "csAIServices", "csDocIntelligence",
                  "csOpenAI", "csSpeech", "csVision", "cosmosdb", "redis", "sqldatabase", "postgresqlDeployment",
                  "pgFlexibleServer", "eventhub", "logAnalyticsWorkspace", "machineLearningAIHub")
ENTRY_TEMPLATES = ("esml-common/main/13-rgLevel.bicep", "esml-genai-1/02-core-infrastructure.bicep",
                   "esml-genai-1/03-cognitive-services.bicep", "esml-genai-1/04-databases.bicep",
                   "esml-genai-1/04b-postgresql.bicep", "esml-genai-1/06-ai-platform.bicep",
                   "esml-project/22-main.bicep", "modules/services/postgresqlDeployment.bicep")


def secret_modules():
    found = {}
    for path in bicep_sources():
        relative = path.relative_to(BICEP).as_posix() if BICEP in path.parents else path.as_posix()
        source = path.read_text(encoding="utf-8")
        names = [name for kind in ("Microsoft.KeyVault/vaults/secrets", "Microsoft.KeyVault/vaults/keys")
                 for name, _ in blocks(source, kind)]
        if names and relative not in VM_MODULES:
            found[relative] = (path, names)
    return found


def test_secret_inventory_is_complete():
    assert {"modules/keyVault.bicep", "modules/kvSecretsPrj.bicep", "esml-common/modules-common/kvSecretsCmn.bicep",
            "modules/keyVaultExport.bicep", "modules/keyVaultKey.bicep", "modules/databases/sqldatabase/sqldatabase.bicep",
            "modules/machineLearningAIHub.bicep"} <= secret_modules().keys()


@pytest.mark.parametrize("relative", sorted(secret_modules()))
def test_every_secret_and_key_expires_one_year_after_the_deployment(relative):
    path, names = secret_modules()[relative]
    source = path.read_text(encoding="utf-8")
    assert EXPIRY_PARAM in source
    for kind in ("Microsoft.KeyVault/vaults/secrets", "Microsoft.KeyVault/vaults/keys"):
        for name, body in blocks(source, kind):
            assert re.search(r"\bexp: keyVaultSecretExpiry\b", body), f"{relative}: {name}"
    template = compile_bicep(path)
    assert template["parameters"]["keyVaultSecretExpiry"]["defaultValue"] == EXPIRY_DEFAULT


@pytest.mark.parametrize("relative", ENTRY_TEMPLATES)
def test_entry_templates_pass_one_expiry_to_every_secret_module(relative):
    source = (BICEP / relative).read_text(encoding="utf-8")
    assert EXPIRY_PARAM in source
    calls = [(name, body) for module in SECRET_MODULES
             for name, _, body in module_blocks(source, f"{module}.bicep")]
    assert calls, relative
    for name, body in calls:
        assert re.search(r"^\s+keyVaultSecretExpiry: keyVaultSecretExpiry$", body, re.M), f"{relative}: {name}"


def test_key_vault_module_secrets_expire_even_when_the_caller_passes_attributes():
    template = compile_bicep(KEY_VAULT)
    loop = next(item for item in resources(template) if item["type"] == "Microsoft.KeyVault/vaults/secrets")
    for secret in ({"name": "a", "value": "v"}, {"name": "b", "value": "v", "attributes": {"enabled": False}}):
        parameters = {"secrets": [secret], "keyvaultName": "kv", "keyVaultSecretExpiry": EXPIRES_EPOCH}
        merge = {"union": lambda *objects: {key: value for item in objects for key, value in item.items()}}
        (item,) = copy_loop(loop, parameters, template, ("attributes",), {**ARM, **merge, "copyIndex": lambda *_: 0})
        assert item["attributes"]["exp"] == EXPIRES_EPOCH
        assert item["attributes"]["enabled"] is (secret.get("attributes", {}).get("enabled", True))


def test_keys_expire_with_the_deployment_expiry():
    template = compile_bicep(KEY)
    key = next(item for item in resources(template) if item["type"] == "Microsoft.KeyVault/vaults/keys")
    assert arm_value(key["properties"]["attributes"]["exp"], {"keyVaultSecretExpiry": EXPIRES_EPOCH},
                     template, ARM) == EXPIRES_EPOCH
    # An ARM PUT returns an existing key unchanged, so Key Vault itself renews it: a new version 30 days
    # before expiry, valid for the same one year. A customer-managed key never lapses.
    assert key["properties"]["rotationPolicy"] == {
        "attributes": {"expiryTime": EXPIRES_AFTER},
        "lifetimeActions": [{"action": {"type": "rotate"}, "trigger": {"timeBeforeExpiry": "P30D"}}]}


# --- scripts that set secrets pass the same rule: one year from now (UTC) ----------------------------------

SCRIPTS = ("environment_setup/aifactory/bicep/esml-util/29-create-sp-or-update-oid-for-project.sh",
           "environment_setup/aifactory/bicep/esml-util/29b-create-mcp-api-sp-for-projects.sh",
           "environment_setup/aifactory/bicep/esml-util/32-create-azure-groups.sh",
           "bootstrap/lib/create-new-aifactory-scaleset.sh")
SCRIPT_EXPIRY = ("AIF_KV_SECRET_EXPIRES=\"${AIF_KV_SECRET_EXPIRES:-$(date -u -d '+1 year' '+%Y-%m-%dT%H:%M:%SZ' "
                 "2>/dev/null || date -u -v+1y '+%Y-%m-%dT%H:%M:%SZ')}\"")


def secret_set_commands(text):
    """Each uncommented `keyvault secret set` command with its continuation lines or argument array."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "keyvault secret set" in line and not line.lstrip().startswith("#"):
            end = index
            in_array = index > 0 and lines[index - 1].rstrip().endswith("=(")
            while end + 1 < len(lines) and (lines[end].rstrip().endswith("\\")
                                             or in_array and lines[end].strip() != ")"):
                end += 1
            yield "\n".join(lines[index:end + 1])


def test_every_script_that_sets_secrets_is_listed():
    found = set()
    for path in [*ROOT.glob("bootstrap/**/*.sh"), *BICEP.rglob("*.sh"), *BICEP.rglob("*.ps1")]:
        relative = path.relative_to(ROOT).as_posix()
        if "debug" not in path.relative_to(ROOT).parts and any(secret_set_commands(path.read_text("utf-8"))):
            found.add(relative)
    assert found == set(SCRIPTS)


@pytest.mark.parametrize("relative", SCRIPTS)
def test_scripts_set_secrets_one_year_ahead(relative):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert SCRIPT_EXPIRY in text
    commands = list(secret_set_commands(text))
    assert commands
    for command in commands:
        assert re.search(r'--expires "\$AIF_KV_SECRET_EXPIRES"', command), command


def test_script_expiry_is_one_year_ahead_in_utc(tmp_path):
    import run_ci
    import subprocess
    result = subprocess.run([run_ci.find_bash(), "--noprofile", "--norc", "-c",
                             f"unset AIF_KV_SECRET_EXPIRES; {SCRIPT_EXPIRY}; echo \"$AIF_KV_SECRET_EXPIRES\""],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    expires = datetime.strptime(result.stdout.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    assert 364 <= (expires - now).days <= 366


def rollout_one_year_from_now():
    source = (ROOT / "mcp/deploy/rollout.py").read_text(encoding="utf-8")
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "one_year_from_now")
    namespace = {"datetime": datetime, "timezone": timezone}
    exec(compile(ast.Module([function], []), "rollout.py", "exec"), namespace)
    return source, namespace["one_year_from_now"]


def test_mcp_rollout_api_key_secret_expires_one_year_after_creation():
    source, one_year_from_now = rollout_one_year_from_now()
    call = source[source.index("vault.set_secret("):]
    assert "expires_on=one_year_from_now()" in call[:call.index("})")]
    assert one_year_from_now(datetime(2026, 10, 23, tzinfo=timezone.utc)) == datetime(2027, 10, 23, tzinfo=timezone.utc)
    assert one_year_from_now(datetime(2028, 2, 29, tzinfo=timezone.utc)) == datetime(2029, 2, 28, tzinfo=timezone.utc)
