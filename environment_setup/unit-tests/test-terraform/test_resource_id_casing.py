"""ARM ids reach Terraform in any casing (aif-164, 2026-11-17).

The Factory API passes ids lowercased (own_hub_vnet_id ".../resourcegroups/.../microsoft.network/virtualnetworks/...").
ARM and Bicep compare ids case-insensitively; azurerm 5 parses them strictly, and Scenario 2's
ownHubPeeringSpokeToHub failed with 'parsing segment "resourceGroups"'. A strict azurerm id argument fed by a
parameter is normalized with provider::azurerm::normalise_resource_id in the module that owns the argument.
"""
from __future__ import annotations

import re
from pathlib import Path

PEERING = (Path(__file__).resolve().parents[3] / "environment_setup" / "aifactory" / "terraform" / "modules"
           / "vnet-peering" / "main.tf")


def test_the_peering_normalises_the_remote_vnet_id():
    text = PEERING.read_text(encoding="utf-8")
    assert re.search(r"remote_virtual_network_id\s*=\s*provider::azurerm::normalise_resource_id\(var\.remote_vnet_id\)",
                     text), "remote_virtual_network_id must be normalise_resource_id(var.remote_vnet_id)"
