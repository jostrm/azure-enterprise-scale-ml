"""Offline contract tests for the "Deploy to Azure" portal package. No Azure calls, no deployments."""

import importlib.util
import ipaddress
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
PORTAL = ROOT / "portal"
MAX_TEMPLATE_BYTES = 4 * 1024 * 1024
MAX_PARAMETERS = 256
SPEC = importlib.util.spec_from_file_location("generate_portal", PORTAL / "generate_portal.py")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)
CONFIG = GENERATOR.load_config(ROOT)


@pytest.fixture(scope="module")
def plan():
    return GENERATOR.build_plan(ROOT)


@pytest.fixture(scope="module")
def committed():
    return json.loads((PORTAL / "generated/stage-parameters.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def main_template():
    return json.loads((PORTAL / "azuredeploy.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def form():
    return json.loads((PORTAL / "form.json").read_text(encoding="utf-8"))


def linked_deployments(template):
    found = []

    def visit(resources):
        for resource in resources.values() if isinstance(resources, dict) else resources:
            if resource.get("type", "").lower() == "microsoft.resources/deployments":
                link = resource.get("properties", {}).get("templateLink")
                if link:
                    found.append(resource)
    visit(template["resources"])
    return found


def form_outputs(form):
    return form["view"]["outputs"]["parameters"]


def form_elements(form):
    elements = []

    def walk(items):
        for item in items:
            elements.append(item)
            walk(item.get("elements", []))
    for step in form["view"]["properties"]["steps"]:
        walk(step.get("elements", []))
    return elements


def test_generated_outputs_have_no_drift(plan):
    """Regeneration from the Simple Mode preset, variables.json and the workflows is byte-identical."""
    for relative, content in GENERATOR.render_outputs(ROOT, plan).items():
        assert (PORTAL / relative).read_text(encoding="utf-8") == content, f"{relative} drifted; run portal/generate_portal.py"


def test_stage_parameters_equal_the_simple_mode_preset(committed):
    """Every preset key that a workflow passes to a stage keeps its Simple Mode value."""
    preset = CONFIG.simple_mode_values()
    checked = 0
    for stage in committed["stages"].values():
        for parameter, env_name in stage["sources"].items():
            if env_name in preset and parameter in stage["constants"]:
                expected = GENERATOR.typed(preset[env_name], stage["types"][parameter])
                assert stage["constants"][parameter] == expected, (stage["template"], parameter)
                checked += 1
    assert checked > 100


def test_disabled_simple_mode_features_stay_disabled(committed):
    disabled = set(CONFIG.SIMPLE_MODE_DISABLED)
    for stage in committed["stages"].values():
        for parameter, env_name in stage["sources"].items():
            if env_name in disabled and parameter in stage["constants"]:
                assert stage["constants"][parameter] in (False, "false"), (stage["template"], parameter)


def test_private_networking_is_never_weakened(committed):
    for stage in committed["stages"].values():
        constants = stage["constants"]
        for parameter in ("enablePublicGenAIAccess", "allowPublicAccessWhenBehindVnet",
                          "enablePublicAccessWithPerimeter", "centralDnsZoneByPolicyInHub"):
            if parameter in constants:
                assert constants[parameter] in (False, "false"), (stage["template"], parameter)
        if "disableLocalAuth" in constants:
            assert constants["disableLocalAuth"] in (True, "true")


def test_stages_follow_the_simple_mode_pipeline_order(committed):
    order = [stage["template"] for stage in committed["stages"].values()]
    assert order.index("stages/11-rgCommon.json") < order.index("stages/12-networkCommon.json") < order.index("stages/13-rgLevel.json")
    assert order.index("stages/13-rgLevel.json") < order.index("stages/31-network.json") < order.index("stages/01-foundation.json")
    foundry = [key for key, stage in committed["stages"].items() if stage["template"] == "stages/09-ai-foundry-2025-v4.json"]
    assert len(foundry) == 2, "Foundry v4 is deployed twice (account, then account update)"
    assert order.index("stages/08b-rbac-common-rg.json") < list(committed["stages"]).index(foundry[0])


def test_every_required_stage_parameter_is_supplied(committed):
    for key, stage in committed["stages"].items():
        template = json.loads((PORTAL / stage["template"]).read_text(encoding="utf-8"))
        declared = template["parameters"]
        supplied = set(stage["constants"]) | set(stage["templated"]) | set(stage["templatedJson"]) | set(stage["wired"])
        assert not supplied - set(declared), (key, sorted(supplied - set(declared)))
        required = {name for name, spec in declared.items() if "defaultValue" not in spec}
        assert not required - supplied, (key, sorted(required - supplied))
        buckets = [set(stage["constants"]), set(stage["templated"]), set(stage["templatedJson"]), set(stage["wired"])]
        assert sum(len(bucket) for bucket in buckets) == len(supplied), f"{key}: a parameter is supplied twice"


def test_constants_never_contain_unfilled_tokens_or_arm_expressions(committed):
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    tokens = set(committed["tokens"])
    for stage in committed["stages"].values():
        for text in strings(stage["constants"]):
            assert "__P_" not in text
            assert not text.startswith("["), "a literal would be evaluated as an ARM expression"
        for text in list(stage["templated"].values()) + list(stage["templatedJson"].values()):
            assert set(re.findall(r"__P_(\w+?)__", text)) <= tokens


@pytest.mark.parametrize("name", sorted(p.name for p in (PORTAL / "stages").glob("*.json")))
def test_every_stage_template_fits_arm_limits(name):
    path = PORTAL / "stages" / name
    assert path.stat().st_size < MAX_TEMPLATE_BYTES
    assert len(json.loads(path.read_text(encoding="utf-8"))["parameters"]) < MAX_PARAMETERS


def test_main_template_fits_arm_limits(main_template):
    assert (PORTAL / "azuredeploy.json").stat().st_size < MAX_TEMPLATE_BYTES
    assert len(main_template["parameters"]) <= MAX_PARAMETERS
    assert "subscriptionDeploymentTemplate" in main_template["$schema"]


def test_every_linked_template_exists_and_is_published(main_template, committed):
    paths = {resource["properties"]["templateLink"]["relativePath"] for resource in linked_deployments(main_template)}
    assert paths, "main must use linked templates, not inline modules"
    for relative in paths:
        assert (PORTAL / relative).is_file(), relative
    assert {stage["template"] for stage in committed["stages"].values()} == paths
    published = {f"stages/{path.name}" for path in (PORTAL / "stages").glob("*.json")}
    assert published == paths, f"unlinked or missing stage templates: {sorted(published ^ paths)}"


def test_wired_stage_parameters_are_set_by_main(main_template, committed):
    by_path = {}
    for resource in linked_deployments(main_template):
        by_path.setdefault(resource["properties"]["templateLink"]["relativePath"], []).append(
            json.dumps(resource["properties"].get("parameters", "")))
    variables = main_template.get("variables", {})
    for key, stage in committed["stages"].items():
        bodies = " ".join(by_path[stage["template"]])
        for name in set(re.findall(r"variables\(\\?'(\w+)\\?'\)", bodies)) & set(variables):
            bodies += " " + json.dumps(variables[name])
        for parameter in stage["wired"]:
            assert f"'{parameter}'" in bodies or f'"{parameter}"' in bodies, (key, parameter)


def test_vnet_writes_in_the_hub_are_serialized(main_template):
    # Azure rejects a resolver, Bastion or endpoint on a VNet that is still "Updating" after a subnet write
    # (observed on portal-125: bastion-<prefix>-<loc>-dev-001 failed "not found ... or is not in a Succeeded state").
    stage = json.loads((PORTAL / "stages/portal-hub-access.json").read_text(encoding="utf-8"))
    by_type = {resource["type"]: resource for resource in stage["resources"]}

    def depends(kind):
        return " ".join(by_type[kind].get("dependsOn", []))
    assert "virtualNetworks/subnets" in depends("Microsoft.Network/dnsResolvers")
    assert "dnsResolvers/inboundEndpoints" in depends("Microsoft.Network/bastionHosts")
    resources = main_template["resources"]
    assert "hubAccess" in resources["seedingEndpoint"]["dependsOn"]


def test_redeploy_can_skip_the_common_vnet_put(form, main_template):
    # 12-networkCommon PUTs the whole common VNet with its four subnets. On a redeploy that PUT tries to delete the
    # resolver, gateway and project subnets added later (observed: InUseSubnetCannotBeDeleted on
    # snet-dns-private-resolver). ARM cannot test existence, so the form mirrors the CLI's RUN_JOB1_NETWORKING=false.
    assert main_template["parameters"]["commonVnetExists"] == {"type": "bool", "defaultValue": False,
                                                               "metadata": main_template["parameters"]["commonVnetExists"]["metadata"]}
    assert main_template["resources"]["commonNetwork"]["condition"] == "[not(parameters('commonVnetExists'))]"
    toggle = next(element for element in form_elements(form) if element["name"] == "commonVnetExists")
    assert toggle["defaultValue"] == "No"
    assert form_outputs(form)["commonVnetExists"] == "[equals(steps('basics').commonVnetExists, 'true')]"


def test_every_stage_uses_the_common_subnet_the_network_stage_creates(committed):
    # The project job applies variables.json (subnetCommon "snet-dev-esml-cmn-001") while the common job, dispatched
    # without the JSON override, creates and uses common_subnet_name. Observed: CannotChangeSubnetOnExistingPrivateEndpoint
    # on the common ACR endpoint in 02-core-infrastructure.
    stages = committed["stages"]
    created = stages["common-12-networkCommon"]["constants"]["common_subnet_name"]
    checked = 0
    for key, stage in stages.items():
        values = {**stage["constants"], **stage["templated"]}
        if "common_subnet_name" not in values or key == "common-12-networkCommon":
            continue
        override = values.get("subnetCommon", "")
        resolved = override.replace("<network_env>", values.get("network_env", "")) if override else values["common_subnet_name"]
        assert resolved == created, (key, resolved)
        assert not values.get("subnetCommonScoring") and not values.get("subnetCommonPowerbiGw"), key
        checked += 1
    assert checked >= 4


def test_main_does_not_inline_stage_templates(main_template):
    for resource in linked_deployments(main_template):
        assert "template" not in resource["properties"]


def test_form_outputs_map_one_to_one_to_main_parameters(form, main_template):
    # The CustomDeploymentBlade uiFormDefinitionUri renders a Form view, not a createUiDefinition.
    assert form["$schema"].endswith("2021-09-09/uiFormDefinition.schema.json#")
    assert form["view"]["kind"] == "Form"
    context = form["view"]["outputs"]
    assert context["kind"] == "Subscription"
    # Subscription scope: the portal reads scope and location from a ResourceScope element (as in Microsoft's AVD
    # landing zone accelerator form); subscriptionId is the subscription's resource ID.
    assert form["view"]["properties"]["steps"][0]["elements"][0]["type"] == "Microsoft.Common.ResourceScope"
    assert context["subscriptionId"] == "[steps('basics').resourceScope.subscription.id]"
    assert context["location"] == "[steps('basics').resourceScope.location.name]"
    outputs = form_outputs(form)
    assert set(outputs) == set(main_template["parameters"])
    names = {element["name"] for element in form_elements(form)}
    for value in outputs.values():
        referenced = re.findall(r"steps\('\w+'\)\.(\w+)", value)
        assert set(referenced) <= names, value


def test_disabled_flags_never_appear_in_the_form(form):
    text = json.dumps(form)
    for flag in CONFIG.SIMPLE_MODE_DISABLED:
        assert f'"{flag}"' not in text and f".{flag}" not in text, flag
    assert "enableEventHubs" not in text


def test_costly_hub_options_are_optional_and_off_by_default(form, main_template):
    parameters = main_template["parameters"]
    assert parameters["enableVpnGateway"]["defaultValue"] is False
    assert parameters["enableApplicationGateway"]["defaultValue"] is False
    defaults = {}
    for element in form_elements(form):
        choices = {item["label"]: item["value"] for item in element.get("constraints", {}).get("allowedValues", [])}
        defaults[element["name"]] = choices.get(element.get("defaultValue"), element.get("defaultValue"))
    assert defaults["enableVpnGateway"] == "false"
    assert defaults["enableApplicationGateway"] == "false"
    assert defaults["enableBastion"] == "true" and parameters["enableBastion"]["defaultValue"] is True
    for name in ("enableVpnGateway", "enableApplicationGateway", "enableBastion", "enablePrivateDnsPolicy",
                 "enableApplicationInsights"):
        assert form_outputs(form)[name].startswith("[equals(steps(") and form_outputs(form)[name].endswith(", 'true')]")


def test_form_collects_no_secrets_and_writes_nothing_to_entra(form, main_template):
    types = {element["type"] for element in form_elements(form)}
    assert "Microsoft.Common.PasswordBox" not in types
    assert not [name for name, spec in main_template["parameters"].items() if spec["type"].lower() in ("securestring", "secureobject")]
    text = json.dumps(main_template).lower()
    assert "microsoft.graph" not in text and "graph.microsoft.com" not in text


def test_region_allow_list_is_sourced(form, main_template):
    expected = GENERATOR.allowed_regions(ROOT)
    assert expected, "at least one region must remain after the intersections"
    assert main_template["parameters"]["location"]["allowedValues"] == expected
    scope = next(element for element in form_elements(form) if element["name"] == "resourceScope")
    assert scope["location"]["allowedValues"] == expected
    assert form_outputs(form)["location"] == "[steps('basics').resourceScope.location.name]"
    cli = GENERATOR.cli_regions(ROOT)
    assert set(expected) <= set(cli)
    assert set(expected) <= set(GENERATOR.bastion_developer_regions(ROOT))
    page = GENERATOR.region_page_regions(ROOT)
    if page is not None:
        assert set(expected) == set(cli) & set(page) & set(GENERATOR.bastion_developer_regions(ROOT))


def test_network_plan_matches_the_simple_mode_reservation(plan):
    vnet = ipaddress.ip_network(plan["network"]["vnetCidr"])
    assert str(vnet) == "172.16.0.0/20"
    allocated = {}
    for name, (prefix, index) in plan["network"]["subnets"].items():
        allocated[name] = list(vnet.subnets(new_prefix=prefix))[index]
    hub = CONFIG.simple_mode_hub_subnets(str(vnet), [])
    for name, prefix in hub.items():
        assert str(allocated[name]) == prefix, name
    common = CONFIG.subnet_plan(str(vnet))
    assert str(allocated["common"]) == common["common_subnet_cidr"]
    assert str(allocated["bastion"]) == common["common_bastion_subnet_cidr"]
    values = list(allocated.values())
    for i, left in enumerate(values):
        for right in values[i + 1:]:
            assert not left.overlaps(right), (left, right)
    sizes = sorted(allocated[name].prefixlen for name in ("aca", "aca2", "aks2", "genai", "aks", "dbxpub", "dbxpriv", "webapp"))
    assert sizes == [23, 23, 24, 25, 26, 26, 26, 27]


def test_greenfield_existence_flags_are_false(committed):
    for stage in committed["stages"].values():
        for parameter, value in stage["constants"].items():
            if parameter.endswith("Exists") and parameter != "resolvedManagedIdentityNames":
                assert value in (False, "false"), (stage["template"], parameter)


def test_no_service_principal_secret_names_or_seeding_reads(committed):
    for stage in committed["stages"].values():
        for parameter, value in stage["constants"].items():
            if "SeedingKeyvaultName" in parameter or parameter in (
                    "inputCommonSPIDKey", "inputCommonSPSecretKey", "commonServicePrincipleOIDKey"):
                assert value == "", (stage["template"], parameter)


def test_readme_button_points_at_the_published_branch():
    readme = (PORTAL / "README.md").read_text(encoding="utf-8")
    raw = f"https://raw.githubusercontent.com/{GENERATOR.PUBLISH_REPOSITORY}/{GENERATOR.PUBLISH_BRANCH}/portal/"
    from urllib.parse import quote
    for name in ("azuredeploy.json", "form.json"):
        assert quote(raw + name, safe="") in readme
    assert "Microsoft_Azure_CreateUIDef/CustomDeploymentBlade/uri/" in readme


def strict_requirement(available: bool, reason: str) -> None:
    """Optional tools skip locally; the portal workflow sets PORTAL_STRICT=1 so a missing tool fails."""
    if not available:
        if os.environ.get("PORTAL_STRICT") == "1":
            pytest.fail(reason)
        pytest.skip(reason)


def test_form_matches_the_ui_form_definition_schema(form):
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    strict_requirement(jsonschema is not None, "jsonschema is required to validate form.json")
    schema = json.loads((PORTAL / "data/uiformdefinition-schema/uiFormDefinition.schema.json").read_text(encoding="utf-8"))
    errors = [f"{list(error.path)}: {error.message[:200]}"
              for error in jsonschema.Draft7Validator(schema).iter_errors(form)]
    assert not errors


def test_compiled_templates_match_bicep_sources(tmp_path):
    bicep = os.environ.get("PORTAL_BICEP", "")
    strict_requirement(bool(bicep), "set PORTAL_BICEP to a Bicep 0.37.4 binary")
    version = subprocess.run([bicep, "--version"], capture_output=True, text=True, check=True).stdout
    assert GENERATOR.BICEP_VERSION in version
    for relative, source in GENERATOR.compiled_sources(ROOT).items():
        output = tmp_path / Path(relative).name
        subprocess.run([bicep, "build", str(source), "--outfile", str(output)], check=True, capture_output=True)
        assert output.read_bytes() == (PORTAL / relative).read_bytes(), relative
