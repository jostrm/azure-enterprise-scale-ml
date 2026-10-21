"""Consumer JSON examples must work offline after copying out of the module."""

import importlib.util
import ipaddress
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import Mock
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
SCRIPTS = BICEP / "scripts"
EXAMPLES = BICEP / "copy_to_local_settings" / "ai-gateway"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("apim_gateway_example_runner", SCRIPTS / "apim-gateway-deployment.py")
gw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gw)
from apim_gateway_config import load_config


@pytest.fixture
def consumer_area():
    area = ROOT / ".apim-examples-unit" / uuid.uuid4().hex
    area.mkdir(parents=True)
    try:
        yield area
    finally:
        shutil.rmtree(area)
        try:
            area.parent.rmdir()
        except OSError:
            pass


@pytest.mark.parametrize("mode", ["managed", "existing"])
def test_copied_example_plans_and_transforms_without_cli(mode, consumer_area, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Examples must not invoke Azure or subprocesses"))
    monkeypatch.setattr(gw.subprocess, "run", forbidden)
    cli = Mock(read=forbidden, invoke=forbidden)
    original = EXAMPLES / f"apim.{mode}.dev.example.json"
    source_bytes = original.read_bytes()
    config_file = consumer_area / "aifactory" / "gateways" / "apim.dev.json"
    config_file.parent.mkdir(parents=True)
    shutil.copyfile(original, config_file)
    config = load_config(config_file, "dev", {})
    assert config["serviceMode"] == mode
    assert json.loads(source_bytes).get("serviceMode", "existing") == mode
    output = consumer_area / "artifacts" / "apim-dev"
    sources_before = gw.source_manifest()
    assert gw.main(["--environment", "dev", "--config", str(config_file),
                    "--output-dir", str(output)], cli=cli, environ={}) == 0
    plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
    receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert plan["config"] == config
    assert plan["offline"] and not plan["armPreviewExecuted"]
    assert plan["sourceHashes"] == sources_before == gw.source_manifest()
    assert receipt["status"] == "offline-plan" and not receipt["resourceWritesAttempted"]
    assert len(plan["planDigest"]) == 64
    runner = gw.Deployment(config, gw.Artifacts(output, config_file), cli=cli)
    principal = "33333333-3333-3333-3333-333333333333"
    runner.service = {"identity": {"type": "SystemAssigned", "principalId": principal}}
    params = runner.parameters("configuration")
    assert params["apimServiceName"] == config["serviceName"]
    assert params["apimManagedIdentityPrincipalId"] == principal
    assert params["azureOpenAIBackends"] == config["api"]["azureOpenAIBackends"]
    assert params["aggregateTokensPerMinute"] == config["api"]["aggregateTokensPerMinute"]
    if mode == "managed":
        assert config["publisherEmail"].endswith("@example.invalid")
        prefix = ipaddress.ip_network(config["network"]["integrationSubnetPrefix"])
        assert prefix.subnet_of(ipaddress.ip_network("10.0.0.0/8")) and prefix.prefixlen <= 27
        assert runner.parameters("service-bootstrap", "Enabled")["publicNetworkAccess"] == "Enabled"
        assert runner.parameters("service-lockdown")["publicNetworkAccess"] == "Disabled"
        assert runner.parameters("private-endpoint")["privateDnsMode"] == "policy"
        assert runner.parameters("private-endpoint")["privateDnsZoneId"] == ""
        assert runner.parameters("network")["integrationSubnetPrefix"] == str(prefix)
        assert not config["network"]["createIntegrationSubnet"]
    else:
        assert "serviceMode" not in json.loads(source_bytes)
        assert "network" not in config
        assert plan["phases"] == ["inventory-existing-service", "configuration"]
    serialized = json.dumps(plan).lower()
    for credential in ('"apikey"', '"api_key"', '"clientsecret"', '"password"', '"accesstoken"',
                       '"subscriptionkey"', "bearer ", "-----begin"):
        assert credential not in serialized
    assert config_file.read_bytes() == original.read_bytes() == source_bytes
    assert list(config_file.parent.iterdir()) == [config_file]
    assert not output.is_relative_to(config_file.parent)
    assert not output.is_relative_to(BICEP)
    forbidden.assert_not_called()
