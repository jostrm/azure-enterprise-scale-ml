"""The parity map (terraform/parity_map.json) covers every resource type the 11/12/13 Bicep closure deploys.

Each Bicep `resource '<type>@<apiVersion>'` that is not `existing` must be mapped, and the mapping must be
implemented: an azurerm resource of the named type, or an azapi_resource with exactly that ARM type and API
version, in the named modules. Every Bicep file of the closure maps to a Terraform module, every Terraform
module is reachable from the root, and no azapi type is used without an entry. Nothing is skipped silently.
"""
from __future__ import annotations

import json
import re

from harness import BICEP_DIR, MODULES, PARITY_MAP, ROOT_MODULE, TERRAFORM_DIR, deployed_resource_types, module_closure

PARITY = json.loads(PARITY_MAP.read_text(encoding="utf-8"))


def module_text(module: str) -> str:
    folder = TERRAFORM_DIR / module
    assert folder.is_dir(), f"{module} does not exist"
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.tf")))


def module_sources(folder) -> set:
    text = "\n".join(path.read_text(encoding="utf-8") for path in folder.glob("*.tf"))
    return {(folder / source).resolve() for source in re.findall(r'^\s*source\s*=\s*"(\.[^"]+)"', text, re.M)}


def reachable_modules() -> set:
    seen, queue = set(), [ROOT_MODULE.resolve()]
    while queue:
        folder = queue.pop()
        for child in module_sources(folder):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def test_every_deployed_bicep_resource_type_is_mapped_and_nothing_else():
    deployed = deployed_resource_types()
    mapped = PARITY["types"]
    assert sorted(set(deployed) - set(mapped)) == [], "unmapped Bicep resource types"
    assert sorted(set(mapped) - set(deployed)) == [], "parity map entries no Bicep file of the closure deploys"
    assert len(deployed) >= 40


def test_every_mapping_is_implemented_in_its_modules():
    for arm_type, entry in PARITY["types"].items():
        assert entry["provider"] in ("azurerm", "azapi"), arm_type
        assert entry["terraform"] and entry["modules"], arm_type
        texts = {module: module_text(module) for module in entry["modules"]}
        if entry["provider"] == "azapi":
            assert entry["terraform"] in (["azapi_resource"], ["azapi_update_resource"]), arm_type
        else:
            assert all(name.startswith("azurerm_") or name == "azapi_resource" for name in entry["terraform"]), arm_type
            assert entry["terraform"][0].startswith("azurerm_"), f"{arm_type}: an azurerm entry leads with azurerm"
        azapi = [name for name in entry["terraform"] if name.startswith("azapi_")]
        if azapi:
            assert entry["reason"].strip(), f"{arm_type}: say why azapi"
            assert any(re.search(r'type\s*=\s*"' + re.escape(arm_type) + '"', text) for text in texts.values()), \
                f"no azapi_resource of type {arm_type} in {entry['modules']}"
        for module, text in texts.items():
            implemented = [name for name in entry["terraform"]
                           if (name.startswith("azapi_") and f'resource "{name}"' in text
                               and re.search(r'type\s*=\s*"' + re.escape(arm_type) + '"', text))
                           or (name.startswith("azurerm_") and f'resource "{name}"' in text)]
            assert implemented, f"{module} implements none of {entry['terraform']} for {arm_type}"
        for name in entry["terraform"]:
            if name.startswith("azurerm_"):
                assert any(f'resource "{name}"' in text for text in texts.values()), (arm_type, name)


def test_every_azapi_type_used_by_the_port_is_documented():
    documented = set(PARITY["types"]) | set(PARITY.get("terraform_only", {}))
    for path in sorted(MODULES.rglob("*.tf")):
        for arm_type in re.findall(r'^\s*type\s*=\s*"([A-Za-z.]+/[^"@]+@[^"]+)"', path.read_text(encoding="utf-8"), re.M):
            assert arm_type in documented, f"{path.relative_to(TERRAFORM_DIR)} uses undocumented {arm_type}"
    for arm_type, entry in PARITY.get("terraform_only", {}).items():
        assert entry["reason"].strip() and entry["modules"], arm_type


def test_every_bicep_file_of_the_closure_has_a_terraform_module():
    closure = sorted(path.relative_to(BICEP_DIR).as_posix() for path in module_closure())
    files = PARITY["files"]
    assert sorted(set(closure) - set(files)) == [], "Bicep files without a Terraform module"
    assert sorted(set(files) - set(closure)) == [], "parity map files outside the closure"
    reachable = reachable_modules()
    for bicep_file, module in files.items():
        folder = (TERRAFORM_DIR / module).resolve()
        assert folder.is_dir(), f"{bicep_file} -> {module} does not exist"
        if bicep_file.startswith("esml-common/main/"):
            continue
        assert folder in reachable, f"{module} ({bicep_file}) is not reachable from the root module"
        assert bicep_file in (folder / "main.tf").read_text(encoding="utf-8"), \
            f"{module}/main.tf does not name {bicep_file} in its header"


def test_every_terraform_module_is_used():
    reachable = reachable_modules()
    unused = sorted(path.name for path in MODULES.iterdir() if path.is_dir() and path.resolve() not in reachable)
    assert unused == [], f"modules nothing calls: {unused}"
