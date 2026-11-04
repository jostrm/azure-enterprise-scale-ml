from unittest.mock import patch

import pytest

from azure_esml.cli import execute, parser
from ml_model_factory.config import write_json


TENANT = "00000000-0000-0000-0000-000000000001"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"


def arguments(tmp_path, subscription=True):
    plan = tmp_path / "plan.json"
    write_json(plan, {"schema": "esml.lake-publication/v2"})
    args = ["lake-publish", "--plan", str(plan), "--root", str(tmp_path), "--tenant-id", TENANT, "--execute"]
    if subscription:
        args += ["--subscription-id", SUBSCRIPTION]
    return parser().parse_args(args)


def test_subscription_bound_auth_checks_tenant_before_publishing(tmp_path):
    with patch("ml_model_factory.project.azure_cli", return_value={"id": SUBSCRIPTION, "tenantId": TENANT}) as cli, \
            patch("azure.identity.AzureCliCredential") as credential, \
            patch("azure_esml.domain_layer.lake_publication.publish", return_value={"state": "committed"}) as publish:
        assert execute(arguments(tmp_path))["state"] == "committed"
    cli.assert_called_once_with("account", "show", "--subscription", SUBSCRIPTION)
    credential.assert_called_once_with(subscription=SUBSCRIPTION, process_timeout=60)
    publish.assert_called_once()


def test_mismatched_subscription_tenant_never_publishes(tmp_path):
    with patch("ml_model_factory.project.azure_cli", return_value={"id": SUBSCRIPTION, "tenantId": "other"}), \
            patch("azure.identity.AzureCliCredential") as credential, \
            patch("azure_esml.domain_layer.lake_publication.publish") as publish:
        with pytest.raises(ValueError, match="requested tenant"):
            execute(arguments(tmp_path))
    credential.assert_not_called()
    publish.assert_not_called()


def test_existing_tenant_only_auth_remains_explicit(tmp_path):
    with patch("azure.identity.AzureCliCredential") as credential, \
            patch("azure_esml.domain_layer.lake_publication.publish"):
        execute(arguments(tmp_path, subscription=False))
    credential.assert_called_once_with(tenant_id=TENANT, process_timeout=60)
