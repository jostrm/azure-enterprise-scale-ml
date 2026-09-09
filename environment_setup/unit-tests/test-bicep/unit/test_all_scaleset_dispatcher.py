"""Contracts for the unified AI Factory scale-set dispatcher."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DISPATCHER = ROOT / "bootstrap/ALL-create-new-aifactory-scaleset.sh"
ADO_LAUNCHER = ROOT / "bootstrap/ADO-create-new-aifactory-scaleset.sh"
GHA_LAUNCHER = ROOT / "bootstrap/GHA-create-new-aifactory-scaleset.sh"
SHARED = ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh"
CONFIG = ROOT / "bootstrap/lib/aifactory_scaleset_config.py"
ADO_VARIABLES = (
    ROOT
    / "environment_setup/aifactory/bicep/copy_to_local_settings"
    / "azure-devops/esml-yaml-pipelines/variables/variables.yaml"
)
ADO_COMMON_JOB = (
    ROOT
    / "environment_setup/aifactory/bicep/copy_to_local_settings"
    / "azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-1-aif-cmn.yaml"
)
GHA_ENV = (
    ROOT
    / "environment_setup/aifactory/bicep/copy_to_local_settings"
    / "github-actions/.env.template"
)
GHA_PUBLISHER = (
    ROOT
    / "environment_setup/aifactory/bicep/copy_to_local_settings"
    / "github-actions/03a-GH-create-or-update-github-variables.sh"
)
GHA_COMMON = (
    ROOT
    / "environment_setup/aifactory/bicep/copy_to_local_settings"
    / "github-actions/infra-common.yml"
)
COMMON_BICEP = (
    ROOT / "environment_setup/aifactory/bicep/esml-common/main/13-rgLevel.bicep"
)
START = ROOT / "00-start.sh"


class TestAllScaleSetDispatcher(unittest.TestCase):
    def test_routes_to_existing_ado_and_gha_launchers(self) -> None:
        script = DISPATCHER.read_text(encoding="utf-8")
        self.assertIn("AIF_ORCHESTRATOR", script)
        self.assertIn("--orchestrator", script)
        self.assertIn("ADO-create-new-aifactory-scaleset.sh", script)
        self.assertIn("GHA-create-new-aifactory-scaleset.sh", script)
        self.assertIn('exec bash "$LAUNCHER" "${FORWARD_ARGS[@]}"', script)

    def test_start_script_copies_unified_dispatcher(self) -> None:
        self.assertIn(
            "ALL-create-new-aifactory-scaleset.sh",
            START.read_text(encoding="utf-8"),
        )

    def test_route_specific_launchers_are_isolated(self) -> None:
        ado = ADO_LAUNCHER.read_text(encoding="utf-8")
        gha = GHA_LAUNCHER.read_text(encoding="utf-8")
        shared = SHARED.read_text(encoding="utf-8")
        self.assertIn('readonly AIF_SCALESET_ROUTE="ado"', ado)
        self.assertNotIn('AIF_SCALESET_ROUTE="gha"', ado)
        self.assertIn('readonly AIF_SCALESET_ROUTE="gha"', gha)
        self.assertNotIn('AIF_SCALESET_ROUTE="ado"', gha)
        self.assertIn(
            '[[ "$AIF_ROUTE" != "ado" ]] || aif_ensure_ado_auth',
            shared,
        )
        self.assertIn(
            '[[ "$AIF_ROUTE" != "gha" ]] || aif_publish_github_configuration',
            shared,
        )

    def test_shared_bootstrap_copies_unified_dispatcher(self) -> None:
        shared = SHARED.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            shared.count("ALL-create-new-aifactory-scaleset.sh"),
            3,
        )

    def test_dns_forwarder_is_reconciled_before_optional_vpn(self) -> None:
        shared = SHARED.read_text(encoding="utf-8")
        external_hub = shared[
            shared.index("aif_prepare_external_access_hub()")
            : shared.index("aif_write_state_and_configure()")
        ]
        self.assertIn("aif_ensure_hub_dns_forwarder external", external_hub)
        self.assertLess(
            external_hub.index("aif_ensure_hub_dns_forwarder external"),
            external_hub.index("aif_ensure_vpn_access_hub external"),
        )
        forwarder = shared[
            shared.index("aif_ensure_hub_dns_forwarder()")
            : shared.index("aif_create_vpn_public_ip()")
        ]
        self.assertIn("Azure DNS Private Resolver inbound endpoint", forwarder)
        self.assertIn("168.63.129.16", forwarder)

    def test_ado_environments_are_authorized_before_pipeline_run(self) -> None:
        shared = SHARED.read_text(encoding="utf-8")
        deployment = shared[
            shared.index("aif_deploy_ado()")
            : shared.index("aif_deploy_github()")
        ]
        self.assertIn("aif_authorize_ado_environment", deployment)
        self.assertLess(
            deployment.index("aif_authorize_ado_environment"),
            deployment.index("aif_run_ado_pipeline"),
        )

    def test_admin_vm_size_flows_through_both_routes(self) -> None:
        shared = SHARED.read_text(encoding="utf-8")
        config = CONFIG.read_text(encoding="utf-8")
        ado_variables = ADO_VARIABLES.read_text(encoding="utf-8")
        ado_job = ADO_COMMON_JOB.read_text(encoding="utf-8")
        gha_env = GHA_ENV.read_text(encoding="utf-8")
        gha_publisher = GHA_PUBLISHER.read_text(encoding="utf-8")
        gha_common = GHA_COMMON.read_text(encoding="utf-8")
        bicep = COMMON_BICEP.read_text(encoding="utf-8")

        self.assertIn("AIF_ADMIN_VM_SIZE=Standard_D2s_v5", shared)
        self.assertIn("aif_validate_admin_vm_size", shared)
        self.assertIn('"adminVMSize": state.get(', config)
        self.assertIn('"ADMIN_VM_SIZE": state.get(', config)
        self.assertIn('adminVMSize: "Standard_D2s_v5"', ado_variables)
        self.assertIn('--parameters adminVMSize="$(adminVMSize)"', ado_job)
        self.assertIn('ADMIN_VM_SIZE="Standard_D2s_v5"', gha_env)
        self.assertIn('"ADMIN_VM_SIZE"', gha_publisher)
        self.assertEqual(gha_common.count("--parameters adminVMSize="), 3)
        self.assertIn(
            "param adminVMSize string = 'Standard_D2s_v5'",
            bicep,
        )
        self.assertIn("vmSize: adminVMSize", bicep)

    def test_storage_prefix_is_derived_from_aifactory_prefix(self) -> None:
        config = CONFIG.read_text(encoding="utf-8")
        self.assertIn(
            're.sub(r"[^a-z0-9]", "", state["prefix"].lower())[:8]',
            config,
        )
        self.assertIn(
            '"commonLakeNamePrefixMax8chars": lake_prefix or "aifactory"',
            config,
        )


if __name__ == "__main__":
    unittest.main()
