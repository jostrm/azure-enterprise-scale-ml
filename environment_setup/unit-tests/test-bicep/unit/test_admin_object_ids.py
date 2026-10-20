"""technical_admins_ad_object_id reaches every consumer trimmed, lower-cased, de-duplicated and non-empty.

The preflight gate (scripts/kv_principal_object_ids.py) accepts "a , B"; the Bicep that consumes the same
value normalizes it with the one rule in modules/common/objectIds.bicep. Role-assignment names are seeded
with the object ID, so spacing or case must not change them (RoleAssignmentExists 409 on redeploy), and
already-normalized input must keep the names existing factories were deployed with. Classic-ARM templates
inline the rule, because importing a function would switch them to languageVersion 2.0; the last tests pin
every copy to objectIds.bicep.
"""
from pathlib import Path
import re

import pytest

from base.arm_expressions import (arm_value, compile_bicep, copy_loop, nested_parameters,
                                  parameters_with_defaults, resources)


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
OBJECT_IDS = BICEP / "modules/common/objectIds.bicep"
RG_COMMON = BICEP / "esml-common/main/11-rgCommon.bicep"
RG_LEVEL = BICEP / "esml-common/main/13-rgLevel.bicep"
NAMING = BICEP / "modules/common/CmnAIfactoryNaming.bicep"
CONTRIBUTOR = BICEP / "modules/contributorRbac.bicep"
KEY_VAULT = BICEP / "modules/kvCmnAccessPolicys.bicep"

A = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
B = "24ad8636-1b2c-4d5e-8f90-a1b2c3d4e5f6"
NORMALIZED = f"{A},{B}"
VARIANTS = [f" {A} , {B} ", f"{A.upper()},{B}", f"{A}, {B.upper()}\n", f"{A},,{B},",
            f"{A},{B},{A.upper()}", f"\t{A}\t,{B}"]
NONE = ["", "null", "NULL", " null ", ",", " , "]
GROUPS = {"AIF-Persona-Access": "groups-v1"}

RG_ID = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-cmn"
RG = {"resourceGroup": lambda: {"id": RG_ID, "name": "rg-cmn"}}
CONTRIBUTOR_NAMES = [f"guid({A}-contributor-{RG_ID})", f"guid({B}-contributor-{RG_ID})"]


def deployment(template, name_part):
    return next(item for item in resources(template)
                if item["type"] == "Microsoft.Resources/deployments" and name_part in item["name"])


def common_rg_admin_ids(template, admin_ids, tags=None, module="ContributorPermissionsOnRGCmn"):
    parameters = parameters_with_defaults(template, {"technicalAdminsObjectID": admin_ids, "tags": tags or {}})
    return nested_parameters(deployment(template, module), parameters, template)["additionalUserIds"]


def common_rg_contributors(admin_ids, admin_emails="null", tags=None):
    """The contributorRbac role assignments 11-rgCommon deploys on the common resource group."""
    template = compile_bicep(RG_COMMON)
    parameters = parameters_with_defaults(template, {"technicalAdminsObjectID": admin_ids,
                                                     "technicalAdminsEmail": admin_emails, "tags": tags or {}})
    module = deployment(template, "ContributorPermissionsOnRGCmn")
    nested = module["properties"]["template"]
    values = nested_parameters(module, parameters, template)
    loop = next(item for item in resources(nested) if item["copy"]["name"] == "contributorRole2userOrGroup")
    return copy_loop(loop, values, nested, ("principalId", "description"), RG)


def contributor_module(admin_ids, admin_emails):
    template = compile_bicep(CONTRIBUTOR)
    parameters = parameters_with_defaults(template, {"userEmail": "", "additionalUserIds": admin_ids,
                                                     "additionalUserEmails": admin_emails})
    loop = next(item for item in resources(template) if item["copy"]["name"] == "contributorRole2userOrGroup")
    return copy_loop(loop, parameters, template, ("principalId", "description"), RG)


# --- the one normalization ---------------------------------------------------------------------------------

def normalized(raw):
    return arm_value("[__bicep.normalizedObjectIds(split(parameters('csv'), ','))]", {"csv": raw},
                     compile_bicep(OBJECT_IDS))


@pytest.mark.parametrize("raw", [NORMALIZED, *VARIANTS])
def test_normalized_object_ids_trims_lowers_and_removes_duplicates_in_order(raw):
    assert normalized(raw) == [A, B]


@pytest.mark.parametrize("raw", NONE)
def test_normalized_object_ids_treats_empty_and_null_as_none(raw):
    assert normalized(raw) == []


# --- 11-rgCommon: Contributor and VM admin login on the common resource group --------------------------------

def test_common_rg_role_assignment_names_stay_the_same_for_normalized_input():
    # The seed '<oid>-contributor-<rg id>' is what existing factories were deployed with.
    assignments = common_rg_contributors(NORMALIZED, "a@contoso.com,b@contoso.com")
    assert [item["name"] for item in assignments] == CONTRIBUTOR_NAMES
    assert [item["principalId"] for item in assignments] == [A, B]
    assert [item["description"] for item in assignments] == [
        "Contributor to user a@contoso.com to get Contributor on resource group: rg-cmn",
        "Contributor to user b@contoso.com to get Contributor on resource group: rg-cmn"]


@pytest.mark.parametrize("raw", VARIANTS)
def test_common_rg_spacing_or_case_does_not_change_role_assignment_names(raw):
    assignments = common_rg_contributors(raw)
    assert [item["name"] for item in assignments] == CONTRIBUTOR_NAMES
    assert [item["principalId"] for item in assignments] == [A, B]


@pytest.mark.parametrize("raw", NONE)
def test_common_rg_empty_or_null_admins_get_no_role_assignment(raw):
    assert common_rg_contributors(raw) == []


def test_common_rg_persona_groups_skip_admin_role_assignments():
    assert common_rg_contributors(NORMALIZED, tags=GROUPS) == []


@pytest.mark.parametrize("emails", ["a@contoso.com", "null", ""])
def test_common_rg_more_admin_ids_than_emails_deploys(emails):
    # Used to fail 11-rgCommon with an index-out-of-bounds error on additionalUserEmails[i].
    assignments = common_rg_contributors(NORMALIZED, emails)
    assert [item["name"] for item in assignments] == CONTRIBUTOR_NAMES
    assert assignments[1]["description"] == f"Contributor to user {B} to get Contributor on resource group: rg-cmn"


@pytest.mark.parametrize("raw", VARIANTS)
def test_common_rg_vm_admin_login_gets_the_same_normalized_ids(raw):
    template = compile_bicep(RG_COMMON)
    assert common_rg_admin_ids(template, raw, module="VMAdminLoginPermissions") == [A, B]


# --- contributorRbac.bicep on its own (11-rgCommon and esml-project/22-main) --------------------------------

def test_contributor_rbac_falls_back_to_the_object_id_when_an_email_is_missing():
    assignments = contributor_module([A, B], ["a@contoso.com"])
    assert [item["name"] for item in assignments] == CONTRIBUTOR_NAMES
    assert [item["description"] for item in assignments] == [
        "Contributor to user a@contoso.com to get Contributor on resource group: rg-cmn",
        f"Contributor to user {B} to get Contributor on resource group: rg-cmn"]


# --- 13-rgLevel: common Key Vault access policies for admins -------------------------------------------------

def rg_level_admin_policies(raw, tags=None):
    """additionalPrincipalIds of the cmn and admin Key Vault policies that 13-rgLevel grants the technical contact."""
    template = compile_bicep(RG_LEVEL)
    modules = [item for item in resources(template) if item["type"] == "Microsoft.Resources/deployments"
               and item["properties"]["parameters"].get("principalId") == {"value": "[parameters('technicalContactId')]"}]
    assert len(modules) == 2
    return [arm_value(item["properties"]["parameters"]["additionalPrincipalIds"]["value"],
                      {"technicalAdminsObjectID": raw, "tags": tags or {}}, template) for item in modules]


@pytest.mark.parametrize("raw", [NORMALIZED, *VARIANTS])
def test_rg_level_key_vault_admins_are_normalized(raw):
    assert rg_level_admin_policies(raw) == [[A, B], [A, B]]


@pytest.mark.parametrize("raw,tags", [(raw, {}) for raw in NONE] + [(NORMALIZED, GROUPS)])
def test_rg_level_without_admins_passes_none(raw, tags):
    assert rg_level_admin_policies(raw, tags) == [[], []]


# --- CmnAIfactoryNaming: p011_genai_team_lead_array feeds every genai RBAC module ---------------------------

@pytest.mark.parametrize("raw,expected", [(NORMALIZED, [A, B]), *[(raw, [A, B]) for raw in VARIANTS],
                                          *[(raw, []) for raw in NONE]])
def test_naming_team_lead_array_is_normalized(raw, expected):
    template = compile_bicep(NAMING)
    output = template["outputs"]["p011_genai_team_lead_array"]["value"]
    assert arm_value(output, {"technicalAdminsObjectID": raw}, template) == expected


# --- one rule: imported by languageVersion 2.0 templates, inlined verbatim by classic ones --------------------

CSV = "split(technicalAdminsObjectID, ',')"
INLINED = {"esml-common/main/11-rgCommon.bicep": CSV, "esml-common/main/13-rgLevel.bicep": CSV,
           "esml-project/22-main.bicep": CSV,
           "modules/kvCmnAccessPolicys.bicep": "union(main_principal_2_array, additionalPrincipalIds)"}
IMPORTED = {"modules/common/CmnAIfactoryNaming.bicep": f"normalizedObjectIds({CSV})"}


def rule_body():
    match = re.search(r"^func normalizedObjectIds\(ids array\) array => (.+)$",
                      OBJECT_IDS.read_text(encoding="utf-8"), re.MULTILINE)
    assert match and match[1].startswith("union(filter(map(ids, "), "objectIds.bicep lost its rule"
    return match[1].strip()


def inlined(source_ids):
    return rule_body().replace("map(ids, ", f"map({source_ids}, ", 1)


@pytest.mark.parametrize("relative,source_ids", INLINED.items())
def test_classic_templates_inline_the_exact_rule(relative, source_ids):
    assert inlined(source_ids) in (BICEP / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [RG_COMMON, RG_LEVEL, KEY_VAULT, CONTRIBUTOR])
def test_classic_templates_stay_classic_arm(path):
    # Importing a user-defined function compiles to languageVersion 2.0, which deploys 'existing' resources
    # (some in 13-rgLevel have full resource IDs as names) and changes the template shape other tests read.
    assert "languageVersion" not in compile_bicep(path)


def test_admin_object_ids_are_parsed_only_through_the_rule():
    # esml-util holds manual scripts that compile only from a consumer copy (their module paths start
    # with ../../azure-enterprise-scale-ml), so they are not deployment consumers.
    parsers, importers = {}, set()
    for path in sorted(BICEP.rglob("*.bicep")):
        relative = path.relative_to(BICEP).as_posix()
        if relative.startswith("esml-util/"):
            continue
        source = path.read_text(encoding="utf-8")
        lines = [line for line in source.splitlines() if re.search(r"split\([^)]*\btechnicalAdminsObjectID\b", line)]
        if lines:
            parsers[relative] = lines
        if re.search(r"^import \{[^}]*\bnormalizedObjectIds\b[^}]*\} from '(?:[^']*/)?objectIds\.bicep'",
                     source, re.MULTILINE):
            importers.add(relative)
    assert set(parsers) == {path for path, ids in INLINED.items() if ids == CSV} | set(IMPORTED)
    for relative, lines in parsers.items():
        expected = IMPORTED.get(relative) or inlined(CSV)
        assert all(expected in line for line in lines), relative
    assert importers == set(IMPORTED)
