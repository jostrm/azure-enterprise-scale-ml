"""Read-only runner planning and explicitly approved provisioning in an EXISTING common RG.

This is not lifecycle enrollment: it never publishes a binding, edits configuration,
changes CLI defaults, dispatches a workflow, or calls the full-factory bootstrap.
Public APIs: read_config, selected_values, load_request, plan, ensure_vm.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4
from urllib.parse import quote

from factory_enrollment import (
    ADO_AUDIENCE, Cloud, EnrollmentError, canonical, guid, parse_json, require,
)

LIB = Path(__file__).resolve().parent
FLAGS = ("useSelfHostedBuildAgent", "USE_SELF_HOSTED_BUILD_AGENT")
FORMATS = ("variables.yaml", "variables.yml", "variables.json", ".env")
ENVIRONMENTS = {"dev": "dev", "stage": "test", "prod": "prod"}
COMPUTE_API = "2024-03-01"
DISK_API = "2024-03-02"
NETWORK_API = "2023-11-01"
TAGS_API = "2021-04-01"
SIZE = "Standard_D4s_v5"
IMAGE = {"publisher": "Canonical", "offer": "ubuntu-24_04-lts", "sku": "server", "version": "latest"}


def scalar(text):
    text = text.strip()
    if text.startswith('"'):
        decoder = json.JSONDecoder()
        try:
            value, end = decoder.raw_decode(text)
        except ValueError:
            raise EnrollmentError("invalid-quoted-config-value") from None
        require(not text[end:].strip() or text[end:].lstrip().startswith("#"), "invalid-config-comment")
        return value
    if text.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", text)
        require(match, "invalid-quoted-config-value")
        return match[1].replace("''", "'")
    text = re.split(r"\s+#", text, maxsplit=1)[0].strip()
    require(not text.startswith(("[", "{", "&", "*", "!", "|", ">")), "unsupported-config-syntax")
    return text


def read_config(path):
    """Parse data, never source/eval it. YAML supports literal mappings and named variables."""
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8 * 1024 * 1024,
            "ordinary-bounded-config-file-required")
    for parent in (path, *path.parents):
        require(not parent.is_symlink() and not getattr(parent.lstat(), "st_file_attributes", 0) & 0x400,
                "config-symlinks-or-junctions-forbidden")
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        value = parse_json(text)
        require(isinstance(value, dict), "config-object-required")
        return value
    result = {}
    if path.name == ".env":
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
            require(match and match[1] not in result, "invalid-or-duplicate-env-assignment")
            result[match[1]] = scalar(match[2])
        return result
    require(path.suffix.lower() in (".yaml", ".yml"), "unsupported-config-format")
    stack = [(-1, result)]
    child_indents = {id(result): 0}
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
             and line.strip() not in ("---", "...")]
    skip_value = False
    for index, line in enumerate(lines):
        if skip_value:
            skip_value = False
            continue
        require("\t" not in line[:len(line) - len(line.lstrip())], "yaml-tabs-forbidden")
        named = re.fullmatch(r"( *)-\s+name:\s+(.+)", line)
        if named:
            require(index + 1 < len(lines), "yaml-named-variable-value-required")
            value = re.fullmatch(r"( *)value:(?:\s+(.*)|\s*)", lines[index + 1])
            require(value and len(value[1]) == len(named[1]) + 2, "yaml-named-variable-value-required")
            key, raw, indent = scalar(named[2]), value[2], len(named[1])
            require(isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", key),
                    "invalid-yaml-variable-name")
            if indent == stack[-1][0]:
                indent += 2
            skip_value = True
        else:
            match = re.fullmatch(r"""( *)([A-Za-z_][A-Za-z0-9_.-]*|'[A-Za-z_][A-Za-z0-9_.-]*'|"[A-Za-z_][A-Za-z0-9_.-]*"):(?:\s+(.*)|\s*)""", line)
            require(match, "unsupported-or-malformed-yaml-mapping")
            indent, key, raw = len(match[1]), scalar(match[2]), match[3]
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        require(indent == child_indents.setdefault(id(parent), indent), "inconsistent-yaml-indentation")
        require(key not in parent, "duplicate-yaml-key")
        if raw is None or not raw.strip() or raw.lstrip().startswith("#"):
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            parent[key] = scalar(raw)
    return result


def selected_values(document, environment):
    """Only shared/root and the selected environment, never sibling project/factory scopes."""
    require(environment in ENVIRONMENTS and isinstance(document, dict), "invalid-selected-scope")
    result = []
    for key in FLAGS:
        require(key not in document or not isinstance(document[key], (dict, list)), "invalid-self-hosted-flag")
    def contains_flag(value):
        if isinstance(value, list):
            return any(contains_flag(x) for x in value)
        return isinstance(value, dict) and (any(key in value for key in FLAGS)
                                           or any(contains_flag(x) for x in value.values()))
    known = {"variables", "common", "shared", "environments", "dev", "stage_prod", "stage", "test", "prod"}
    require(not any(contains_flag(value) for key, value in document.items() if key not in known),
            "ambiguous-config-target-scope")
    flat = {key: value for key, value in document.items() if not isinstance(value, (dict, list))}
    result.append(flat)
    for key in ("variables", "common", "shared", "environments",
                *(("dev",) if environment == "dev" else ("stage_prod", environment))):
        if key in document:
            require(isinstance(document[key], dict), "config-scope-must-be-object")
            result.extend(selected_values(document[key], environment))
    if environment == "stage" and "test" in document:
        require("stage" not in document, "ambiguous-stage-test-config")
        result.extend(selected_values(document["test"], environment))
    return result


def requested(sources):
    values = []
    for source in sources:
        for key in FLAGS:
            if key in source:
                value = source[key]
                require(type(value) is bool or isinstance(value, str)
                        and value.strip().lower() in ("true", "false"), "invalid-self-hosted-flag")
                values.append(value is True or isinstance(value, str) and value.strip().lower() == "true")
    return any(values)


def pick(sources, *keys, default=None):
    values = [str(source[key]).strip() for source in sources for key in keys
              if key in source and source[key] not in ("", None)]
    require(len(set(values)) <= 1, "conflicting-selected-config-" + keys[0].lower().replace("_", "-"))
    return values[0] if values else default


def literal(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.()-]+", value)
            and value not in (".", ".."), "literal-" + label + "-required")
    return value


def consumer_root(root):
    root = Path(root).absolute()
    for parent in (root, *root.parents):
        if (parent / "azurefactory" / "register.json").exists() or (parent / "azurefactory" / "register.json").is_symlink():
            root = parent
            break
        if parent.name == "azurefactory" and ((parent / "register.json").exists() or (parent / "register.json").is_symlink()):
            root = parent.parent
            break
    return root.resolve()


def config_sources(root, source=None):
    root = Path(root).resolve()
    directories = [root, root / "aifactory",
                   root / "aifactory" / "esml-infra" / "azure-devops" / "bicep" / "yaml" / "variables"]
    if source:
        source = Path(source).resolve()
        require(source.is_relative_to(root) and source.name in FORMATS, "config-source-outside-selected-root")
        require(source.is_file(), "exact-config-source-required")
        # An explicit nonstandard scope must not accidentally include unrelated factory files.
        if source.parent not in directories:
            directories = [source.parent]
    paths = list(dict.fromkeys(directory / name for directory in directories for name in FORMATS
                               if (directory / name).exists() or (directory / name).is_symlink()))
    return paths


def load_request(root, provider, environment="dev", config_source=None, factory_id=None,
                 scale_set_id=None, repository=None, ado_organization=None, ado_tenant=None,
                 pool=None, agent_name=None, runner_label=None, vm_os=None, vm_name=None,
                 common_rg=None, subnet_id=None, separate_github=False, prereqs_only=False,
                 environ=None):
    root = consumer_root(root)
    require(provider in ("ado", "gha") and environment in ENVIRONMENTS, "invalid-runner-scope")
    require(not separate_github or provider == "gha", "separate-github-requires-gha-provider")
    env = os.environ if environ is None else environ
    register = root / "azurefactory" / "register.json"
    sources, fingerprints = [], {}
    selected = None
    registered = register.exists() or register.is_symlink()
    if registered:
        require(factory_id and scale_set_id, "factory-id-and-scale-set-id-required")
        document = read_config(register)
        require(document.get("schema_version") == 2, "consumer-schema-2-required")
        factories = [x for x in document.get("factories", []) if x.get("id") == guid(factory_id)]
        require(len(factories) == 1, "exact-registered-factory-required")
        factory = factories[0]
        scales = [x for x in factory.get("scale_sets", []) if x.get("id") == guid(scale_set_id)]
        require(len(scales) == 1, "exact-registered-scaleset-required")
        selected = scales[0]
        require(selected.get("environment") == environment, "registered-environment-mismatch")
        require(selected.get("orchestrator") == provider or provider == "gha" and separate_github,
                "registered-orchestrator-mismatch")
        fingerprints[str(register)] = hashlib.sha256(register.read_bytes()).hexdigest()
        configuration = document.get("configurations", {}).get(factory["id"], {})
        if "factory" in configuration or "scale_sets" in configuration:
            effective = {**configuration.get("factory", {}),
                         **configuration.get("scale_sets", {}).get(scale_set_id, {})}
            # Typed registers own placement; factory defaults can retain template placeholders.
            effective.update(
                tenantId=selected["tenant_id"],
                admin_location=factory["region"],
                admin_aifactoryPrefixRG=factory["prefix"].rstrip("-") + "-",
                admin_aifactorySuffixRG="-" + selected["suffix"],
            )
            effective[{"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}[environment]] = selected["subscription_id"]
            sources.extend(selected_values(effective, environment))
        variables = configuration.get("variables", {})
        require(isinstance(variables, dict), "invalid-registered-variables")
        # Register schema-2 variables may be keyed by exact scale-set UUID.
        if scale_set_id in variables:
            sources.extend(selected_values(variables[scale_set_id], environment))
        elif all(not isinstance(v, dict) for v in variables.values()) or any(
                key in variables for key in ("dev", "stage_prod", "stage", "prod", "variables", "environments")):
            sources.extend(selected_values(variables, environment))
        elif variables:
            require(config_source, "ambiguous-registered-variables-select-config-source")
        binding = document.get("bindings", {}).get(factory["id"], {}).get(provider, {})
        if repository and binding.get("repository") and not separate_github:
            require(repository.removeprefix("https://github.com/").removesuffix(".git") ==
                    binding["repository"].removeprefix("https://github.com/").removesuffix(".git"),
                    "registered-repository-mismatch")
        if not repository and provider == "gha" and binding:
            repository = binding.get("repository")
        if provider == "ado" and binding.get("repository"):
            match = re.match(r"(https://dev\.azure\.com/[A-Za-z0-9_-]+)/", binding["repository"])
            require(match, "invalid-registered-ado-repository")
            require(not ado_organization or ado_organization.rstrip("/") == match[1], "registered-organization-mismatch")
            ado_organization = match[1]
        if not config_source:
            require(any(any(key in source for key in (*FLAGS, "tenantId", "admin_aifactoryPrefixRG", "TENANT_ID"))
                        for source in sources), "registered-config-source-required")
    else:
        require(not factory_id and not scale_set_id, "register-required-for-selected-ids")
        require(config_source, "legacy-requires-exact-config-source")
    paths = config_sources(root, config_source) if not registered or config_source else []
    for path in paths:
        sources.extend(selected_values(read_config(path), environment))
        fingerprints[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    # The process environment can request self-hosting; it cannot silently retarget Azure.
    desired = requested([*sources, {key: env[key] for key in FLAGS if key in env}])
    request = {"desired": desired, "provider": provider, "environment": environment,
               "root": str(root), "fingerprints": fingerprints, "prereqs_only": prereqs_only}
    if not desired:
        return request
    subscription_key = {"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}[environment]
    tenant = pick(sources, "tenantId", "TENANT_ID", "AIF_TENANT_ID")
    subscription = pick(sources, subscription_key, "AZURE_SUBSCRIPTION_ID",
                        {"dev": "DEV_SUBSCRIPTION_ID", "stage": "STAGE_SUBSCRIPTION_ID",
                         "prod": "PROD_SUBSCRIPTION_ID"}[environment],
                        {"dev": "AIF_DEV_SUBSCRIPTION_ID", "stage": "AIF_STAGE_SUBSCRIPTION_ID",
                         "prod": "AIF_PROD_SUBSCRIPTION_ID"}[environment])
    location = pick(sources, "admin_location", "AIFACTORY_LOCATION", "AIF_LOCATION")
    prefix = pick(sources, "admin_aifactoryPrefixRG", "AIFACTORY_PREFIX", "AIF_PREFIX")
    suffix = pick(sources, "admin_aifactorySuffixRG", "AIFACTORY_SUFFIX", "AIF_SCALESET_SUFFIX")
    if selected:
        for value, expected in ((tenant, selected.get("tenant_id")), (subscription, selected.get("subscription_id")),
                                (location, factory.get("region"))):
            require(value is None or value.lower() == str(expected).lower(), "config-register-placement-mismatch")
        tenant, subscription, location = selected["tenant_id"], selected["subscription_id"], factory["region"]
        require(prefix is None or prefix.rstrip("-") == factory["prefix"].rstrip("-"), "config-register-prefix-mismatch")
        require(suffix is None or suffix.lstrip("-") == selected["suffix"], "config-register-suffix-mismatch")
        prefix, suffix = prefix or factory["prefix"].rstrip("-") + "-", suffix or "-" + selected["suffix"]
    tenant, subscription = guid(tenant), guid(subscription)
    location = literal(location, "location").lower()
    short = pick(sources, "admin_locationSuffix", "AIFACTORY_LOCATION_SHORT", "AIF_LOCATION_SHORT")
    literal(short, "location-short")
    literal(prefix, "factory-prefix")
    require(isinstance(suffix, str) and re.fullmatch(r"-?[0-9]{3}", suffix), "literal-scaleset-suffix-required")
    suffix = "-" + suffix.lstrip("-")
    azure_env = ENVIRONMENTS[environment]
    expected_rg = pick(sources, "commonResourceGroup_param", "COMMON_RESOURCE_GROUP_PARAM",
                       default=f"{prefix}esml-common-{short}-{azure_env}{suffix}")
    common_rg = common_rg or expected_rg
    require(common_rg.casefold() == expected_rg.casefold(), "common-resource-group-mismatch")
    literal(common_rg, "common-resource-group")
    rg_id = f"/subscriptions/{subscription}/resourceGroups/{common_rg}"
    network_env = pick(sources, "network_env_" + environment, "NETWORK_ENV_" + environment.upper(), default=azure_env + "-")
    vnet_rg = pick(sources, "vnetResourceGroup_param", "VNET_RESOURCE_GROUP_PARAM", default=common_rg).replace("<network_env>", network_env)
    vnet_name = pick(sources, "vnetNameFull_param", "VNET_NAME_FULL_PARAM")
    if not vnet_name:
        vnet_base = pick(sources, "vnetNameBase", "VNET_NAME_BASE", default="vnt-esmlcmn")
        common_suffix = pick(sources, "admin_commonResourceSuffix", "ADMIN_COMMON_RESOURCE_SUFFIX", default="-001")
        vnet_name = f"{vnet_base}-{short}-{azure_env}{common_suffix}"
    vnet_name = vnet_name.replace("<network_env>", network_env)
    byo = pick(sources, "BYO_subnets", "BYO_SUBNETS", default="false").lower()
    require(byo in ("true", "false"), "invalid-byo-subnets-flag")
    subnet_name = (pick(sources, "subnetCommon", "SUBNET_COMMON") if byo == "true" else
                   pick(sources, "common_subnet_name", "COMMON_SUBNET_NAME", default="snet-esml-cmn-001"))
    require(subnet_name, "selected-common-subnet-required")
    subnet_name = subnet_name.replace("<network_env>", network_env)
    network_subscription = pick(sources, "vnetSubscriptionId", "VNET_SUBSCRIPTION_ID", default=subscription)
    expected_subnet = (f"/subscriptions/{guid(network_subscription)}/resourceGroups/{literal(vnet_rg, 'vnet-rg')}"
                       f"/providers/Microsoft.Network/virtualNetworks/{literal(vnet_name, 'vnet')}"
                       f"/subnets/{literal(subnet_name, 'subnet')}")
    require(not subnet_id or subnet_id.casefold() == expected_subnet.casefold(), "selected-subnet-mismatch")
    subnet_id = expected_subnet
    vm_os = vm_os or pick(sources, "AIF_RUNNER_OS", "AIF_RUNNER_VM_OS")
    vm_os = (vm_os or ("linux" if provider == "gha" or registered else "windows")).lower()
    require(vm_os in ("linux", "windows"), "supported-vm-os-required")
    # Runner-only separate GHA setup is not a lifecycle binding; scoped contracts remain Linux.
    require(not registered or separate_github or vm_os == "linux", "linux-scoped-runner-required")
    default_name = (f"dsvm-cmn-{short}-{azure_env}-001" if vm_os == "windows" else
                    f"runner-{provider}-{short}-{azure_env}{suffix}")
    vm_name = vm_name or pick(sources, "AIF_RUNNER_VM_NAME") or default_name
    require(re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", vm_name), "invalid-runner-vm-name")
    legacy_windows = not registered and vm_os == "windows" and vm_name == default_name
    repository = (repository or pick(sources, "GITHUB_REPOSITORY", "GITHUB_NEW_REPO")) if provider == "gha" else None
    if provider == "gha" and not repository and not prereqs_only:
        remote = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                                capture_output=True, text=True, check=False)
        if remote.returncode == 0:
            match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?",
                                remote.stdout.strip())
            repository = match[1] if match else None
    if repository:
        repository = repository.removeprefix("https://github.com/").removesuffix(".git")
        require(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*", repository),
                "explicit-github-repository-required")
    organization = (ado_organization or pick(sources, "ADO_ORGANIZATION")) if provider == "ado" and not prereqs_only else None
    if organization:
        require(re.fullmatch(r"https://dev\.azure\.com/[A-Za-z0-9_-]+", organization.rstrip("/")),
                "explicit-ado-organization-required")
        organization = organization.rstrip("/")
    ado_tenant = (ado_tenant or pick(sources, "azureDevOpsTenantId", "ADO_TENANT", "ADO_TENANT_ID")) if provider == "ado" and not prereqs_only else None
    pool = (pool or pick(sources, "adminVMBuildAgentPool", "ADO_AGENT_POOL", default="Default")) if provider == "ado" else "Default"
    name = agent_name or pick(sources, "GHA_RUNNER_NAME" if provider == "gha" else "adminVMBuildAgentName",
                             *(() if provider == "gha" else ("ADO_AGENT_NAME",)), default=vm_name)
    label = (runner_label or pick(sources, "selfHostedRunnerLabel", "GHA_RUNNER_LABEL", default=f"{prefix}aifactory{suffix}")) if provider == "gha" else "unused"
    for value in (pool, name, label):
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}", value), "invalid-runner-registration-name")
    if not prereqs_only:
        require(repository if provider == "gha" else organization and ado_tenant,
                "provider-scope-required-or-select-prereqs-only")
    owner = hashlib.sha256(canonical([tenant, rg_id.lower(), vm_name.lower(), provider])).hexdigest()[:32]
    request.update(target={"tenant_id": tenant, "subscription_id": subscription},
                   common_rg=common_rg, rg_id=rg_id, subnet=subnet_id, location=location,
                   vm_os=vm_os, vm_name=vm_name, vm_id=rg_id + "/providers/Microsoft.Compute/virtualMachines/" + vm_name,
                   size=SIZE, legacy_windows=legacy_windows, repository=repository,
                   ado_organization=organization, ado_tenant_id=guid(ado_tenant) if ado_tenant else None,
                   pool=pool, agent_name=name, runner_label=label,
                   tags={"aifactory-runner-owner": owner, "aifactory-runner-provider": provider})
    return request


def fresh(request):
    for path, digest in request["fingerprints"].items():
        require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, "selected-config-changed-replan")


def get(cloud, identifier, version):
    status, _, value = cloud.arm("GET", identifier, version, allowed=(200, 404))
    if status == 404:
        require(isinstance(value, dict) and isinstance(value.get("error"), dict)
                and value["error"].get("code") in ("ResourceNotFound", "ResourceGroupNotFound", "NotFound"),
                "unverified-resource-absence")
        return None
    require(status == 200, "resource-read-failed-not-absence")
    require(isinstance(value, dict) and str(value.get("id", "")).lower() == identifier.split("?")[0].lower(),
            "unexpected-resource-identity")
    return value


def tag_values(resource):
    tags = resource.get("tags") or {}
    require(isinstance(tags, dict) and all(isinstance(k, str) for k in tags), "invalid-resource-tags")
    require(len({key.lower() for key in tags}) == len(tags), "ambiguous-resource-tags")
    return {key.lower(): value for key, value in tags.items()}


def owned(request, resource, identifier):
    require(resource and str(resource.get("id", "")).lower() == identifier.lower()
            and resource.get("location", "").replace(" ", "").lower() == request["location"],
            "runner-resource-identity-or-location-mismatch")
    require(all(tag_values(resource).get(k) == v for k, v in request["tags"].items()),
            "runner-resource-ownership-conflict")
    require(resource.get("properties", {}).get("provisioningState") == "Succeeded",
            "runner-resource-not-ready-inspect-before-retry")


def resource_ids(request):
    base = request["rg_id"] + "/providers/Microsoft.Network/"
    return {"nsg": base + "networkSecurityGroups/" + request["vm_name"] + "-nsg",
            "nic": base + "networkInterfaces/" + request["vm_name"] + "-nic",
            "disk": request["rg_id"] + "/providers/Microsoft.Compute/disks/" + request["vm_name"] + "-os"}


def validate_nic(request, nic, *, managed=True):
    ids = resource_ids(request)
    if managed:
        owned(request, nic, ids["nic"])
        require(nic["properties"].get("networkSecurityGroup", {}).get("id", "").lower() == ids["nsg"].lower(),
                "runner-nsg-mismatch")
    configs = nic.get("properties", {}).get("ipConfigurations", [])
    require(len(configs) == 1 and configs[0].get("properties", {}).get("subnet", {}).get("id", "").lower()
            == request["subnet"].lower() and not configs[0]["properties"].get("publicIPAddress"),
            "runner-network-or-public-ip-mismatch")


def snapshot(request, cloud):
    fresh(request)
    account = cloud.az("account", "show", "--subscription", request["target"]["subscription_id"])
    require(str(account.get("tenantId", "")).lower() == request["target"]["tenant_id"]
            and str(account.get("id", "")).lower() == request["target"]["subscription_id"]
            and account.get("state") == "Enabled", "azure-account-target-mismatch")
    subnet_subscription = request["subnet"].split("/")[2]
    if subnet_subscription != request["target"]["subscription_id"]:
        network_account = cloud.az("account", "show", "--subscription", subnet_subscription)
        require(str(network_account.get("tenantId", "")).lower() == request["target"]["tenant_id"]
                and str(network_account.get("id", "")).lower() == subnet_subscription
                and network_account.get("state") == "Enabled", "subnet-subscription-tenant-mismatch")
    group = get(cloud, request["rg_id"], TAGS_API)
    require(group and group.get("location", "").replace(" ", "").lower() == request["location"],
            "existing-common-resource-group-location-required")
    subnet = get(cloud, request["subnet"], NETWORK_API)
    require(subnet and subnet.get("properties", {}).get("provisioningState") == "Succeeded", "existing-common-subnet-required")
    vnet = get(cloud, request["subnet"].rsplit("/subnets/", 1)[0], NETWORK_API)
    require(vnet and vnet.get("location", "").replace(" ", "").lower() == request["location"], "subnet-location-mismatch")
    vm = get(cloud, request["vm_id"], COMPUTE_API)
    ids = resource_ids(request)
    resources = {key: get(cloud, value, DISK_API if key == "disk" else NETWORK_API) for key, value in ids.items()}
    if vm:
        props = vm.get("properties", {})
        require(vm.get("location", "").replace(" ", "").lower() == request["location"]
                and props.get("storageProfile", {}).get("osDisk", {}).get("osType", "").lower() == request["vm_os"],
                "existing-vm-os-or-location-mismatch")
        if not request["legacy_windows"]:
            owned(request, vm, request["vm_id"])
            require(props.get("hardwareProfile", {}).get("vmSize") == SIZE
                    and vm.get("identity", {}).get("type", "None") == "None", "existing-runner-size-or-identity-mismatch")
        else:
            require(not any(key in tag_values(vm) and tag_values(vm)[key] != value
                            for key, value in request["tags"].items()), "existing-windows-owner-conflict")
        nics = props.get("networkProfile", {}).get("networkInterfaces", [])
        require(len(nics) == 1, "single-selected-runner-nic-required")
        nic_id = nics[0].get("id", "")
        require(nic_id.lower().startswith(request["rg_id"].lower() + "/providers/microsoft.network/networkinterfaces/"),
                "runner-nic-outside-common-group")
        nic = get(cloud, nic_id, NETWORK_API)
        validate_nic(request, nic, managed=not request["legacy_windows"])
        _, _, view = cloud.arm("GET", request["vm_id"] + "/instanceView", COMPUTE_API)
        require(any(item.get("code") == "PowerState/running" for item in view.get("statuses", [])),
                "runner-vm-not-running-no-automatic-start-or-restart")
    else:
        require(request["vm_os"] == "linux", "existing-windows-vm-required-no-replacement")
    if not request["legacy_windows"]:
        if resources["nsg"]:
            owned(request, resources["nsg"], ids["nsg"])
            rules = resources["nsg"]["properties"].get("securityRules", [])
            require(len(rules) == 1 and all(rules[0].get("properties", {}).get(k) == v for k, v in deny_inbound().items()),
                    "runner-inbound-policy-mismatch")
        if resources["nic"]:
            validate_nic(request, resources["nic"])
            attachment = resources["nic"]["properties"].get("virtualMachine", {}).get("id")
            require(not attachment or attachment.lower() == request["vm_id"].lower(), "runner-nic-already-attached")
        if resources["disk"]:
            disk = resources["disk"]
            require(vm and disk.get("managedBy", "").lower() == request["vm_id"].lower()
                    and props["storageProfile"]["osDisk"].get("managedDisk", {}).get("id", "").lower() == ids["disk"].lower()
                    and disk.get("sku", {}).get("name") == "StandardSSD_LRS"
                    and disk.get("properties", {}).get("diskSizeGB") == 128, "runner-disk-conflict")
            require(not any(key in tag_values(disk) and tag_values(disk)[key] != value
                            for key, value in request["tags"].items()), "runner-disk-ownership-conflict")
        require(not vm or resources["disk"] and resources["nsg"], "runner-created-resource-inventory-incomplete")
    return {"vm": vm, **resources}


def deny_inbound():
    return {"protocol": "*", "sourcePortRange": "*", "destinationPortRange": "*",
            "sourceAddressPrefix": "*", "destinationAddressPrefix": "*", "access": "Deny",
            "priority": 100, "direction": "Inbound"}


def provider_action(request, cloud, *, require_online=False, allow_pool_create=False):
    if request["prereqs_only"]:
        return "noop"
    if request["provider"] == "gha":
        rows = []
        for page in range(1, 101):
            _, _, value = cloud.gh("GET", f"repos/{request['repository']}/actions/runners?per_page=100&page={page}")
            require(isinstance(value.get("runners"), list), "invalid-provider-runner-inventory")
            rows.extend(value["runners"])
            if len(value["runners"]) < 100:
                break
        else:
            raise EnrollmentError("incomplete-provider-runner-inventory")
        matches = [x for x in rows if x.get("name") == request["agent_name"]]
        require(len(matches) <= 1, "ambiguous-provider-runner")
        if matches:
            runner = matches[0]
            require(request["runner_label"] in [x.get("name") for x in runner.get("labels", [])]
                    and runner.get("os", "").lower() == request["vm_os"], "existing-provider-runner-mismatch")
            require(not runner.get("busy"), "runner-busy-retry-without-interruption")
            if require_online and runner.get("status") != "online":
                return "offline"
    else:
        prefix = request["ado_organization"] + "/_apis/distributedtask/"
        def ado(endpoint):
            _, headers, value = cloud.http("GET", prefix + endpoint, ADO_AUDIENCE,
                                           tenant=request["ado_tenant_id"])
            require(not headers.get("x-ms-continuationtoken"), "incomplete-provider-runner-inventory")
            require(isinstance(value.get("value"), list), "invalid-provider-runner-inventory")
            return value["value"]
        pools = [x for x in ado("pools?poolName=" + quote(request["pool"], safe="") + "&actionFilter=manage&api-version=7.1")
                 if x.get("name") == request["pool"]]
        if not pools and allow_pool_create:
            visible = ado("pools?poolName=" + quote(request["pool"], safe="") + "&api-version=7.1")
            require(not visible, "existing-pool-not-manageable")
            return "create-pool-and-register"
        require(len(pools) == 1 and not pools[0].get("isHosted"), "exact-manageable-self-hosted-pool-required")
        matches = [x for x in ado(f"pools/{pools[0]['id']}/agents?agentName=" +
                                  quote(request["agent_name"], safe="") +
                                  "&includeCapabilities=true&includeAssignedRequest=true&api-version=7.1")
                   if x.get("name") == request["agent_name"]]
        require(len(matches) <= 1, "ambiguous-provider-runner")
        if matches:
            require(matches[0].get("enabled") and not matches[0].get("assignedRequest"), "runner-disabled-or-busy")
            actual_os = matches[0].get("systemCapabilities", {}).get("Agent.OS")
            require(actual_os == ("Linux" if request["vm_os"] == "linux" else "Windows_NT"),
                    "existing-provider-runner-os-mismatch")
            if require_online and matches[0].get("status") != "online":
                return "offline"
    return "reuse" if matches else "create"


def plan(request, cloud=None, *, allow_pool_create=False):
    if not request["desired"]:
        return {"desired": False, "status": "skipped-not-requested", "actions": {"vm": "noop", "agent": "noop"}}
    cloud = cloud or Cloud(request)
    cloud.read_only = True
    state = snapshot(request, cloud)
    agent_action = provider_action(request, cloud, allow_pool_create=allow_pool_create)
    require(state["vm"] or agent_action != "reuse", "existing-agent-without-matching-vm-no-takeover")
    result = {key: request[key] for key in ("desired", "provider", "environment", "common_rg", "subnet",
                                          "vm_os", "vm_name", "size", "location")}
    result.update(status="planned", agent_ready=False,
                  actions={"vm": "reuse" if state["vm"] else "create", "prerequisites": "verify-install-missing",
                           "agent": agent_action},
                  no_public_ip=True, managed_identity="none-on-new-vm", os_disk_gb=128,
                  os_disk_sku="StandardSSD_LRS")
    if state["vm"] and request["vm_os"] == "windows":
        properties = state["vm"]["properties"]
        disk = properties["storageProfile"]["osDisk"]
        result.update(size=properties.get("hardwareProfile", {}).get("vmSize"),
                      os_disk_gb=disk.get("diskSizeGB"),
                      os_disk_sku=disk.get("managedDisk", {}).get("storageAccountType"),
                      managed_identity="unchanged-existing-vm")
    return result


def ensure_provider_pool(request, cloud, *, project=None):
    if request["provider"] != "ado":
        return
    action = provider_action(request, cloud, allow_pool_create=True)
    prefix = request["ado_organization"] + "/_apis/distributedtask/"
    cloud.read_only = False
    if action == "create-pool-and-register":
        cloud.http("POST", prefix + "pools?api-version=7.1", ADO_AUDIENCE,
                   {"name": request["pool"], "autoProvision": False, "autoUpdate": True, "poolType": "automation"},
                   tenant=request["ado_tenant_id"], allowed=(200, 201))
    _, headers, value = cloud.http("GET", prefix + "pools?poolName=" + quote(request["pool"], safe="") +
                                  "&actionFilter=manage&api-version=7.1", ADO_AUDIENCE, tenant=request["ado_tenant_id"])
    require(not headers.get("x-ms-continuationtoken"), "complete-pool-inventory-required")
    pools = [item for item in value["value"] if item.get("name") == request["pool"] and not item.get("isHosted")]
    require(len(pools) == 1, "created-pool-not-verified")
    require(isinstance(project, str) and bool(project.strip()), "exact-agent-project-required")
    endpoint = request["ado_organization"] + "/" + quote(project, safe="") + "/_apis/distributedtask/queues"
    _, headers, value = cloud.http("GET", endpoint + "?queueName=" + quote(request["pool"], safe="") + "&api-version=7.1",
                                  ADO_AUDIENCE, tenant=request["ado_tenant_id"])
    require(not headers.get("x-ms-continuationtoken"), "complete-queue-inventory-required")
    require(all(item.get("pool", {}).get("id") == pools[0]["id"] for item in value["value"]), "existing-agent-queue-conflict")
    if not value["value"]:
        cloud.http("POST", endpoint + "?api-version=7.1", ADO_AUDIENCE,
                   {"name": request["pool"], "pool": {"id": pools[0]["id"]}},
                   tenant=request["ado_tenant_id"], allowed=(200, 201))
    _, _, value = cloud.http("GET", endpoint + "?queueName=" + quote(request["pool"], safe="") + "&api-version=7.1",
                            ADO_AUDIENCE, tenant=request["ado_tenant_id"])
    require(len(value["value"]) == 1 and value["value"][0].get("pool", {}).get("id") == pools[0]["id"],
            "created-agent-queue-not-verified")


def wait_resource(cloud, identifier, version):
    for _ in range(180):
        value = get(cloud, identifier, version)
        state = (value or {}).get("properties", {}).get("provisioningState")
        if state == "Succeeded":
            return value
        require(state not in ("Failed", "Canceled"), "runner-provisioning-failed-inspect-before-retry")
        time.sleep(10)
    raise EnrollmentError("runner-provisioning-timeout-inspect-before-retry")


def create_absent(cloud, identifier, version, body):
    require(get(cloud, identifier, version) is None, "resource-appeared-replan-no-overwrite")
    cloud.arm("PUT", identifier, version, data=body, allowed=(200, 201, 202))
    return wait_resource(cloud, identifier, version)


def protect_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name == "nt":
        who = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader(io.StringIO(who.strip())))[1]
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F",
                        "*S-1-5-18:(OI)(CI)F"], check=True, stdout=subprocess.DEVNULL)


def ensure_vm(request, *, yes=False, cloud=None, ssh_public_key=None):
    require(yes, "runner-ensure-requires-yes")
    if not request["desired"]:
        return None
    cloud = cloud or Cloud(request)
    state = snapshot(request, cloud)
    cloud.read_only, cloud.serialized_provisioning = False, True
    ids = resource_ids(request)
    if not state["vm"]:
        body = {"location": request["location"], "tags": request["tags"]}
        key_directory = None
        try:
            if ssh_public_key:
                key = Path(ssh_public_key).read_text(encoding="utf-8").strip()
            else:
                key_directory = Path(request["root"]) / (".aifactory-runner-key-" + uuid4().hex)
                protect_directory(key_directory)
                executable = shutil.which("ssh-keygen")
                require(executable, "ssh-keygen-or-user-public-key-required")
                subprocess.run([executable, "-q", "-t", "ed25519", "-N", "", "-f", str(key_directory / "key")],
                               check=True, capture_output=True)
                key = (key_directory / "key.pub").read_text(encoding="utf-8").strip()
            require(re.fullmatch(r"(ssh-ed25519|ssh-rsa) [A-Za-z0-9+/=]+(?: [^\r\n]*)?", key),
                    "invalid-ssh-public-key")
            if not state["nsg"]:
                create_absent(cloud, ids["nsg"], NETWORK_API,
                              body | {"properties": {"securityRules": [{"name": "DenyAllInbound", "properties": deny_inbound()}]}})
            if not state["nic"]:
                create_absent(cloud, ids["nic"], NETWORK_API, body | {"properties": {
                    "networkSecurityGroup": {"id": ids["nsg"]}, "enableIPForwarding": False,
                    "ipConfigurations": [{"name": "private", "properties": {
                        "privateIPAllocationMethod": "Dynamic", "subnet": {"id": request["subnet"]}}}]}})
            create_absent(cloud, request["vm_id"], COMPUTE_API, body | {"properties": {
                "hardwareProfile": {"vmSize": SIZE},
                "storageProfile": {"imageReference": IMAGE, "osDisk": {
                    "name": request["vm_name"] + "-os", "createOption": "FromImage", "diskSizeGB": 128,
                    "managedDisk": {"storageAccountType": "StandardSSD_LRS"}, "deleteOption": "Detach"}},
                "osProfile": {"computerName": request["vm_name"], "adminUsername": "aifrunneradmin",
                              "linuxConfiguration": {"disablePasswordAuthentication": True, "provisionVMAgent": True,
                                                     "ssh": {"publicKeys": [{"path": "/home/aifrunneradmin/.ssh/authorized_keys",
                                                                             "keyData": key}]}}},
                "networkProfile": {"networkInterfaces": [{"id": ids["nic"], "properties": {"deleteOption": "Detach"}}]},
                "securityProfile": {"securityType": "TrustedLaunch",
                                    "uefiSettings": {"secureBootEnabled": True, "vTpmEnabled": True}}}})
        finally:
            if key_directory:
                shutil.rmtree(key_directory)
    # A disk created by this exact owned VM is tagged only after verifying managedBy.
    state = snapshot(request, cloud)
    if not request["legacy_windows"] and any(tag_values(state["disk"]).get(k) != v for k, v in request["tags"].items()):
        disk = get(cloud, ids["disk"], DISK_API)
        require(disk and disk.get("managedBy", "").lower() == request["vm_id"].lower()
                and not any(key in tag_values(disk) and tag_values(disk)[key] != value
                            for key, value in request["tags"].items()), "runner-disk-ownership-conflict")
        cloud.arm("PUT", ids["disk"] + "/providers/Microsoft.Resources/tags/default", TAGS_API,
                  data={"properties": {"tags": (disk.get("tags") or {}) | request["tags"]}}, allowed=(200, 201))
        disk = get(cloud, ids["disk"], DISK_API)
        owned(request, disk, ids["disk"])
    return request


def prerequisites(request, cloud):
    suffix = ".sh" if request["vm_os"] == "linux" else ".ps1"
    script = (LIB / ("runner-prerequisites" + suffix)).read_text(encoding="utf-8")
    if suffix == ".sh":
        script = ("#!/usr/bin/env bash\nset -euo pipefail\nsource /dev/stdin <<'AIF_RUNNER_SOURCE'\n" + script +
                  "\nAIF_RUNNER_SOURCE\naif_runner_prerequisites_main --install-missing --require-runner-runtime --require-az-modules\n")
    else:
        encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
        script = ("$ErrorActionPreference='Stop'\n. ([scriptblock]::Create([Text.Encoding]::UTF8.GetString("
                  f"[Convert]::FromBase64String('{encoded}'))))\n"
                  "Invoke-AifRunnerPrerequisites -InstallMissing -RequireAzModules\n")
    identifier = request["vm_id"] + "/runCommands/prerequisites-" + uuid4().hex
    cloud.arm("PUT", identifier, COMPUTE_API, data={
        "location": request["location"], "properties": {"source": {"script": script}, "asyncExecution": False,
        "timeoutInSeconds": 1800, "treatFailureAsDeploymentFailure": True}}, allowed=(200, 201, 202))
    for _ in range(180):
        value = get(cloud, identifier + "?$expand=instanceView", COMPUTE_API)
        view = (value or {}).get("properties", {}).get("instanceView", {})
        if view.get("executionState") == "Succeeded":
            require(view.get("exitCode") == 0, "runner-prerequisites-failed")
            return
        require(view.get("executionState") not in ("Failed", "Canceled", "TimedOut"), "runner-prerequisites-failed")
        time.sleep(10)
    raise EnrollmentError("runner-prerequisites-timeout")


def register_agent(request, cloud, *, python_executable=None):
    state = Path(request["root"]) / (".aifactory-runner-state-" + uuid4().hex)
    protect_directory(state)
    env = dict(os.environ)
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    env.update(AIF_RUNNER_MODE="self-hosted", AIF_DRY_RUN="false", AIF_ROUTE=request["provider"],
               AIF_RUNNER_VM_NAME=request["vm_name"], AIF_RUNNER_VM_RESOURCE_GROUP=request["common_rg"],
               AIF_RUNNER_VM_LOCATION=request["location"], AIF_RUNNER_OS=request["vm_os"].title(),
               AIF_DEV_SUBSCRIPTION_ID=request["target"]["subscription_id"], AIF_STATE_DIR=str(state),
               AIF_RUNNER_PYTHON=python_executable or sys.executable, GH_HOST="github.com", GITHUB_REPOSITORY=request["repository"] or "",
               GHA_RUNNER_NAME=request["agent_name"], GHA_RUNNER_LABEL=request["runner_label"],
               ADO_AGENT_NAME=request["agent_name"], ADO_AGENT_POOL=request["pool"],
               ADO_ORGANIZATION=request["ado_organization"] or "", ADO_TENANT=request["ado_tenant_id"] or "",
               ADO_AUTH_METHOD="az")
    bash = shutil.which("bash")
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        require(candidate.is_file(), "git-bash-required")
        bash = str(candidate)
    require(bash, "bash-required")
    try:
        subprocess.run([bash, str(LIB / "runner-only-registration.sh")], env=env, check=True)
    finally:
        shutil.rmtree(state)


def parser(provider):
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("plan", "ensure", "prepare-vm"))
    result.add_argument("--consumer-root", "--repo-root", dest="root", required=True)
    result.add_argument("--environment", choices=tuple(ENVIRONMENTS), default="dev", help="Selected environment (default dev).")
    result.add_argument("--config-source", help="Exact legacy variables.yaml/.yml/.json or .env; also accepts a registered projection.")
    result.add_argument("--factory-id", help="Required at a registered root; no implicit factory selection.")
    result.add_argument("--scale-set-id", help="Required with --factory-id; must match the selected environment.")
    result.add_argument("--repository", help="Existing GitHub owner/repo; never created or guessed.")
    result.add_argument("--ado-organization")
    result.add_argument("--ado-tenant")
    result.add_argument("--pool")
    result.add_argument("--agent-name")
    result.add_argument("--runner-label")
    result.add_argument("--vm-os", choices=("linux", "windows"),
                        help="Legacy ADO defaults Windows; GHA defaults Linux. Registered scoped runners require Linux.")
    result.add_argument("--vm-name")
    result.add_argument("--common-rg", help="Must equal selected existing COMMON RG.")
    result.add_argument("--subnet-id", help="Must equal selected config's common subnet ARM ID.")
    result.add_argument("--separate-github", action="store_true", help="GHA-only runner setup using registered Azure placement without changing its orchestrator.")
    result.add_argument("--prereqs-only", action="store_true", help="VM and guest prerequisites only, no provider registration or readiness claim.")
    result.add_argument("--ssh-public-key", help="Optional existing public key file; otherwise an ephemeral key is generated only for VM creation.")
    result.add_argument("--yes", action="store_true", help="Approve cloud writes; serialize all provisioning of these exact names. No atomic ARM create-only guarantee.")
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    provider = argv.pop(0) if argv else ""
    require(provider in ("ado", "gha"), "fixed-provider-required")
    args = vars(parser(provider).parse_args(argv))
    action, yes, key = args.pop("action"), args.pop("yes"), args.pop("ssh_public_key")
    try:
        require(action == "plan" or yes, "runner-ensure-requires-yes")
        request = load_request(provider=provider, **args)
        cloud = Cloud(request) if request["desired"] else None
        result = plan(request, cloud)
        if action != "plan" and request["desired"]:
            ensure_vm(request, yes=yes, cloud=cloud, ssh_public_key=key)
            if action != "prepare-vm":
                if request["prereqs_only"]:
                    prerequisites(request, cloud)
                else:
                    register_agent(request, cloud)
            result["status"] = "vm-prepared" if action == "prepare-vm" else "prerequisites-ready" if request["prereqs_only"] else "runner-ready"
            result["agent_ready"] = action == "ensure" and not request["prereqs_only"]
        print(canonical(result).decode("utf-8"))
        return 0
    except (EnrollmentError, ValueError, KeyError, OSError, TypeError, AttributeError, RecursionError,
            subprocess.SubprocessError) as exc:
        print(canonical({"status": "blocked", "agent_ready": False,
                         "error": exc.code if isinstance(exc, EnrollmentError) else "invalid-input-or-runner-operation-failed"}).decode("utf-8"))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
