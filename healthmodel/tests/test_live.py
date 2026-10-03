"""Opt-in live smoke tests against a deployed health model.

    $env:AIF_HEALTHMODEL_LIVE = "1"
    $env:AIF_HEALTHMODEL_ID = "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CloudHealth/healthmodels/<name>"
    python -m pytest tests/test_live.py -m azure

Read-only, except test_external_report_round_trip which needs AIF_HEALTHMODEL_LIVE_WRITE=1 and
reports a short-lived Healthy signal on the root entity.
"""
from __future__ import annotations

import os
import time

import pytest

from aifactory_healthmodel.azure import AzCliTransport
from aifactory_healthmodel.client import HealthModelClient

pytestmark = [
    pytest.mark.azure,
    pytest.mark.skipif(os.environ.get("AIF_HEALTHMODEL_LIVE") != "1" or not os.environ.get("AIF_HEALTHMODEL_ID"),
                       reason="set AIF_HEALTHMODEL_LIVE=1 and AIF_HEALTHMODEL_ID to run live tests"),
]


@pytest.fixture(scope="module")
def client():
    return HealthModelClient(os.environ["AIF_HEALTHMODEL_ID"], AzCliTransport())


def test_model_is_provisioned_with_identity(client):
    model = client.model()
    assert model["properties"]["provisioningState"] == "Succeeded"
    assert model["identity"]["type"] == "SystemAssigned"


def test_root_and_layers_are_connected(client):
    summary = client.summary()
    assert summary["root"]["state"] in ("Healthy", "Degraded", "Unhealthy", "Unknown")
    assert summary["layers"], "the root should have layer entities"
    names = {e["name"] for e in client.entities()}
    for rel in client.relationships():
        props = rel["properties"]
        assert props["parentEntityName"] in names and props["childEntityName"] in names


def test_alerts_endpoint_is_readable(client):
    assert isinstance(client.alerts(hours=24), list)


@pytest.mark.skipif(os.environ.get("AIF_HEALTHMODEL_LIVE_WRITE") != "1", reason="write test is opt-in")
def test_external_report_round_trip(client):
    client.ingest_health_report("root", "aifactory-live-test", "Healthy", value=1, expires_in_minutes=5,
                                context="aifactory-healthmodel live test")
    for _ in range(12):
        signals = client.entity("root")["properties"].get("signalGroups", {}).get("external", {}).get("signals", [])
        if any(s.get("name") == "aifactory-live-test" for s in signals):
            return
        time.sleep(5)
    pytest.fail("external signal did not appear on the root entity")
