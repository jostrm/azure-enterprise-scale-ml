"""ADO and GHA pass every GenAI phase template the same --parameters.

A parameter one provider forwards and the other leaves out silently falls back to the Bicep default
on that provider. GHA's 65-compute-services step left out aksExists, aksEnablePrivateCluster,
aksOutboundType, aksPrivateDNSZone and aksSkuName. So on GHA the GenAI cluster ignored those settings:
AKS_OUTBOUND_TYPE=userDefinedRouting still produced a public egress load balancer, and the aksExists
reconciliation never reached the cluster module, so every run re-PUT the cluster. GHA's 63 step left
out enablePublicNetworkAccessForCognitive, so Content Safety, Vision, Speech and Document Intelligence
kept public network access whatever ALLOW_PUBLIC_ACCESS_WHEN_BEHIND_VNET said, and its 63 and 64 steps
left out the CMK seeding Key Vault, so cmk=true had no vault to use.

KNOWN_GAPS lists the remaining reviewed differences; closing one must also remove its entry.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache

import pytest

from domain.pipeline_contracts import ADO_SERVICES, GHA_PHASE, deployments, load_pipeline


# module -> {parameter: (provider that passes it, reason the other one does not)}
KNOWN_GAPS = {
    "01-foundation.bicep": {
        name: ("ado", "GHA runs one network_env per job; per-environment keys are forbidden there")
        for name in ("DEBUG_network_env_dev", "DEBUG_network_env_stage", "DEBUG_network_env_prod")
    },
    "02-core-infrastructure.bicep": {
        "bingExists": ("ado", "declared but unused by 02"),
    },
    "03-cognitive-services.bicep": {
        "disableLocalAuth": ("gha", "ADO defines disableLocalAuth but does not forward it to 03 yet"),
        "storageAccountSkuName": ("gha", "ADO defines skuStorageAccount* but forwards them only to 02 yet"),
    },
    "04-databases.bicep": {
        "postgreSQLVersion": ("ado", "ADO pins '17', the module default GHA relies on"),
    },
    "09-ai-foundry-2025-v4.bicep": {
        "disableLocalAuth": ("gha", "ADO defines disableLocalAuth but does not forward it to 09 yet"),
    },
}
# (module, parameter, the pipeline variable both providers pass to it)
FORWARDING = [
    *(("05-compute-services.bicep", name, name) for name in (
        "aksExists", "aksEnablePrivateCluster", "aksOutboundType", "aksPrivateDNSZone", "aksSkuName")),
    *(("07-ml-data-platform.bicep", name, name) for name in ("aksExists", "aksOutboundType", "aksPrivateDNSZone")),
    ("03-cognitive-services.bicep", "enablePublicNetworkAccessForCognitive", "allowPublicAccessWhenBehindVnet"),
    *((module, name, name) for module in ("03-cognitive-services.bicep", "04-databases.bicep")
      for name in ("admin_bicep_kv_fw", "admin_bicep_kv_fw_rg", "admin_bicep_input_keyvault_subscription")),
]


@lru_cache(maxsize=None)
def parameters_by_module(path):
    result = defaultdict(set)
    for deployment in deployments(load_pipeline(path)):
        result[deployment.module] |= set(deployment.parameters)
    return dict(result)


def shared_modules():
    return sorted(set(parameters_by_module(ADO_SERVICES)) & set(parameters_by_module(GHA_PHASE)))


def forwarded(module, path, parameter):
    values = {item.parameters.get(parameter) for item in deployments(load_pipeline(path)) if item.module == module}
    assert len(values) == 1, f"{path.name}/{module}: {parameter} differs between steps: {values}"
    return values.pop()


def test_every_genai_phase_template_is_compared():
    assert "05-compute-services.bicep" in shared_modules()
    assert set(KNOWN_GAPS) <= set(shared_modules()), "remove gaps for templates no longer deployed by both"
    assert all(reason.strip() for gaps in KNOWN_GAPS.values() for _, reason in gaps.values())


@pytest.mark.parametrize("module", shared_modules())
def test_ado_and_gha_pass_the_same_parameters(module):
    ado, gha = parameters_by_module(ADO_SERVICES)[module], parameters_by_module(GHA_PHASE)[module]
    actual = {name: "ado" for name in ado - gha} | {name: "gha" for name in gha - ado}
    expected = {name: provider for name, (provider, _) in KNOWN_GAPS.get(module, {}).items()}
    assert actual == expected, (
        f"{module}: unreviewed={ {k: v for k, v in actual.items() if expected.get(k) != v} }, "
        f"stale KNOWN_GAPS={sorted(set(expected) - set(actual))}"
    )


@pytest.mark.parametrize("module,parameter,source", FORWARDING)
def test_settings_reach_the_genai_templates_unchanged(module, parameter, source):
    assert forwarded(module, ADO_SERVICES, parameter) == f"$({source})"
    assert forwarded(module, GHA_PHASE, parameter) == "${{ env." + source + " }}"
