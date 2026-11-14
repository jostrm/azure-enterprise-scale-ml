"""Canonical, credential-free registered inputs for the optional Pipelines-only route.

The register is authoritative. Projection files and explicit variables inputs must
agree with it; invocation never merges configuration or grants execution consent.
ZIPs are read as bounded virtual files, never extracted or executed.
"""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import math
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID

import initialize_azurefactory as starter


MAX_JSON_BYTES = starter.MAX_REGISTER_BYTES
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2048
SUBSCRIPTIONS = {"dev": "dev_sub_id", "stage": "test_sub_id", "prod": "prod_sub_id"}
SECRET = re.compile(
    r"secret|password|credential|private[_ -]?key|api[_ -]?key|connection[_ -]?string|"
    r"(?:access|refresh|auth|bearer)[_ -]?token|(?:^|_)token$|pat$", re.I)
REFERENCE = re.compile(r"secret[_ -]?(?:id|uri|url)$|credential[_ -]?env(?:ironment)?(?:variable)?$", re.I)
SECRET_NAMES = {"inputCommonSPSecretKey", "project_service_principal_Secret_seeding_kv_name"}
CREDENTIAL_NAMES = {
    "githubtoken", "ghtoken", "azurestoragekey", "storageaccountkey", "accountkey",
    "clientassertion", "sastoken", "sas", "accesskey", "sharedaccesssignature",
    "systemaccesstoken", "subscriptionkey",
}
CREDENTIAL_VALUE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})\b|"
    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b")
REQUEST_FIELDS = {
    "schema", "scenario", "provider", "azurefactory_root", "factory", "environment",
    "scale_set", "project", "source_ref", "source_commit", "variables", "bundle",
    "provider_binding", "include_project_subnets", "include_keyvault_and_resource_group",
}
DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}


class InputError(ValueError):
    """A safe diagnostic that never includes input values or credentials."""


def require(condition, code):
    if not condition:
        raise InputError(code)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate-json-key")
        result[key] = value
    return result


def decode_json(raw):
    require(len(raw) <= MAX_JSON_BYTES, "json-size-limit")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                          parse_constant=lambda _: require(False, "nonfinite-json"))
    except (UnicodeError, json.JSONDecodeError):
        raise InputError("invalid-json") from None


def public_configuration(value):
    """Reject, rather than redact, credentials including nested JSON strings."""
    if isinstance(value, dict):
        if set(value) == {"reference"}:
            reference = value["reference"]
            require(isinstance(reference, dict) and {"keyVault", "secretName"} <= set(reference)
                    and set(reference) <= {"keyVault", "secretName", "secretVersion"},
                    "invalid-arm-keyvault-reference")
            vault = reference["keyVault"]
            require(isinstance(vault, dict) and set(vault) == {"id"} and isinstance(vault["id"], str),
                    "invalid-arm-keyvault-reference")
            match = re.fullmatch(
                r"/subscriptions/([a-f0-9-]{36})/resourceGroups/[A-Za-z0-9_.()-]{1,90}"
                r"/providers/Microsoft.KeyVault/vaults/[a-z][a-z0-9-]{1,22}[a-z0-9]", vault["id"], re.I)
            require(match is not None, "invalid-arm-keyvault-reference")
            guid(match[1].lower())
            require(isinstance(reference["secretName"], str)
                    and re.fullmatch(r"[A-Za-z0-9-]{1,127}", reference["secretName"]),
                    "invalid-arm-keyvault-reference")
            require("secretVersion" not in reference or isinstance(reference["secretVersion"], str)
                    and re.fullmatch(r"[a-fA-F0-9]{32}", reference["secretVersion"]),
                    "invalid-arm-keyvault-reference")
            return
        for key, item in value.items():
            require(isinstance(key, str), "configuration-key-type")
            normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower()
            compact = re.sub(r"[_ -]", "", normalized)
            if isinstance(item, dict) and set(item) == {"reference"}:
                public_configuration(item)
                continue
            if key in SECRET_NAMES:
                require(isinstance(item, str) and (not item or re.fullmatch(r"[A-Za-z0-9-]{1,127}", item)),
                        "invalid-secret-name-reference")
            elif REFERENCE.search(normalized):
                require(isinstance(item, str), "invalid-credential-reference")
                if "credential" in normalized:
                    require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", item),
                            "invalid-credential-environment-reference")
                else:
                    require(not item or re.fullmatch(
                        r"https://[a-zA-Z0-9-]+\.(?:vault\.azure\.net|vault\.usgovcloudapi\.net|vault\.azure\.cn)"
                        r"/secrets/[a-zA-Z0-9-]+(?:/[a-fA-F0-9]{32})?", item),
                        "invalid-keyvault-secret-reference")
            else:
                require(not SECRET.search(normalized) and compact not in CREDENTIAL_NAMES,
                        "credential-field-forbidden")
            public_configuration(item)
    elif isinstance(value, list):
        for item in value:
            public_configuration(item)
    elif isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            public_configuration(decode_json(value.encode("utf-8")))
        require("-----BEGIN " not in value and not CREDENTIAL_VALUE.search(value) and not re.search(
            r"(?:AccountKey=|SharedAccessSignature=|[?&]sig=|Bearer\s+[A-Za-z0-9._-]+)", value, re.I),
            "credential-value-forbidden")
    else:
        require(type(value) in (bool, int, float, type(None))
                and (type(value) is not float or math.isfinite(value)), "nonfinite-configuration")


def relative_path(value):
    require(isinstance(value, str) and 0 < len(value) <= 1024
            and "\\" not in value and not value.startswith("/")
            and all(ord(c) >= 32 for c in value), "repository-relative-path-required")
    parts = value.split("/")
    require(all(p not in ("", ".", "..") and not re.search(r'[<>:"|?*]', p)
                and p == p.rstrip(" .") and p.split(".")[0].casefold() not in DEVICES
                for p in parts), "unsafe-path-component")
    return PurePosixPath(value)


def ordinary_path(root, relative):
    relative = relative_path(relative)
    try:
        path = starter.ordinary(root.joinpath(*relative.parts))
        require(path.resolve().is_relative_to(root.resolve()), "path-escapes-repository")
        return path
    except (OSError, ValueError) as error:
        if isinstance(error, InputError):
            raise
        raise InputError("ordinary-repository-path-required") from None


def read_json(root, relative):
    path = ordinary_path(Path(root).absolute(), relative)
    require(path.is_file() and path.stat().st_size <= MAX_JSON_BYTES, "bounded-json-file-required")
    return decode_json(path.read_bytes())


class RepositoryInputs:
    def __init__(self, root):
        self.root = Path(root).absolute()
        try:
            starter.ordinary(self.root)
        except ValueError:
            raise InputError("ordinary-repository-root-required") from None
        require(self.root.is_dir(), "repository-root-required")

    def exists(self, relative):
        return ordinary_path(self.root, relative).exists()

    def read(self, relative):
        return read_json(self.root, relative)


class BundleInputs:
    def __init__(self, root, bundle, azurefactory_root):
        path = ordinary_path(Path(root).absolute(), bundle)
        require(path.is_file() and path.stat().st_size <= MAX_ARCHIVE_BYTES, "archive-size-limit")
        self.files = {}
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                require(len(entries) <= MAX_ARCHIVE_ENTRIES, "archive-entry-limit")
                names, total = set(), 0
                for entry in entries:
                    name = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
                    relative_path(name)
                    folded = name.casefold()
                    require(folded not in names, "archive-duplicate-path")
                    names.add(folded)
                    mode = entry.external_attr >> 16
                    require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR)
                            and not entry.flag_bits & 1, "archive-link-or-encryption-forbidden")
                    require(not any(p in (".git", ".azurefactory") for p in PurePosixPath(name).parts),
                            "archive-private-state-forbidden")
                    total += entry.file_size
                    require(entry.file_size <= MAX_JSON_BYTES and total <= MAX_ARCHIVE_BYTES,
                            "archive-size-limit")
                    require(entry.file_size <= max(1024 * 1024, entry.compress_size * 100),
                            "archive-compression-limit")
                    if not entry.is_dir():
                        require(name.endswith(".json"), "archive-json-inputs-only")
                        with archive.open(entry) as stream:
                            raw = stream.read(MAX_JSON_BYTES + 1)
                        require(len(raw) == entry.file_size, "archive-entry-size-mismatch")
                        self.files[name] = decode_json(raw)
                        public_configuration(self.files[name])
                registers = [name for name in self.files if PurePosixPath(name).name.casefold() == "register.json"]
                require(registers == [azurefactory_root + "/register.json"], "archive-ambiguous-register-root")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError):
            raise InputError("invalid-archive") from None

    def exists(self, relative):
        relative_path(relative)
        return relative in self.files

    def read(self, relative):
        require(self.exists(relative), "bundle-input-missing")
        return copy.deepcopy(self.files[relative])


def guid(value):
    try:
        parsed = UUID(value)
        require(parsed.int != 0 and str(parsed) == value, "canonical-nonzero-uuid-required")
    except (ValueError, TypeError, AttributeError):
        raise InputError("canonical-nonzero-uuid-required") from None
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"(?!000)[0-9]{3}", value),
            "three-digit-identifier-required")
    return value


def readable_key(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{1,79}", value)
            and value not in DEVICES, "readable-key-required")
    return value


def project_path(root, factory, project):
    return (root + "/factories/" + factory["key"] + "/scalesets/" + project["storage_suffix"]
            + "/projects/project" + project["number"])


def validate_variables(factory, scales, project, values):
    require(isinstance(values, dict) and set(values) == {"dev", "stage_prod"}
            and all(isinstance(v, dict) for v in values.values()), "variables-sections-required")
    public_configuration(values)
    environments = set()
    for placement in project["placements"]:
        require(isinstance(placement, dict) and set(placement) == {"environment", "scale_set_id"},
                "invalid-project-placement")
        scale = scales.get(placement["scale_set_id"])
        environment = placement["environment"]
        require(scale is not None and environment == scale["environment"] and environment not in environments,
                "project-placement-conflict")
        environments.add(environment)
        selected = values["dev" if environment == "dev" else "stage_prod"]
        expected = {"admin_aifactoryPrefixRG": factory["prefix"], "admin_location": factory["region"],
                    "admin_aifactorySuffixRG": "-" + scale["suffix"], "tenantId": scale["tenant_id"],
                    SUBSCRIPTIONS[environment]: scale["subscription_id"], "project_number_000": project["number"]}
        if factory.get("region_short_name"):
            expected["admin_locationSuffix"] = factory["region_short_name"]
        require(all(selected.get(k) == v for k, v in expected.items()), "configuration-identity-conflict")


def canonical_reference_aliases(value):
    """Keep ARM transport wrappers out of the unchanged shared catalog schema."""
    if isinstance(value, dict):
        require(set(value) != {"reference"}, "canonical-secret-id-alias-required")
        for item in value.values():
            canonical_reference_aliases(item)
    elif isinstance(value, list):
        for item in value:
            canonical_reference_aliases(item)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        canonical_reference_aliases(decode_json(value.encode("utf-8")))


def validate_register(document):
    try:
        starter.check_envelope(document)
    except (ValueError, TypeError, KeyError):
        raise InputError("registered-schema-two-required") from None
    public_configuration(document)
    canonical_reference_aliases(document)
    identities, keys, physical, subscriptions = set(), set(), set(), {}
    for factory in document["factories"]:
        readable_key(factory["key"])
        require(factory["kind"] == "ai", "pipeline-ai-factory-required")
        require(factory["key"] not in keys, "duplicate-factory")
        keys.add(factory["key"])
        require(isinstance(factory.get("prefix"), str)
                and re.fullmatch(r"[a-z][a-z0-9-]{1,19}", factory["prefix"])
                and isinstance(factory.get("region"), str)
                and re.fullmatch(r"[a-z][a-z0-9]+", factory["region"]), "invalid-factory-identity")
        require(isinstance(factory["scale_sets"], list) and isinstance(factory["projects"], list),
                "invalid-factory-children")
        config = document["configurations"][factory["id"]]
        scales, pairs, homes, placements = {}, set(), set(), set()
        for entity in [factory, *factory["scale_sets"], *factory["projects"]]:
            require(isinstance(entity, dict), "invalid-catalog-entity")
            identity = guid(entity.get("id"))
            require(identity not in identities, "duplicate-entity-identity")
            identities.add(identity)
        for scale in factory["scale_sets"]:
            suffix, environment = identifier(scale.get("suffix")), scale.get("environment")
            require(environment in SUBSCRIPTIONS and scale.get("orchestrator") in ("gha", "ado"),
                    "invalid-scale-environment-provider")
            guid(scale.get("tenant_id"))
            guid(scale.get("subscription_id"))
            require(subscriptions.setdefault(scale["subscription_id"], scale["tenant_id"]) == scale["tenant_id"],
                    "subscription-tenant-conflict")
            pair = (environment, suffix)
            target = (scale["subscription_id"], factory["prefix"], factory["region"], *pair)
            require(pair not in pairs and target not in physical, "duplicate-physical-scope")
            pairs.add(pair)
            physical.add(target)
            network = scale.get("network")
            require(isinstance(network, dict), "scale-network-required")
            try:
                cidr = ipaddress.ip_network(network.get("vnet_cidr"), strict=True)
            except (TypeError, ValueError):
                raise InputError("invalid-scale-cidr") from None
            require(cidr.version == 4 and type(network.get("max_projects")) is int
                    and 1 <= network["max_projects"] <= 8, "invalid-scale-network")
            scales[scale["id"]] = scale
        require(set(config["scale_sets"]) == set(scales)
                and set(config["projects"]) == set(config["variables"])
                == {p["id"] for p in factory["projects"]}, "configuration-scope-conflict")
        for project in factory["projects"]:
            number, suffix = identifier(project.get("number")), identifier(project.get("storage_suffix"))
            readable_key(project.get("key"))
            require((suffix, number) not in homes, "duplicate-project-home")
            homes.add((suffix, number))
            require(isinstance(project.get("placements"), list), "project-placements-required")
            validate_variables(factory, scales, project, config["variables"][project["id"]])
            for placement in project["placements"]:
                identity = (placement["scale_set_id"], number)
                require(identity not in placements, "duplicate-project-placement")
                placements.add(identity)
        for scale_id, scale in scales.items():
            require(sum(s == scale_id for s, _ in placements) <= scale["network"]["max_projects"],
                    "scale-project-capacity-exceeded")
        for provider, binding in document["bindings"].get(factory["id"], {}).items():
            import factory_enrollment
            try:
                factory_enrollment._validate_binding(binding)
            except (factory_enrollment.EnrollmentError, KeyError, TypeError):
                raise InputError("invalid-canonical-binding") from None
            require(provider == binding["orchestrator"] and all(
                t["scale_set_id"] in scales and scales[t["scale_set_id"]]["orchestrator"] == provider
                for t in binding["targets"]), "binding-scope-conflict")


def normalize_request(raw):
    require(isinstance(raw, dict) and set(raw) <= REQUEST_FIELDS, "unknown-request-field")
    result = copy.deepcopy(raw)
    require(type(result.get("schema")) is int and result["schema"] == 1, "request-schema-required")
    scenario = result.get("scenario")
    require(type(scenario) is int and 1 <= scenario <= 6, "scenario-one-through-six-required")
    require(result.get("provider") in ("gha", "ado"), "provider-required")
    readable_key(result.get("factory"))
    require(result.get("environment") in (("all",) if scenario == 6 else SUBSCRIPTIONS),
            "explicit-scenario-environment-required")
    for field, required in (("scale_set", scenario != 6), ("project", scenario in (1, 3, 4))):
        if required:
            identifier(result.get(field))
        else:
            require(field not in result, "selector-not-applicable")
    require(isinstance(result.get("source_ref"), str) and re.fullmatch(
        r"refs/(?:heads|tags)/[A-Za-z0-9_./-]+", result["source_ref"])
        and ".." not in result["source_ref"] and "//" not in result["source_ref"]
        and not result["source_ref"].endswith("/"), "explicit-source-ref-required")
    require(isinstance(result.get("source_commit"), str)
            and re.fullmatch(r"[a-f0-9]{40}", result["source_commit"]), "explicit-source-commit-required")
    result.setdefault("azurefactory_root", "azurefactory")
    for field in ("azurefactory_root", "variables", "bundle", "provider_binding"):
        if field in result:
            relative_path(result[field])
    require(PurePosixPath(result["azurefactory_root"]).name == "azurefactory", "registered-root-required")
    require("variables" not in result or scenario in (1, 3, 4), "variables-not-applicable")
    for field, default in (("include_project_subnets", False), ("include_keyvault_and_resource_group", True)):
        if scenario == 4:
            result.setdefault(field, default)
            require(type(result[field]) is bool, "boolean-deletion-option-required")
        else:
            require(field not in result, "deletion-option-not-applicable")
    return result


def resolve_document(document, request, *, operational=None):
    """Resolve the same canonical model from authenticated durable provider state."""
    request = normalize_request(request)
    root = request["azurefactory_root"]
    document = copy.deepcopy(document)
    validate_register(document)
    matches = [f for f in document["factories"] if f["key"] == request["factory"]]
    require(len(matches) == 1, "exact-factory-required")
    factory = matches[0]
    scales = [s for s in factory["scale_sets"] if request["scenario"] == 6 or
              (s["environment"], s["suffix"]) == (request["environment"], request["scale_set"])]
    require(bool(scales) and (request["scenario"] == 6 or len(scales) == 1), "exact-scale-required")
    require(all(s["orchestrator"] == request["provider"] for s in scales), "provider-scope-conflict")
    scale_ids = {s["id"] for s in scales}
    projects = [p for p in factory["projects"] if any(
        placement["scale_set_id"] in scale_ids for placement in p["placements"])]
    if "project" in request:
        projects = [p for p in projects if p["number"] == request["project"]]
        require(len(projects) == 1, "exact-project-required")
    configuration = document["configurations"][factory["id"]]
    binding = copy.deepcopy(document["bindings"].get(factory["id"], {}).get(request["provider"], {}))
    if operational is not None:
        require(isinstance(operational, dict), "provider-binding-object-required")
        public_configuration(operational)
        require(all(operational[k] == binding[k] for k in operational.keys() & binding.keys()),
                "provider-binding-override-conflict")
        expected = {"factory_id": factory["id"], "provider": request["provider"],
                    "orchestrator": request["provider"], "environment": request["environment"]}
        for key in ("tenant_id", "subscription_id"):
            choices = {s[key] for s in scales}
            if key in operational:
                require(len(choices) == 1, "provider-binding-ambiguous-identity")
                expected[key] = next(iter(choices))
        require(all(operational[k] == expected[k] for k in operational.keys() & expected.keys()),
                "provider-binding-identity-conflict")
        binding.update(operational)
    return {"request": request, "azurefactory_root": root, "document": document, "factory": factory, "warnings": [],
            "scales": scales, "projects": projects, "configuration": configuration, "binding": binding,
            "variables": {p["id"]: configuration["variables"][p["id"]] for p in projects},
            "source": {"ref": request["source_ref"], "commit": request["source_commit"]}}


def resolve_request(repo_root, request):
    request = normalize_request(request)
    root = request["azurefactory_root"]
    reader = (BundleInputs(repo_root, request["bundle"], root) if request.get("bundle")
              else RepositoryInputs(repo_root))
    document = reader.read(root + "/register.json")
    operational = reader.read(request["provider_binding"]) if request.get("provider_binding") else None
    resolved = resolve_document(document, request, operational=operational)
    from pipeline_configuration import projections
    for relative, expected in projections(document).items():
        if relative == "register.json" or not reader.exists(root + "/" + relative):
            continue
        actual = reader.read(root + "/" + relative)
        require(isinstance(actual, dict), "configuration-projection-invalid")
        if "generation" in expected:
            if actual.get("generation") != expected["generation"]:
                resolved["warnings"].append("projection-generation-drift:" + relative)
            actual = {k: v for k, v in actual.items() if k != "generation"}
            expected = {k: v for k, v in expected.items() if k != "generation"}
        require(actual == expected, "configuration-projection-conflict")
    if "variables" in request:
        require(len(resolved["projects"]) == 1 and reader.read(request["variables"]) ==
                resolved["variables"][resolved["projects"][0]["id"]], "explicit-variables-projection-conflict")
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--request", required=True, help="Repository-relative JSON request.")
    args = parser.parse_args(argv)
    try:
        resolved = resolve_request(args.repository_root, read_json(args.repository_root, args.request))
    except InputError as error:
        print("Input rejected: " + str(error), file=sys.stderr)
        return 2
    except OSError:
        print("Input rejected: registered configuration could not be read.", file=sys.stderr)
        return 2
    print(json.dumps({"valid": True, "scenario": resolved["request"]["scenario"],
                      "provider": resolved["request"]["provider"], "factory": resolved["factory"]["key"],
                      "execution_authorized": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
