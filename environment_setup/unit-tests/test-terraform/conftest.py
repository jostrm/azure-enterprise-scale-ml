"""Pytest glue for the numbered test tiers (tiers.py), shared with test-bicep's base/tiers.py."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tiers import MANIFEST
from base.tiers import ENVIRONMENT_VARIABLE, Selection


SUITE = Path(__file__).resolve().parent
SELECTION = pytest.StashKey[Selection]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--tiers", default=None, metavar="SELECTION",
                     help=f"Test tiers to run, such as 1, 2 or all (default: ${ENVIRONMENT_VARIABLE}, "
                          f"else {MANIFEST.default}). See tiers.py.")


def pytest_configure(config: pytest.Config) -> None:
    for tier in MANIFEST.tiers:
        config.addinivalue_line("markers", f"tier{tier.number}: tier {tier.number} ({tier.name}): {tier.summary}")
    try:
        config.stash[SELECTION] = MANIFEST.resolve(config.getoption("--tiers"), os.environ)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    selection = config.stash[SELECTION]
    base = Path(config.invocation_params.dir)
    named = {(base / argument.split("::", 1)[0]).resolve() for argument in config.args}
    kept, deselected = [], []
    for item in items:
        relative = item.path.resolve().relative_to(SUITE).as_posix()
        tier = MANIFEST.tier_of(relative)
        if tier is not None:
            item.add_marker(getattr(pytest.mark, f"tier{tier}"))
        keep = MANIFEST.keeps(relative, selection, explicit=item.path.resolve() in named)
        (kept if keep else deselected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


WRAPPER = '''# Test wrapper: the three stage modules called directly with arbitrary Bicep parameters.
variable "p11" {
  type = any
}
variable "p12" {
  type = any
}
variable "p13" {
  type = any
}
variable "subscription_id" {
  type = string
}
provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
provider "azurerm" {
  alias = "private_dns"
  features {}
  subscription_id = var.subscription_id
}
provider "azurerm" {
  alias = "own_hub"
  features {}
  subscription_id = var.subscription_id
}
module "stage_11" {
  source          = "../modules/stage-11-rg-common"
  parameters      = var.p11
  subscription_id = var.subscription_id
}
module "stage_12" {
  source          = "../modules/stage-12-network-common"
  parameters      = var.p12
  subscription_id = var.subscription_id
}
module "stage_13" {
  source                  = "../modules/stage-13-rg-level"
  parameters              = var.p13
  subscription_id         = var.subscription_id
  admin_password          = "not-a-secret-0"
  key_vault_secret_expiry = 1893456000
  providers = {
    azurerm             = azurerm
    azurerm.private_dns = azurerm.private_dns
    azurerm.own_hub     = azurerm.own_hub
  }
}
'''


@pytest.fixture(scope="session")
def terraform_copy(tmp_path_factory):
    """A copy of environment_setup/aifactory/terraform with the root and a stage wrapper initialised
    (`init -backend=false`; providers from the registry, or from TF_CLI_CONFIG_FILE's mirror offline)."""
    from harness import copy_terraform_tree, terraform

    base = tmp_path_factory.mktemp("terraform")
    root = copy_terraform_tree(base / "terraform")
    wrapper = root.parent / "stage-wrapper"
    wrapper.mkdir()
    (wrapper / "main.tf").write_text(WRAPPER, encoding="utf-8")
    (wrapper / "versions.tf").write_text((root / "versions.tf").read_text(encoding="utf-8")
                                         .split("  # Remote state")[0] + "}\n", encoding="utf-8")
    # `terraform console` needs an initialised backend: the copy overrides the azurerm backend with a local one
    # (an *_override.tf file), so nothing leaves the machine. validate runs on the unmodified configuration too.
    (root / "backend_override.tf").write_text('terraform {\n  backend "local" {}\n}\n', encoding="utf-8")
    for folder in (root, wrapper):
        result = terraform("init", "-input=false", "-no-color", cwd=folder, timeout=1800)
        assert result.returncode == 0, result.stdout + result.stderr
    return {"root": root, "wrapper": wrapper, "base": base}
