#!/usr/bin/env python3
"""Validate the Entra object IDs that AI Factory grants Key Vault roles (Azure RBAC).

modules/kvRbacPrincipals.bicep skips every principal that is not a GUID, so a shipped
placeholder such as <todo>_EntraID_ObjectID silently leaves the common and admin Key Vaults
without an admin role assignment. preflight.sh turns every FAIL line printed here into a finding that
blocks the deployment even in WARN_ONLY mode.

Sources, checked per principal:
  * The pipeline environment (ADO maps variables to UPPERCASE names; GitHub workflows export
    the variables.json names). When a principal is set there, even to '', that is exactly what
    Bicep receives, so the settings files are not consulted for it.
  * Otherwise every settings file on its own: variables.json (each target environment, with
    the dev baseline + stage_prod + exact environment overlay), variables.yaml and .env.
An empty value means "no principal" and never blocks. groups-v1 persona access skips the check.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import functools
import importlib.util
import io
import json
import os
from pathlib import Path
import re
from typing import Mapping, Sequence


GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
INVALID = "KV_PRINCIPAL_OBJECT_ID_INVALID"
UNREADABLE = "KV_PRINCIPAL_CONFIG_UNREADABLE"
SCOPES = ("common", "project")
OVERRIDES = Path(__file__).resolve().with_name("apply-json-config-overrides.py")
# The AzureDatabricks first-party application (client) ID is the same in every tenant; Key Vault
# needs the object ID of its service principal in the customer's tenant instead.
AZURE_DATABRICKS_APP_ID = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"


@dataclass(frozen=True)
class Setting:
    name: str                       # variables.json / variables.yaml name
    dotenv: str                     # .env name
    environment: tuple[str, ...]    # pipeline environment names, in lookup order


@dataclass(frozen=True)
class Principal:
    setting: Setting
    multiple: bool                  # comma-separated list, or a single principalId
    switch: str | None              # enable flag without which the principal is not used
    scopes: tuple[str, ...]         # preflight scopes whose templates read the principal
    hint: str
    wrong_ids: tuple[tuple[str, str], ...] = ()  # well-known GUIDs that are not object IDs


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    hint: str


ENABLE_DATABRICKS = Setting("enableDatabricks", "ENABLE_DATABRICKS",
                            ("enableDatabricks", "ENABLEDATABRICKS", "ENABLE_DATABRICKS"))
ENABLE_PERSONAS = Setting("enablePersonas", "ENABLE_PERSONAS",
                          ("enablePersonas", "ENABLEPERSONAS", "ENABLE_PERSONAS"))
PERSONA_ACCESS_MODE = Setting("persona_access_mode", "PERSONA_ACCESS_MODE",
                              ("persona_access_mode", "PERSONA_ACCESS_MODE"))
FLAGS = (ENABLE_DATABRICKS, ENABLE_PERSONAS, PERSONA_ACCESS_MODE)
PRINCIPALS = (
    Principal(
        Setting("technical_admins_ad_object_id", "PROJECT_MEMBERS",
                ("technical_admins_ad_object_id", "TECHNICAL_ADMINS_AD_OBJECT_ID", "PROJECT_MEMBERS")),
        multiple=True, switch=None, scopes=SCOPES,
        hint="Use comma-separated Entra object IDs (GUIDs) of the technical admins, or leave it empty "
             "for none (.env and the GitHub secret: PROJECT_MEMBERS)."),
    # Only esml-common/main/13-rgLevel.bicep reads databricksOID; no project template does.
    Principal(
        Setting("databricksOID", "DATABRICKS_OID", ("databricksOID", "DATABRICKSOID", "DATABRICKS_OID")),
        multiple=False, switch=ENABLE_DATABRICKS.name, scopes=("common",),
        hint="Use the object ID (GUID) of the AzureDatabricks enterprise application in your Entra tenant "
             "(.env: DATABRICKS_OID), leave it empty for no grant, or set enableDatabricks to false.",
        wrong_ids=((AZURE_DATABRICKS_APP_ID, "the AzureDatabricks application (client) ID, not your tenant's "
                                             "object ID for it"),)),
)


def is_true(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def groups_v1(values: Mapping[str, str]) -> bool:
    """Persona mode as personas/pipeline.py access_mode resolves it; groups-v1 clears human principals."""
    enabled = str(values.get(ENABLE_PERSONAS.name, "")).strip()
    if enabled:
        return is_true(enabled)
    return str(values.get(PERSONA_ACCESS_MODE.name, "")).strip().lower() == "groups-v1"


def problem(principal: Principal, value: str) -> str | None:
    """Why a non-empty value would not grant its principal any Key Vault access (None when valid)."""
    entries = [entry.strip() for entry in value.split(",")]
    if not principal.multiple and len(entries) > 1:
        return "must be one object ID, not a list"
    for wrong, description in principal.wrong_ids:
        if any(entry.lower() == wrong for entry in entries):
            return f"is {description}"
    invalid = [(position, entry) for position, entry in enumerate(entries, 1) if not GUID.fullmatch(entry)]
    if not invalid:
        return None
    # Placeholders and plain words are shown. An entry with digits may be a mistyped real ID and is
    # shown only by position, because GitHub masks a whole secret such as PROJECT_MEMBERS, not entries.
    shown = ", ".join(ascii(entry[:60]) if "<" in entry or not any(ch.isdigit() for ch in entry)
                      else f"entry {position} of {len(entries)}" for position, entry in invalid)
    return f"has entries that are not Entra object IDs (GUIDs): {shown}"


def pipeline_value(environ: Mapping[str, str], setting: Setting, keep_empty: bool) -> tuple[str, str] | None:
    for name in setting.environment:
        value = environ.get(name)
        # An unresolved Azure DevOps macro such as $(databricksOID) means the variable is undefined.
        if value is None or value.startswith("$(") or (not keep_empty and not value.strip()):
            continue
        return name, value
    return None


def yaml_settings(path: Path) -> dict[str, str]:
    """First 'key: value' per key, like preflight.sh yaml_get, also unquoting single quotes."""
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_]+)\s*:(.*)$", line)
        if not match or match.group(1) in result:
            continue
        raw = match.group(2).strip()
        quoted = re.match(r"^(\"|')(.*?)\1", raw)
        result[match.group(1)] = quoted.group(2) if quoted else raw.split("#", 1)[0].strip()
    return result


def dotenv_settings(path: Path) -> dict[str, str]:
    """Last 'KEY=value' per key, like preflight.sh dotenv_get, without cutting quoted '#'."""
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=(.*)$", line)
        if not match:
            continue
        raw = match.group(2).strip()
        quoted = re.match(r"^(\"|')(.*?)\1", raw)
        result[match.group(1)] = quoted.group(2) if quoted else raw.split("#", 1)[0].strip()
    return result


@functools.lru_cache(maxsize=None)
def json_overrides():
    spec = importlib.util.spec_from_file_location("_aif_json_config_overrides", OVERRIDES)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_settings(path: Path, environment: str) -> dict[str, str]:
    """The environment's values with the same overlay apply-json-config-overrides.py applies in CI."""
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("the root must be an object with dev/stage_prod/test/prod sections")
    errors = io.StringIO()
    try:
        with contextlib.redirect_stderr(errors):
            values, _ = json_overrides().selected_values(config, environment)
    except SystemExit:
        raise ValueError(errors.getvalue().strip() or "invalid configuration") from None
    return values


def validate(environ: Mapping[str, str], environments: Sequence[str], variables_json: Path | None = None,
             variables_yaml: Path | None = None, env_file: Path | None = None,
             scope: str | None = None) -> tuple[list[Finding], list[str]]:
    """Return the blocking findings and informational notes; scope None checks every principal."""
    findings: list[Finding] = []
    notes: list[str] = []
    checked: list[str] = []
    principals = [principal for principal in PRINCIPALS if scope is None or scope in principal.scopes]
    pipeline_flags = {setting.name: found[1] for setting in FLAGS
                      if (found := pipeline_value(environ, setting, keep_empty=False))}
    if groups_v1(pipeline_flags):
        # The persona bridge already resolved this run; settings-file copies cannot change that.
        notes.append("the pipeline environment: groups-v1 persona access clears the technical admins and the "
                     "Databricks Key Vault grant, so they are not validated.")
        return findings, notes

    files: list[tuple[str, dict[str, str], bool]] = []  # label, canonical values, dotenv naming
    if variables_yaml:
        files.append(("variables.yaml", yaml_settings(Path(variables_yaml)), False))
    if env_file:
        raw = dotenv_settings(Path(env_file))
        names = [principal.setting for principal in PRINCIPALS] + list(FLAGS)
        files.append((".env", {setting.name: raw[setting.dotenv] for setting in names if setting.dotenv in raw}, True))
    in_pipeline = {principal.setting.name: pipeline_value(environ, principal.setting, keep_empty=True)
                   for principal in principals}
    if variables_json and not all(in_pipeline.values()):
        for environment in environments:
            label = f"variables.json [{environment}]"
            try:
                files.append((label, json_settings(Path(variables_json), environment), False))
            except (OSError, ValueError) as error:
                findings.append(Finding(UNREADABLE, f"{label} cannot be read: {error}",
                                        "Fix variables.json, or pass the intended file with --variables-json."))

    def check(label: str, values: Mapping[str, str], selected, name_of) -> None:
        if groups_v1(values):
            notes.append(f"{label}: groups-v1 persona access clears the technical admins and the Databricks "
                         "Key Vault grant, so they are not validated.")
            return
        for principal in selected:
            if principal.switch and not is_true(values.get(principal.switch, "")):
                continue
            name = name_of(principal)
            text = str(values.get(principal.setting.name, "")).strip()
            if not text:
                if principal.switch:
                    notes.append(f"{name} is empty in {label} while {principal.switch} is true: "
                                 "no Key Vault role is granted for it.")
                continue
            reason = problem(principal, text)
            if reason:
                findings.append(Finding(INVALID, f"{name} in {label} {reason}, so the principal would get "
                                        "no access to the common/admin Key Vaults.", principal.hint))
        checked.append(label)

    pipeline = [principal for principal in principals if in_pipeline[principal.setting.name]]
    if pipeline:
        # Flags absent from the pipeline environment come from the settings files, as preflight getval does.
        values = dict(pipeline_flags)
        for setting in FLAGS:
            if setting.name not in values:
                values[setting.name] = next((file_values[setting.name] for _, file_values, _ in files
                                             if str(file_values.get(setting.name, "")).strip()), "")
        values.update({name: found[1] for name, found in in_pipeline.items() if found})
        check("the pipeline environment", values, pipeline,
              lambda principal: in_pipeline[principal.setting.name][0])
    remaining = [principal for principal in principals if not in_pipeline[principal.setting.name]]
    for label, file_values, dotenv in files if remaining else ():
        check(label, file_values, remaining,
              lambda principal: principal.setting.dotenv if dotenv else principal.setting.name)
    if checked and not findings:
        notes.append("Key Vault principal object IDs are valid in: " + ", ".join(checked) + ".")
    return findings, notes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variables-json", type=Path)
    parser.add_argument("--variables-yaml", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--environment", action="append", default=[], help="dev, test/stage or prod; repeatable")
    parser.add_argument("--scope", choices=SCOPES, help="principals the common or project templates read; "
                                                         "default: both")
    args = parser.parse_args(argv)
    findings, notes = validate(os.environ, args.environment or ["dev"], args.variables_json,
                               args.variables_yaml, args.env_file, args.scope)
    for note in notes:
        print(f"INFO\t{note}")
    for finding in findings:
        fields = (finding.code, finding.message, finding.hint)
        print("FAIL\t" + "\t".join(field.replace("\t", " ").replace("\n", " ") for field in fields))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
