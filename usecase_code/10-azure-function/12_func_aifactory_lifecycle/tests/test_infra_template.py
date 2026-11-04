"""Contract of infra/function-app.bicep and deploy.ps1: a Flex Consumption app that needs no Always On.

Subscription governance switched Always On off on the Dedicated (B1) app every night (observed 2026-10-22 and
2026-10-23, ~01:36 CEST); without it the host idles and the timer and queue triggers stop. Flex Consumption has no
Always On: the platform starts instances for every trigger.
"""

import json
import re

from conftest import TEMPLATE_ROOT

BICEP = (TEMPLATE_ROOT / "infra" / "function-app.bicep").read_text(encoding="utf-8")
DEPLOY = (TEMPLATE_ROOT / "deploy.ps1").read_text(encoding="utf-8")
SETTINGS = json.loads((TEMPLATE_ROOT / "settings.example.json").read_text(encoding="utf-8"))

# Site properties and app settings Flex Consumption rejects or ignores (Microsoft Learn, "Flex Consumption plan
# deprecations" in the Functions app settings reference).
FLEX_INVALID = ("alwaysOn", "linuxFxVersion", "ftpsState", "vnetRouteAllEnabled", "healthCheckPath")
FLEX_INVALID_SETTINGS = ("FUNCTIONS_WORKER_RUNTIME", "FUNCTIONS_EXTENSION_VERSION", "SCM_DO_BUILD_DURING_DEPLOYMENT",
                         "ENABLE_ORYX_BUILD", "WEBSITE_RUN_FROM_PACKAGE")


def test_plan_is_flex_consumption():
    plan = re.search(r"resource plan 'Microsoft\.Web/serverfarms@[^']+' = \{(.*?)\n\}", BICEP, re.S).group(1)
    assert "name: 'FC1'" in plan and "tier: 'FlexConsumption'" in plan
    assert "param planSku" not in BICEP


def test_site_has_no_always_on_or_dedicated_only_properties():
    for name in FLEX_INVALID:
        assert re.search(r"\b" + name + r"\s*:", BICEP) is None, name


def test_flex_invalid_app_settings_are_never_set_and_never_passed_through():
    for name in FLEX_INVALID_SETTINGS:
        assert re.search(r"\{\s*name:\s*'" + name + "'", BICEP) is None, name
        # Extra settings from the settings file are filtered, so a stale settings file cannot break the deployment.
        assert re.search(r"^\s+'" + name + r"'$", BICEP, re.M), name


def test_function_app_config_runs_python_from_an_identity_based_package_container():
    config = re.search(r"functionAppConfig: \{(.*?)\n    \}", BICEP, re.S).group(1)
    assert "type: 'blobContainer'" in config
    assert "type: 'SystemAssignedIdentity'" in config
    assert "name: 'python'" in config and "version: pythonVersion" in config
    assert "instanceMemoryMB: instanceMemoryMB" in config and "maximumInstanceCount: maximumInstanceCount" in config
    assert "resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@" in BICEP


def test_integration_subnet_must_be_delegated_to_container_apps_environments():
    description = re.search(r"@description\('([^']*)'\)\nparam integrationSubnetId", BICEP).group(1)
    assert "Microsoft.App/environments" in description
    assert "Microsoft.App/environments" in DEPLOY  # deploy.ps1 checks the delegation before it deploys


def test_deploy_script_and_example_settings_have_no_dedicated_plan_sku():
    assert "planSku" not in DEPLOY
    assert "planSku" not in SETTINGS
    assert not SETTINGS["integrationSubnetId"].endswith("-webapp")
