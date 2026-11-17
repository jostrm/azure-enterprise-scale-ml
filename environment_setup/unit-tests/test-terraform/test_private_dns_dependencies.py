"""Every private DNS zone group waits for the private endpoint it points at (aif-164, 2026-11-17).

modules/private-dns addresses its parent endpoint by a string `parent_id`, so Terraform sees no dependency on the
endpoint. The Bicep port keeps `dependsOn` on the owning module; in Terraform each `../private-dns` call must list the
module whose `dns_config` it consumes in its `depends_on`. Without it, aif-164's first Terraform common apply created
`privateDnsZoneGroups` before the data lake endpoints existed (404 ResourceNotFound, 400 ReferencedResourceNotProvisioned).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

TERRAFORM = Path(__file__).resolve().parents[3] / "environment_setup" / "aifactory" / "terraform"
_BLOCK = re.compile(r'(?ms)^module "(?P<name>[A-Za-z0-9_]+)" \{\n(?P<body>.*?)^\}')


def _private_dns_calls():
    calls = []
    for path in sorted(TERRAFORM.rglob("*.tf")):
        for match in _BLOCK.finditer(path.read_text(encoding="utf-8")):
            body = match.group("body")
            if re.search(r'source\s*=\s*"\.\./private-dns"', body):
                owner = re.search(r"dns_config\s*=\s*module\.([A-Za-z0-9_]+)", body)
                calls.append((path.relative_to(TERRAFORM).as_posix(), match.group("name"),
                              owner.group(1) if owner else None, body))
    return calls


def test_the_private_dns_calls_are_found():
    names = {name for _, name, _, _ in _private_dns_calls()}
    assert {"privateDnsDatalake", "privateDnsContainerRegistryCommon", "privateDnsKeyVaultCmn"} <= names


@pytest.mark.parametrize("path,name,owner,body", _private_dns_calls(), ids=lambda value: value if isinstance(value, str) and "\n" not in value else None)
def test_each_private_dns_call_depends_on_the_module_that_owns_its_endpoints(path, name, owner, body):
    assert owner, f"{path} {name}: dns_config does not come from a module"
    depends = re.search(r"depends_on\s*=\s*\[(?P<list>[^\]]*)\]", body)
    assert depends and re.search(r"\bmodule\." + re.escape(owner) + r"\b", depends.group("list")), \
        f"{path} {name}: depends_on must include module.{owner}, the owner of the private endpoints"
