"""Offline contracts for exact-name reuse of discovered project identities."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
ENTRYPOINTS = BICEP / "esml-genai-1"
NAMING = BICEP / "modules" / "common" / "CmnAIfactoryNaming.bicep"
ROUTES = {
    "01-foundation.bicep",
    "02-core-infrastructure.bicep",
    "03-cognitive-services.bicep",
    "04-databases.bicep",
    "05-compute-services.bicep",
    "06-ai-platform.bicep",
    "07-ml-data-platform.bicep",
    "08-rbac-security.bicep",
    "08b-rbac-common-rg.bicep",
    "09-ai-foundry-2025-v2.bicep",
    "09-ai-foundry-2025-v3.bicep",
    "09-ai-foundry-2025-v4.bicep",
    "11-integration.bicep",
}


def source(path):
    return re.sub(r"(?m)^\s*//.*$", "", path.read_text(encoding="utf-8-sig"))


def compact(text):
    """Ignore formatting while retaining whitespace inside string literals."""
    return "".join(re.findall(r"'(?:\\.|[^'\\])*'|\S", text))


def module_block(text, symbol):
    match = re.search(
        rf"^\s*module\s+{re.escape(symbol)}\s+.*?"
        r"(?=^\s*(?:module|resource|var|param|output)\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"Missing module {symbol}")
    return match.group()


class TestResolvedIdentityBicep(unittest.TestCase):
    def test_all_naming_routes_accept_and_forward_internal_optional_names(self):
        callers = {
            path.name: source(path)
            for path in ENTRYPOINTS.glob("*.bicep")
            if re.search(
                r"\bmodule\s+\w+\s+'[^']*/CmnAIfactoryNaming\.bicep'",
                source(path),
            )
        }
        self.assertEqual(ROUTES, set(callers))
        for name, text in callers.items():
            with self.subTest(route=name):
                self.assertRegex(
                    text,
                    r"@description\(\s*'Internal only:[^']*'\s*\)\s*"
                    r"param\s+resolvedManagedIdentityNames\s+object\s*=\s*\{\s*\}",
                )
                self.assertRegex(
                    module_block(text, "namingConvention"),
                    r"\bparams\s*:\s*\{[\s\S]*?"
                    r"\bresolvedManagedIdentityNames\s*:\s*resolvedManagedIdentityNames\b",
                )

    def test_naming_defaults_remain_backward_compatible(self):
        text = compact(source(NAMING))
        for expression in (
            "param resolvedManagedIdentityNames object = {}",
            "param keepMIandKVsuffixAs001 bool = false",
            "var projectName = 'prj${projectNumber}'",
            "var miSuffix = keepMIandKVsuffixAs001 ? '-001' : resourceSuffix",
            "var randomSalt = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? substring(randomValue, 0, 10): aifactorySalt10char",
            "var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)",
        ):
            with self.subTest(expression=expression):
                self.assertIn(compact(expression), text)

    def test_each_identity_independently_prefers_exact_name_with_safe_empty_fallback(self):
        text = compact(source(NAMING))
        for symbol, key, default in (
            ("miPrjName", "project", "mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${miSuffix}"),
            ("miACAName", "containerApps", "mi-aca-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${miSuffix}"),
        ):
            with self.subTest(identity=key):
                self.assertIn(
                    compact(
                        f"var {symbol} = empty(resolvedManagedIdentityNames.?{key}) "
                        f"? '{default}' : resolvedManagedIdentityNames.{key}"
                    ),
                    text,
                )
                self.assertIn(compact(f"output {symbol} string = {symbol}"), text)
                self.assertIn(compact(f"{symbol}: {symbol}"), text)

    def test_foundation_only_creates_when_no_resolved_name_and_prior_flag_false(self):
        text = source(ENTRYPOINTS / "01-foundation.bicep")
        for symbol, key, flag, name in (
            ("miForPrj", "project", "miPrj", "miPrjName"),
            ("miForAca", "containerApps", "miACA", "miACAName"),
        ):
            with self.subTest(identity=key):
                block = compact(module_block(text, symbol))
                self.assertIn(
                    compact(
                        f"= if (empty(resolvedManagedIdentityNames.?{key}) "
                        f"&& !resourceExists.{flag}) {{"
                    ),
                    block,
                )
                self.assertIn(compact(f"params: {{ name: {name}"), block)
                self.assertIn(
                    compact("scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)"),
                    block,
                )
                self.assertIn(compact(f"{flag}: {flag}Exists"), compact(text))

    def test_static_aml_and_data_platform_references_use_exact_project_identity(self):
        for name in ("06-ai-platform.bicep", "07-ml-data-platform.bicep"):
            with self.subTest(route=name):
                text = compact(source(ENTRYPOINTS / name))
                self.assertIn(
                    compact(
                        "var miPrjName_Static = empty(resolvedManagedIdentityNames.?project) "
                        "? 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${randomSaltLogic}${resourceSuffix}' "
                        ": resolvedManagedIdentityNames.project"
                    ),
                    text,
                )
                self.assertIn(
                    compact(
                        "resource miPrjREF 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = { "
                        "name: miPrjName_Static "
                        "scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)"
                    ),
                    text,
                )

    def test_compute_rbac_and_foundry_identity_lookups_consume_resolved_naming_outputs(self):
        for name, lookup, local_name, output_name in (
            ("05-compute-services.bicep", "getACAMIPrincipalId", "miACAName", "miACAName"),
            ("08-rbac-security.bicep", "getProjectMIPrincipalId", "miPrjName", "miPrjName"),
            ("08b-rbac-common-rg.bicep", "getProjectMIPrincipalId", "miPrjName", "miPrjName"),
            ("09-ai-foundry-2025-v3.bicep", "getProjectMIPrincipalId", "miPrjName", "miPrjName"),
            ("09-ai-foundry-2025-v3.bicep", "getAcaMIPrincipalId", "miAcaName", "miACAName"),
            ("09-ai-foundry-2025-v4.bicep", "getProjectMIPrincipalId", "miPrjName", "miPrjName"),
            ("09-ai-foundry-2025-v4.bicep", "getAcaMIPrincipalId", "miAcaName", "miACAName"),
        ):
            with self.subTest(route=name, lookup=lookup):
                text = source(ENTRYPOINTS / name)
                self.assertIn(
                    compact(f"var {local_name} = namingConvention.outputs.{output_name}"),
                    compact(text),
                )
                block = compact(module_block(text, lookup))
                self.assertIn(compact(f"managedIdentityName: {local_name}"), block)
                self.assertIn(
                    compact("scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)"),
                    block,
                )


if __name__ == "__main__":
    unittest.main()
