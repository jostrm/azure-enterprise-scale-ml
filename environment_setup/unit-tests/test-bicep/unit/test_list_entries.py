"""Comma-separated lists (IPwhiteList, technical_admins_email, postGresAdminEmails) reach every consumer trimmed.

split() keeps the spaces around each entry and an empty entry for a trailing or doubled comma, and the
replace(x, '\\s+', '') several templates used is a literal replace in Bicep, not a regex. So "1.2.3.4, 5.6.7.8"
became ' 5.6.7.8/32' in Key Vault, ACR and storage IP rules, and a spaced email a PostgreSQL admin named
' b@contoso.com'. The one rule in modules/common/listEntries.bicep trims each entry and drops empty ones. It keeps
case and order: IP ranges have no case to fold, and an email seeds its PostgreSQL administrator's name
(guid(server, role, email)), so lower-casing would rename admins existing servers were deployed with. Each template
keeps its own guards ('null', length < 5) and de-duplication, so already-clean input evaluates to the values it
did before. Classic-ARM templates inline the rule, because importing a function would switch them to
languageVersion 2.0; the last tests pin every copy.
"""
from pathlib import Path
import re

import pytest

from base.arm_expressions import arm_value, compile_bicep


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
LIST_ENTRIES = BICEP / "modules/common/listEntries.bicep"

IP_A, IP_B = "1.2.3.4", "5.6.7.0/24"
IPS = f"{IP_A},{IP_B}"
IP_VARIANTS = [f"{IP_A}, {IP_B}", f" {IP_A} , {IP_B} ", f"{IP_A},{IP_B},", f"{IP_A},,{IP_B}",
               f"\t{IP_A}\t,\n{IP_B}\n"]
MAIL_A, MAIL_B = "Ann.Admin@contoso.com", "bo@contoso.com"
MAILS = f"{MAIL_A},{MAIL_B}"
MAIL_VARIANTS = [f"{MAIL_A}, {MAIL_B}", f" {MAIL_A} ,{MAIL_B} ", f"{MAIL_A},{MAIL_B},", f"{MAIL_A},,{MAIL_B}"]


def variable(relative, name, parameters):
    template = compile_bicep(BICEP / relative)
    return arm_value(f"[variables('{name}')]", parameters, template)


# --- the one rule -------------------------------------------------------------------------------------------

def trimmed(raw):
    return arm_value("[__bicep.trimmedEntries(split(parameters('csv'), ','))]", {"csv": raw},
                     compile_bicep(LIST_ENTRIES))


@pytest.mark.parametrize("raw", [IPS, *IP_VARIANTS])
def test_trimmed_entries_trims_each_entry_and_drops_empty_ones(raw):
    assert trimmed(raw) == [IP_A, IP_B]


@pytest.mark.parametrize("raw", ["", " ", ",", " , "])
def test_trimmed_entries_of_a_blank_list_is_empty(raw):
    assert trimmed(raw) == []


def test_trimmed_entries_keeps_case_order_and_duplicates():
    # De-duplication stays with each template (some union, some do not), so the rule does not change it.
    assert trimmed(f" {MAIL_A}, FD00::1/128 ,{IP_A}, {MAIL_A}") == [MAIL_A, "FD00::1/128", IP_A, MAIL_A]


# --- IPwhiteList: every template that turns it into IP rules ------------------------------------------------

IP_LISTS = {
    "esml-common/main/12-networkCommon.bicep": "ipWhitelist_array",   # Bastion NSG allow rules
    "esml-common/main/13-rgLevel.bicep": "ipWhitelist_array",         # common ACR and Key Vault
    "esml-genai-1/02-core-infrastructure.bicep": "ipWhitelist_array",
    "esml-genai-1/03-cognitive-services.bicep": "ipWhitelist_array",
    "esml-genai-1/04-databases.bicep": "ipWhitelist_array",
    "esml-genai-1/05-compute-services.bicep": "ipWhitelist_array",
    "esml-genai-1/06-ai-platform.bicep": "ipWhitelist_array",
    "esml-genai-1/07-ml-data-platform.bicep": "ipWhitelist_array",
    "esml-genai-1/09-ai-foundry-2025-v3.bicep": "filteredIpWhitelist_array",
    "esml-genai-1/09-ai-foundry-2025-v4.bicep": "filteredIpWhitelist_array",
    "esml-genai-1/11-integration.bicep": "ipWhitelist_array",         # Event Hubs network rule set
    "modules/services/aiSearchDeployment.bicep": "ipWhitelist_array",
    "modules/services/containerAppsDeployment.bicep": "ipWhitelist_array",
}


@pytest.mark.parametrize("relative,name", IP_LISTS.items())
def test_ip_whitelist_clean_input_is_unchanged(relative, name):
    assert variable(relative, name, {"IPwhiteList": IPS}) == [IP_A, IP_B]


@pytest.mark.parametrize("raw", IP_VARIANTS)
@pytest.mark.parametrize("relative,name", IP_LISTS.items())
def test_ip_whitelist_entries_are_trimmed_without_empty_ones(relative, name, raw):
    assert variable(relative, name, {"IPwhiteList": raw}) == [IP_A, IP_B]


@pytest.mark.parametrize("relative,name", IP_LISTS.items())
def test_ip_whitelist_empty_means_no_rules(relative, name):
    assert variable(relative, name, {"IPwhiteList": ""}) == []


@pytest.mark.parametrize("relative", ["esml-common/main/12-networkCommon.bicep", "esml-common/main/13-rgLevel.bicep"])
def test_ip_whitelist_null_means_no_rules(relative):
    assert variable(relative, "ipWhitelist_array", {"IPwhiteList": "null"}) == []


@pytest.mark.parametrize("raw", [IPS, f"{IP_A}, {IP_B}"])
def test_common_acr_ip_rules_get_the_trimmed_ranges(raw):
    # Used to be ' 5.6.7.0/24' for "1.2.3.4, 5.6.7.0/24".
    assert variable("esml-common/main/13-rgLevel.bicep", "processedIpRules", {"IPwhiteList": raw}) == [
        {"action": "Allow", "value": f"{IP_A}/32"}, {"action": "Allow", "value": IP_B}]


@pytest.mark.parametrize("raw", [IPS, f"{IP_A}, {IP_B}"])
def test_container_apps_ip_restrictions_get_the_trimmed_ranges(raw):
    # The rule name is derived from the range, so a space used to end up in the name as well.
    assert variable("modules/services/containerAppsDeployment.bicep", "ipSecurityRestrictions",
                    {"IPwhiteList": raw}) == [
        {"name": IP_A, "ipAddressRange": IP_A, "action": "Allow"},
        {"name": "5.6.7.0_24", "ipAddressRange": IP_B, "action": "Allow"}]


# --- technical_admins_email and postGresAdminEmails -----------------------------------------------------------

EMAIL_LISTS = {
    "esml-common/main/11-rgCommon.bicep": "technicalAdminsEmail_array_safe",   # contributor descriptions
    "esml-common/main/13-rgLevel.bicep": "technicalAdminsEmail_array_safe",
}
NAMING = "modules/common/CmnAIfactoryNaming.bicep"


@pytest.mark.parametrize("raw", [MAILS, *MAIL_VARIANTS])
@pytest.mark.parametrize("relative,name", EMAIL_LISTS.items())
def test_admin_emails_are_trimmed_and_keep_their_case(relative, name, raw):
    assert variable(relative, name, {"technicalAdminsEmail": raw, "tags": {}}) == [MAIL_A, MAIL_B]


@pytest.mark.parametrize("raw", [MAILS, *MAIL_VARIANTS])
@pytest.mark.parametrize("output", ["postGresAdminEmails", "p011_genai_team_lead_email_array"])
def test_naming_email_outputs_are_trimmed_and_keep_their_case(output, raw):
    template = compile_bicep(BICEP / NAMING)
    value = template["outputs"][output]["value"]
    assert arm_value(value, {"postGresAdminEmails": raw, "technicalAdminsEmail": raw}, template) == [MAIL_A, MAIL_B]


@pytest.mark.parametrize("output", ["postGresAdminEmails", "p011_genai_team_lead_email_array"])
def test_naming_email_outputs_are_empty_without_emails(output):
    template = compile_bicep(BICEP / NAMING)
    value = template["outputs"][output]["value"]
    assert arm_value(value, {"postGresAdminEmails": "", "technicalAdminsEmail": ""}, template) == []


def test_postgres_admin_emails_stay_de_duplicated():
    template = compile_bicep(BICEP / NAMING)
    value = template["outputs"]["postGresAdminEmails"]["value"]
    assert arm_value(value, {"postGresAdminEmails": f"{MAIL_A}, {MAIL_A}", "technicalAdminsEmail": ""},
                     template) == [MAIL_A]


# --- one rule: imported by languageVersion 2.0 templates, inlined verbatim by classic ones --------------------

IP = "split(IPwhiteList, ',')"
EMAIL = "split(technicalAdminsEmail, ',')"
INLINED = {
    "esml-common/main/11-rgCommon.bicep": [EMAIL],
    "esml-common/main/12-networkCommon.bicep": [IP],
    "esml-common/main/13-rgLevel.bicep": [IP, EMAIL],
    "esml-project/22-main.bicep": [IP, EMAIL],
    **{relative: [IP] for relative in IP_LISTS if relative.startswith("esml-genai-1/0")},
    "modules/services/aiSearchDeployment.bicep": [IP],
    "modules/services/containerAppsDeployment.bicep": [IP],
}
IMPORTED = {
    NAMING: ["split(postGresAdminEmails, ',')", EMAIL],
    "esml-genai-1/11-integration.bicep": [IP],
}
# esml-project/22-main does not compile on its own today (modules/machineLearning.bicep outboundType), so it is
# pinned by text only.
CLASSIC = [relative for relative in INLINED if relative != "esml-project/22-main.bicep"]


def rule_body():
    match = re.search(r"^func trimmedEntries\(entries array\) array => (.+)$",
                      LIST_ENTRIES.read_text(encoding="utf-8"), re.MULTILINE)
    assert match and match[1].startswith("filter(map(entries, "), "listEntries.bicep lost its rule"
    return match[1].strip()


def inlined(source):
    return rule_body().replace("map(entries, ", f"map({source}, ", 1)


@pytest.mark.parametrize("relative,sources", INLINED.items())
def test_classic_templates_inline_the_exact_rule(relative, sources):
    text = (BICEP / relative).read_text(encoding="utf-8")
    for source in sources:
        assert inlined(source) in text, source


@pytest.mark.parametrize("relative,sources", IMPORTED.items())
def test_language_version_2_templates_import_the_rule(relative, sources):
    text = (BICEP / relative).read_text(encoding="utf-8")
    for source in sources:
        assert f"trimmedEntries({source})" in text, source


@pytest.mark.parametrize("relative", CLASSIC)
def test_classic_templates_stay_classic_arm(relative):
    # Importing a user-defined function compiles to languageVersion 2.0, which deploys 'existing' resources
    # differently and changes the template shape other tests read.
    assert "languageVersion" not in compile_bicep(BICEP / relative)


LISTS = r"\b(?:IPwhiteList|technicalAdminsEmail|postGresAdminEmails)\b"


def deployment_templates():
    # esml-util holds manual scripts that compile only from a consumer copy (their module paths start
    # with ../../azure-enterprise-scale-ml), so they are not deployment consumers.
    for path in sorted(BICEP.rglob("*.bicep")):
        relative = path.relative_to(BICEP).as_posix()
        if not relative.startswith("esml-util/"):
            yield relative, path.read_text(encoding="utf-8")


def code_lines(source):
    return [line for line in source.splitlines() if not line.lstrip().startswith("//")]


def test_no_template_uses_the_literal_whitespace_replace():
    users = [relative for relative, source in deployment_templates()
             if any("'\\\\s+'" in line for line in code_lines(source))]
    assert users == []


def test_comma_lists_are_parsed_only_through_the_rule():
    parsers, importers = {}, set()
    for relative, source in deployment_templates():
        lines = [line for line in code_lines(source) if re.search(rf"split\(\s*{LISTS}", line)]
        if lines:
            parsers[relative] = lines
        if re.search(r"^import \{[^}]*\btrimmedEntries\b[^}]*\} from '(?:[^']*/)?listEntries\.bicep'",
                     source, re.MULTILINE):
            importers.add(relative)
    assert set(parsers) == set(INLINED) | set(IMPORTED)
    for relative, lines in parsers.items():
        expected = [f"trimmedEntries({source})" for source in IMPORTED.get(relative, [])] or \
                   [inlined(source) for source in INLINED[relative]]
        assert all(any(rule in line for rule in expected) for line in lines), relative
    assert importers == set(IMPORTED)
