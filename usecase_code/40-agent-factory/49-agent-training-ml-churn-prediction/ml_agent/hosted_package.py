"""Operator-side packaging and deployment of the example 49 Foundry hosted agent.

The ZIP is an explicit allowlist: the hosted entry point, ml_agent, the vendored azure_esml and
ml_model_factory sources of the installed ESML v2 SDK, and a bundle of reviewed, secret-free
configuration (consumer config, reviewed rollout, champion receipt, scenarios, selection policy).
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .configuration import TEMPLATE, canonical_sha256, fingerprint, read_json
from .runtime import ApprovalRequired
from .usecases import AIR

ENTRY = TEMPLATE / "hosted_main.py"
REQUIREMENTS = TEMPLATE / "hosted-requirements.txt"
CPU, MEMORY, RUNTIME = "1", "2Gi", "python_3_13"
DESCRIPTION = ("49 hosted: Foundry Playground entry point for M49 synthetic churn, M05 air-passengers "
               "retraining and batch inference through ESML v2.")
TEXT = {".py", ".json", ".txt", ".md", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".ipynb"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", "tests"}
MAX_PACKAGE_BYTES = 50 * 1024 * 1024


def hosted_agent_name(config: dict) -> str:
    return f"{config['owner']}-{config['version']}-ml-churn-hosted"


def _data(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or symlinked package source: {path}")
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n") if path.suffix.lower() in TEXT else data


def _tree(root: Path, prefix: str) -> dict[str, bytes]:
    files = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if SKIP_PARTS & set(relative.parts[:-1]) or path.suffix in {".pyc", ".pyo"}:
            continue
        files[f"{prefix}/{relative.as_posix()}"] = _data(path)
    return files


def bundle_config(config: dict) -> dict:
    """The consumer configuration without operator workstation paths (the sandbox sets its own)."""
    value = json.loads(json.dumps(config))
    for key in ("factory_config", "ml_factory_root", "evidence_root", "state_root", "reviewed_rollout"):
        value[key] = f"/hosted-bundle/{key}"
    value["usecases"][AIR]["champion_receipts"] = "/hosted-bundle/champion"
    return value


def package_files(config: dict) -> dict[str, bytes]:
    import azure_esml
    import ml_model_factory

    files = {"main.py": _data(ENTRY), "requirements.txt": _data(REQUIREMENTS)}
    files.update({f"ml_agent/{path.name}": _data(path) for path in sorted((TEMPLATE / "ml_agent").glob("*.py"))})
    for module in (azure_esml, ml_model_factory):
        root = Path(module.__file__).resolve().parent
        files.update(_tree(root, root.name))
    files["bundle/config.json"] = (json.dumps(bundle_config(config), indent=2, sort_keys=True) + "\n").encode("utf-8")
    files["bundle/reviewed-rollout.json"] = _data(Path(config["reviewed_rollout"]))
    champion = Path(config["usecases"][AIR]["champion_receipts"]) / "training-completion.json"
    files["bundle/champion/training-completion.json"] = _data(champion)
    model = Path(config["ml_factory_root"]) / "user-config" / "model"
    for path in sorted((model / "scenarios").glob("*.json")):
        files[f"bundle/ml-factory/user-config/model/scenarios/{path.name}"] = _data(path)
    files["bundle/ml-factory/user-config/model/model-selection.json"] = _data(model / "model-selection.json")
    if "bundle/ml-factory/user-config/model/scenarios/49-agent-training-ml-churn-prediction.json" not in files:
        raise ValueError("Create the M49 scenario in the ML factory copy (prepare-local) before packaging")
    return files


def build_package(config: dict, output: Path) -> dict:
    """Write a byte-reproducible ZIP; no Azure access."""
    files = package_files(config)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"{hosted_agent_name(config)}.zip"
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
    size = package.stat().st_size
    if size > MAX_PACKAGE_BYTES:
        raise ValueError(f"Hosted package is {size} bytes; keep it below {MAX_PACKAGE_BYTES}")
    return {"package": str(package), "sha256": hashlib.sha256(package.read_bytes()).hexdigest(), "files": len(files),
            "bytes": size, "config_sha256": fingerprint(config)}


def _field(value, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def environment(config: dict) -> dict[str, str]:
    host = urlsplit(config["project_endpoint"]).hostname
    return {"FOUNDRY_PROJECT_ENDPOINT": config["project_endpoint"], "FOUNDRY_RESOURCE_ENDPOINT": f"https://{host}",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": config["model_deployment"], "OPENAI_AGENTS_DISABLE_TRACING": "1"}


def deploy(project, config: dict, built: dict, *, apply: bool = False, allow_paid: bool = False,
           timeout_seconds: int = 2700, poll_seconds: int = 15, sleep=time.sleep) -> dict:
    """Create (or reuse) the owned hosted version from the built ZIP, wait until active, then route it."""
    if apply is not True or allow_paid is not True:
        raise ApprovalRequired("Hosted deployment requires --apply and --allow-paid.")
    from agent_factory.catalog import OWNER, metadata, validate_agent_name
    from agent_factory.prompt import route_version
    from azure.ai.projects.models import CodeConfiguration, HostedAgentDefinition, ProtocolVersionRecord
    from azure.core.exceptions import ResourceNotFoundError

    package = Path(built["package"])
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    if digest != built["sha256"] or built["config_sha256"] != fingerprint(config):
        raise ValueError("The package changed after it was built; build it again.")
    name = validate_agent_name(hosted_agent_name(config))
    variables = environment(config)
    tags = {**metadata("hosted", role="specialist"), "aifactory.solution_id": "agent-ml-training",
            "aifactory.execution_kind": "hosted", "aif49.owner": config["owner"],
            "aif49.config_sha256": fingerprint(config), "aif49.package_sha256": digest}
    tags["aifactory.definition_hash"] = canonical_sha256({
        "package_sha256": digest, "environment": variables, "cpu": CPU, "memory": MEMORY, "runtime": RUNTIME,
        "protocol": "responses/2.0.0", "description": DESCRIPTION})
    try:
        latest = _field(_field(project.agents.get(agent_name=name), "versions"), "latest")
    except ResourceNotFoundError:
        latest = None
    if latest is not None:
        saved = _field(latest, "metadata") or {}
        if saved.get("aifactory.managed_by") != OWNER or saved.get("aif49.owner") != config["owner"]:
            raise ValueError(f"Refusing to modify agent {name!r}: it is not owned by this configuration.")
    status = "unchanged"
    if latest is None or (_field(latest, "metadata") or {}).get("aifactory.definition_hash") != tags[
            "aifactory.definition_hash"] or _field(latest, "status") in {"failed", "deleted", "deleting"}:
        definition = HostedAgentDefinition(
            cpu=CPU, memory=MEMORY,
            code_configuration=CodeConfiguration(runtime=RUNTIME, entry_point=["python", "main.py"],
                                                 dependency_resolution="remote_build"),
            environment_variables=variables,
            protocol_versions=[ProtocolVersionRecord(protocol="responses", version="2.0.0")])
        with package.open("rb") as code:
            latest = project.agents.create_version_from_code(
                agent_name=name, definition=definition, code=code, code_zip_sha256=digest,
                description=DESCRIPTION, metadata=tags)
        status = "created"
    version = str(_field(latest, "version"))
    deadline = time.monotonic() + timeout_seconds
    while True:
        detail = project.agents.get_version(agent_name=name, agent_version=version)
        state = _field(detail, "status")
        if state == "active":
            break
        if state in {"failed", "deleting", "deleted"}:
            raise RuntimeError(f"Hosted agent {name} version {version} is {state}: {_field(detail, 'error')}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Hosted agent {name} version {version} is still {state}; check it again later.")
        sleep(poll_seconds)
    route_version(project, name, version)
    identity = _field(detail, "instance_identity") or {}
    return {"name": name, "version": version, "status": status, "state": state, "package_sha256": digest,
            "config_sha256": fingerprint(config), "definition_sha256": tags["aifactory.definition_hash"],
            "principal_id": _field(identity, "principal_id"), "client_id": _field(identity, "client_id"),
            "deployed_at": datetime.now(timezone.utc).isoformat(), "execution": "foundry-hosted"}


def seed_state(container, config: dict, *, apply: bool = False) -> dict:
    """Create-only upload of the operator's publication record so hosted plans continue its versions."""
    if apply is not True:
        raise ApprovalRequired("Seeding hosted agent state writes to the lake; pass --apply.")
    from azure.core.exceptions import ResourceExistsError

    from .configuration import paths
    from .hosted import state_prefix
    from .plan import PUBLICATIONS

    source = paths(config).state / PUBLICATIONS
    if not source.is_file():
        return {"seeded": [], "reason": "no publications recorded yet"}
    name = f"{state_prefix(config)}/state/{PUBLICATIONS}"
    try:
        container.upload_blob(name, json.dumps(read_json(source), indent=2) + "\n", overwrite=False)
    except ResourceExistsError:
        return {"seeded": [], "existing": [name]}
    return {"seeded": [name]}
