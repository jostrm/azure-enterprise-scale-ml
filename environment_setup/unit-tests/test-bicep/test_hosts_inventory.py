"""Read-only private endpoint discovery and pipeline hosts artifact regressions."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup/aifactory/bicep"
SCRIPT = BICEP / "scripts/generate_hosts_file_info.py"
SPEC = importlib.util.spec_from_file_location("hosts_inventory", SCRIPT)
HOSTS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HOSTS
SPEC.loader.exec_module(HOSTS)
SUB = "11111111-1111-4111-8111-111111111111"
NETWORK_SUB = "22222222-2222-4222-8222-222222222222"
PROJECT = HOSTS.Scope(SUB, "custom-project")
COMMON = HOSTS.Scope(SUB, "custom-common")
NETWORK = HOSTS.Scope(NETWORK_SUB, "network-rg")
ADO = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"


def endpoint(name="unconventional-pe", scope=PROJECT, target=PROJECT, status="Approved", custom=None):
    return {
        "id": f"{scope.id}/providers/Microsoft.Network/privateEndpoints/{name}",
        "provisioningState": "Succeeded",
        "subnet": {"id": f"{NETWORK.id}/providers/Microsoft.Network/virtualNetworks/vnet/subnets/pe"},
        "privateLinkServiceConnections": [{
            "privateLinkServiceId": f"{target.id}/providers/Microsoft.CognitiveServices/accounts/foundry",
            "privateLinkServiceConnectionState": {"status": status},
        }],
        "customDnsConfigs": custom or [],
        "networkInterfaces": [{"id": f"{NETWORK.id}/providers/Microsoft.Network/networkInterfaces/{name}-nic"}],
    }


def nic(*pairs):
    return {"ipConfigurations": [
        {"privateIPAddress": ip, "privateLinkConnectionProperties": {"fqdns": names}}
        for ip, names in pairs
    ]}


class FakeAz:
    def __init__(self, resources=None, nics=None):
        self.resources = resources or {}
        self.nics = nics or {}
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:3] == ("network", "private-endpoint", "list"):
            if args[3:4] != ("--subscription",):
                raise AssertionError("Subscription must be explicit")
            value = self.resources.get(args[6], [])
        elif args[:3] == ("network", "nic", "show"):
            value = self.nics.get(args[4], nic())
        else:
            raise AssertionError(f"Not a read-only expected call: {args}")
        if isinstance(value, Exception):
            raise value
        return value


class HostsInventoryTests(unittest.TestCase):
    def config(self, values=None, argv=None):
        with patch.dict(os.environ, values or {}, clear=True):
            return HOSTS.configuration(argv or [])

    def test_empty_or_unexpanded_subscription_is_rejected_before_cli(self):
        for value in ("", "$(dev_test_prod_sub_id)", "<todo>"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "subscription GUID"):
                    self.config({
                        "HOSTS_SUBSCRIPTION_ID": value,
                        "HOSTS_PROJECT_RESOURCE_GROUP": "project",
                        "HOSTS_COMMON_RESOURCE_GROUP": "common",
                    })

    def test_explicit_custom_groups_cross_subscription_and_empty_prefixes(self):
        targets, scans, output = self.config({
            "HOSTS_SUBSCRIPTION_ID": SUB,
            "HOSTS_PROJECT_RESOURCE_GROUP": PROJECT.resource_group,
            "HOSTS_COMMON_RESOURCE_GROUP": COMMON.resource_group,
            "HOSTS_VNET_SUBSCRIPTION_ID": NETWORK_SUB,
            "HOSTS_VNET_RESOURCE_GROUP": NETWORK.resource_group,
        })
        self.assertEqual([PROJECT, COMMON], targets)
        self.assertEqual([PROJECT, COMMON, NETWORK], scans)
        self.assertIsNone(output)

    def test_naming_fallback_uses_full_config_and_not_salt(self):
        targets, _, _ = self.config({
            "HOSTS_SUBSCRIPTION_ID": SUB, "HOSTS_RG_PREFIX": "gh-",
            "HOSTS_PROJECT_NUMBER": "006", "HOSTS_ENVIRONMENT": "dev",
            "HOSTS_LOCATION_SUFFIX": "eus2", "HOSTS_RG_SUFFIX": "-001",
            "HOSTS_COMMON_NAME": "shared-custom",
            "HOSTS_PROJECT_PREFIX": "", "HOSTS_PROJECT_SUFFIX": "",
        })
        self.assertEqual("gh-project006-eus2-dev-001", targets[0].resource_group)
        self.assertEqual("gh-shared-custom-eus2-dev-001", targets[1].resource_group)

    def test_legacy_twelve_arguments_handle_dash_suffix_and_empty_values(self):
        targets, _, _ = self.config(argv=[
            SUB, "gh-", "006", "eus2", "dev", "-001", "-001", "", "", "",
            "", "-rg",
        ])
        self.assertEqual("gh-project006-eus2-dev-001-rg", targets[0].resource_group)
        self.assertEqual("gh-esml-common-eus2-dev-001", targets[1].resource_group)

    def test_custom_dns_and_nic_mappings_include_every_foundry_alias(self):
        pe = endpoint(custom=[{"fqdn": "foundry.openai.azure.com", "ipAddresses": ["10.0.0.4"]}])
        fake = FakeAz({PROJECT.resource_group: [pe]}, {
            pe["networkInterfaces"][0]["id"]: nic(("10.0.0.4", [
                "foundry.openai.azure.com", "foundry.services.ai.azure.com",
                "foundry.cognitiveservices.azure.com",
            ])),
        })
        result = HOSTS.collect([PROJECT], [PROJECT], fake)
        self.assertEqual(3, len(result["hosts"]))
        self.assertEqual("complete", result["status"])
        self.assertEqual(2, len(fake.calls))

    def test_central_dns_empty_configs_use_exact_nic_ids_and_per_ip_fqdns(self):
        pe = endpoint("custom-acr-endpoint")
        fake = FakeAz({PROJECT.resource_group: [pe]}, {
            pe["networkInterfaces"][0]["id"]: nic(
                ("10.1.1.5", ["registry.azurecr.io"]),
                ("10.1.1.6", ["registry.eastus2.data.azurecr.io"]),
            ),
        })
        result = HOSTS.collect([PROJECT], [PROJECT], fake)
        self.assertEqual({
            "registry.azurecr.io": "10.1.1.5",
            "registry.eastus2.data.azurecr.io": "10.1.1.6",
        }, {item["hostname"]: item["ip"] for item in result["hosts"]})

    def test_arm_wrapped_properties_and_case_normalization(self):
        pe = endpoint()
        pe["privateLinkServiceConnections"] = [{"properties": pe["privateLinkServiceConnections"][0]}]
        resource = {"id": pe.pop("id"), "properties": pe}
        config = {"properties": {
            "privateIPAddress": "10.1.1.4",
            "privateLinkConnectionProperties": {"fqdns": ["Search.SEARCH.windows.net."]},
        }}
        fake = FakeAz({PROJECT.resource_group: [resource]}, {
            pe["networkInterfaces"][0]["id"]: {"properties": {"ipConfigurations": [config]}},
        })
        result = HOSTS.collect([PROJECT], [PROJECT], fake)
        self.assertEqual([{"hostname": "search.search.windows.net", "ip": "10.1.1.4"}], result["hosts"])

    def test_conflicting_hostnames_are_omitted_instead_of_choosing_first_ip(self):
        endpoints = [endpoint(str(index), custom=[
            {"fqdn": "search.search.windows.net", "ipAddresses": [f"10.0.0.{index}"]},
        ]) for index in (4, 5)]
        result = HOSTS.collect([PROJECT], [PROJECT], FakeAz({PROJECT.resource_group: endpoints}))
        self.assertEqual([], result["hosts"])
        self.assertTrue(any("multiple endpoint IPs" in warning for warning in result["warnings"]))

    def test_shared_network_scan_excludes_other_projects(self):
        included = endpoint("ours", scope=NETWORK)
        excluded = endpoint("theirs", scope=NETWORK, target=HOSTS.Scope(SUB, "project-other"))
        fake = FakeAz({NETWORK.resource_group: [included, excluded]}, {
            included["networkInterfaces"][0]["id"]: nic(("10.1.1.4", ["search.search.windows.net"])),
        })
        result = HOSTS.collect([PROJECT, COMMON], [PROJECT, COMMON, NETWORK], fake)
        self.assertEqual([included["id"]], [e["id"] for e in result["endpoints"]])
        self.assertNotIn(("network", "nic", "show", "--ids", excluded["networkInterfaces"][0]["id"]), fake.calls)
        self.assertEqual(NETWORK_SUB, fake.calls[2][4])

    def test_pending_endpoints_and_wildcards_never_become_hosts_entries(self):
        pending = endpoint("pending", status="Pending")
        invalid = endpoint("invalid", custom=[
            {"fqdn": "*.services.ai.azure.com", "ipAddresses": ["10.0.0.4"]},
            {"fqdn": "bad host.example", "ipAddresses": ["10.0.0.4"]},
            {"fqdn": "good.example", "ipAddresses": ["127.0.0.1"]},
        ])
        result = HOSTS.collect([PROJECT], [PROJECT], FakeAz({PROJECT.resource_group: [pending, invalid]}))
        self.assertEqual([], result["hosts"])
        self.assertEqual("partial", result["status"])
        self.assertTrue(any("Succeeded/Approved" in warning for warning in result["warnings"]))

    def test_missing_dns_metadata_does_not_invent_service_names(self):
        result = HOSTS.collect([PROJECT], [PROJECT], FakeAz({PROJECT.resource_group: [endpoint()]}))
        self.assertEqual([], result["hosts"])
        self.assertTrue(any("names will not be guessed" in warning for warning in result["warnings"]))

    def test_manual_approved_connections_and_null_optional_fields(self):
        pe = endpoint(custom=[{"fqdn": "search.search.windows.net", "ipAddresses": ["10.0.0.4"]}])
        pe["manualPrivateLinkServiceConnections"] = pe["privateLinkServiceConnections"]
        pe["privateLinkServiceConnections"] = None
        fake = FakeAz({PROJECT.resource_group: [pe]}, {
            pe["networkInterfaces"][0]["id"]: {
                "ipConfigurations": [{"privateIPAddress": "10.0.0.4", "privateLinkConnectionProperties": None}],
            },
        })
        report = HOSTS.collect([PROJECT], [PROJECT], fake)
        self.assertEqual([{"hostname": "search.search.windows.net", "ip": "10.0.0.4"}], report["hosts"])

    def test_nic_failure_keeps_authoritative_custom_dns_with_visible_warning(self):
        pe = endpoint(custom=[{"fqdn": "search.search.windows.net", "ipAddresses": ["10.0.0.4"]}])
        fake = FakeAz({PROJECT.resource_group: [pe]}, {
            pe["networkInterfaces"][0]["id"]: RuntimeError("NIC access denied"),
        })
        report = HOSTS.collect([PROJECT], [PROJECT], fake)
        self.assertEqual(1, len(report["hosts"]))
        self.assertEqual("partial", report["status"])
        self.assertTrue(any("NIC access denied" in w for w in report["warnings"]))

    def test_inaccessible_scope_is_visible_in_partial_report(self):
        pe = endpoint(custom=[{"fqdn": "search.search.windows.net", "ipAddresses": ["10.0.0.4"]}])
        fake = FakeAz({PROJECT.resource_group: [pe], COMMON.resource_group: RuntimeError("Forbidden")})
        result = HOSTS.collect([PROJECT, COMMON], [PROJECT, COMMON], fake)
        self.assertEqual("partial", result["status"])
        self.assertEqual(1, len(result["hosts"]))
        self.assertTrue(any("Forbidden" in warning for warning in result["warnings"]))

    def test_output_is_hosts_fragment_and_inventory_only(self):
        pe = endpoint(custom=[{"fqdn": "search.search.windows.net", "ipAddresses": ["10.0.0.4"]}])
        result = HOSTS.collect([PROJECT], [PROJECT], FakeAz({PROJECT.resource_group: [pe]}))
        with tempfile.TemporaryDirectory() as folder:
            HOSTS.write_output(Path(folder), result)
            self.assertEqual({"hosts.fragment.txt", "private-endpoints.json"}, {p.name for p in Path(folder).iterdir()})
            fragment = (Path(folder) / "hosts.fragment.txt").read_text()
            self.assertEqual(["10.0.0.4 search.search.windows.net"], [
                line for line in fragment.splitlines() if line and not line.startswith("#")
            ])
            self.assertEqual(result, json.loads((Path(folder) / "private-endpoints.json").read_text()))

    def test_windows_az_cmd_uses_bundled_runtime_without_command_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            cli = Path(folder) / "Azure CLI"
            cli.mkdir()
            (cli / "python.exe").touch()
            result = subprocess.CompletedProcess([], 0, "[]", "")
            with (
                patch.object(HOSTS.shutil, "which", return_value=str(cli / "wbin" / "az.cmd")),
                patch.object(HOSTS.sys, "platform", "win32"),
                patch.object(HOSTS.subprocess, "run", return_value=result) as run,
            ):
                self.assertEqual([], HOSTS.az_json("network", "nic", "show", "--ids", "/subscriptions/id?x=1&y=2"))
            self.assertEqual([str(cli / "python.exe"), "-X", "utf8", "-IBm", "azure.cli"], run.call_args.args[0][:5])
            self.assertIn("/subscriptions/id?x=1&y=2", run.call_args.args[0])
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_no_mappings_has_nonzero_standalone_status(self):
        values = {
            "HOSTS_SUBSCRIPTION_ID": SUB, "HOSTS_PROJECT_RESOURCE_GROUP": PROJECT.resource_group,
            "HOSTS_COMMON_RESOURCE_GROUP": COMMON.resource_group,
        }
        report = HOSTS.collect([PROJECT], [PROJECT], FakeAz())
        with patch.dict(os.environ, values, clear=True), patch.object(HOSTS, "collect", return_value=report):
            with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(1, HOSTS.main([]))
                self.assertIn("No unambiguous hosts entries", stderr.getvalue())


class HostsPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ado = yaml.safe_load(ADO.read_text(encoding="utf-8"))["steps"]
        cls.gha = yaml.safe_load(GHA.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["steps"]

    def test_both_routes_use_environment_inputs_and_publish_reviewable_artifact(self):
        ado = next(s for s in self.ado if s.get("displayName") == "101_generate_hosts_file_info")
        gha = next(s for s in self.gha if s.get("name") == "101_generate_hosts_file_info")
        for task, script in ((ado, ado["inputs"]["inlineScript"]), (gha, gha["run"])):
            self.assertIn("generate_hosts_file_info.py", script)
            self.assertNotIn("70_generate_hosts_file_info.sh", script)
            self.assertIn("exit 0", script)
            self.assertIn("HOSTS_COMMON_RESOURCE_GROUP", task["env"])
            self.assertIn("HOSTS_VNET_RESOURCE_GROUP", task["env"])
            self.assertIn("HOSTS_OUTPUT_DIR", task["env"])
        self.assertEqual("$(dev_test_prod_sub_id)", ado["env"]["HOSTS_SUBSCRIPTION_ID"])
        self.assertEqual("${{ env.dev_test_prod_sub_id }}", gha["env"]["HOSTS_SUBSCRIPTION_ID"])
        self.assertTrue(ado["continueOnError"])
        self.assertTrue(gha["continue-on-error"])
        self.assertTrue(any(s.get("task") == "PublishPipelineArtifact@1" and "hosts" in s.get("displayName", "") for s in self.ado))
        self.assertTrue(any(s.get("uses") == "actions/upload-artifact@v4" and "hosts" in s.get("name", "") for s in self.gha))

    def test_actual_powershell_wrappers_keep_hosts_failure_nonblocking(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell Core is needed for workflow execution tests")
        tasks = [
            ("ado", next(s for s in self.ado if s.get("displayName") == "101_generate_hosts_file_info")["inputs"]["inlineScript"]),
            ("gha", next(s for s in self.gha if s.get("name") == "101_generate_hosts_file_info")["run"]),
        ]
        for kind, script in tasks:
            for exit_code in (0, 1):
                with self.subTest(kind=kind, exit_code=exit_code), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    exporter = root / "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/generate_hosts_file_info.py"
                    exporter.parent.mkdir(parents=True)
                    exporter.write_text(
                        "import os, pathlib, sys\np=pathlib.Path(os.environ['HOSTS_OUTPUT_DIR'])\n"
                        "p.mkdir(parents=True, exist_ok=True)\n(p/'private-endpoints.json').write_text('{}')\n"
                        f"sys.exit({exit_code})\n", encoding="utf-8",
                    )
                    discovery = "function Get-Command { param($Name,$CommandType,$ErrorAction); " + (
                        "return [pscustomobject]@{Source='" + sys.executable.replace("'", "''") + "'} }\n"
                    )
                    result = subprocess.run(
                        [pwsh, "-NoProfile", "-NonInteractive", "-Command", discovery + script],
                        env=os.environ | {
                            "GITHUB_WORKSPACE": folder, "SYSTEM_DEFAULTWORKINGDIRECTORY": folder,
                            "HOSTS_OUTPUT_DIR": str(root / "output"), "GITHUB_OUTPUT": str(root / "step-output"),
                        },
                        capture_output=True, text=True, check=False, timeout=30,
                    )
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    if exit_code:
                        self.assertIn("warning", result.stdout.lower())
                    if kind == "gha":
                        self.assertIn("ready=true", (root / "step-output").read_text(encoding="utf-8-sig"))
                    else:
                        self.assertIn("variable=aifactoryHostsInventoryReady]true", result.stdout)

    def test_dashboard_skip_conditions_are_deliberate_and_independent(self):
        dashboard = next(s for s in self.gha if s.get("name") == "10-aifactory-dashboards")
        reconcile = next(s for s in self.gha if s.get("name") == "10b-reconcile-aifactory-dashboard")
        for task in (dashboard, reconcile):
            self.assertIn("inputs.phase == 'infra'", task["if"])
        self.assertIn("debug_disable_10_aifactory_dashboards", dashboard["if"])
        self.assertNotIn("debug_disable_10_aifactory_dashboards", reconcile["if"])


if __name__ == "__main__":
    unittest.main()
