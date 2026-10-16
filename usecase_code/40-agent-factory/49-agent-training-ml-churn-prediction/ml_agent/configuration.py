"""Consumer configuration for example 49. Generated state stays outside the template."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .usecases import AIR, CHURN, RUN_KEY

SCHEMA = "aif49.ml-agent-config/v1"
TEMPLATE = Path(__file__).resolve().parents[1]
GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


def read_json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def canonical_sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def fingerprint(config: dict) -> str:
    return canonical_sha256(config)


def external(path: Path) -> Path:
    """Refuse generated data, configuration or state inside the replaceable template."""
    resolved = Path(path).resolve()
    if resolved == TEMPLATE or resolved.is_relative_to(TEMPLATE):
        raise ValueError("Keep generated data, configuration and state outside the replaceable template.")
    return resolved


def _identifier(value, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be an explicit identifier")
    return value


def _directory(value, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return path


@dataclass(frozen=True)
class Paths:
    ml_root: Path
    scenarios: Path
    rollout: Path
    selection_policy: Path
    evidence: Path
    state: Path

    def raw(self, name: str) -> Path:
        return self.ml_root / "data" / "in" / name

    def esml(self, name: str) -> Path:
        """The same AzureMLRollout receipt folder that the generated notebook uses."""
        return self.ml_root / "ml-environment" / "outputs" / name / RUN_KEY / "esml"

    def work(self, name: str) -> Path:
        return self.state / "work" / name


def paths(config: dict) -> Paths:
    ml_root = Path(config["ml_factory_root"])
    return Paths(
        ml_root=ml_root,
        scenarios=ml_root / "user-config" / "model" / "scenarios",
        rollout=ml_root / "user-config" / "esml-rollout.local.json",
        selection_policy=ml_root / "user-config" / "model" / "model-selection.json",
        evidence=Path(config["evidence_root"]),
        state=Path(config["state_root"]) / config["owner"] / config["version"],
    )


def validate(config: dict) -> dict:
    if config.get("schema") != SCHEMA:
        raise ValueError(f"Expected configuration schema {SCHEMA}")
    for key in ("tenant_id", "subscription_id"):
        if not isinstance(config.get(key), str) or not GUID.fullmatch(config[key]):
            raise ValueError(f"{key} must be a GUID")
    number = config.get("project_number")
    if type(number) is not int or not 1 <= number <= 999:
        raise ValueError("project_number must be an integer from 1 to 999")
    environment = config.get("environment")
    if environment not in ("dev", "test", "prod"):
        raise ValueError("environment must be dev, test or prod")
    if config.get("owner") != f"aif49-project{number:03d}-{environment}":
        raise ValueError("owner must be aif49-project<NNN>-<environment>")
    _identifier(config.get("version"), "version")
    _identifier(config.get("aifactory"), "aifactory")
    _identifier(config.get("target"), "target")
    _identifier(config.get("model_deployment"), "model_deployment")
    endpoint = config.get("project_endpoint")
    if not isinstance(endpoint, str) or not re.fullmatch(r"https://[a-z0-9.-]+/api/projects/[A-Za-z0-9-]+", endpoint):
        raise ValueError("project_endpoint must be the exact https Foundry project endpoint")
    for key in ("factory_config", "ml_factory_root", "evidence_root", "state_root", "reviewed_rollout"):
        _directory(config.get(key), key)
    external(Path(config["state_root"]))
    external(Path(config["evidence_root"]))
    lake = config.get("shared_lake")
    if not isinstance(lake, dict):
        raise ValueError("shared_lake must describe the existing common lake")
    if not isinstance(lake.get("account_url"), str) or not re.fullmatch(
            r"https://[a-z0-9]{3,24}\.blob\.core\.windows\.net", lake["account_url"]):
        raise ValueError("shared_lake.account_url must be an https blob endpoint")
    for key in ("container", "datastore", "prefix"):
        if not isinstance(lake.get(key), str) or not lake[key]:
            raise ValueError(f"shared_lake.{key} is required")
    if lake["prefix"] == "projects" or lake["prefix"].startswith("projects/"):
        raise ValueError("shared_lake.prefix must be a versioned namespace such as mlops/v1")
    usecases = config.get("usecases")
    if not isinstance(usecases, dict) or set(usecases) != {CHURN, AIR}:
        raise ValueError(f"usecases must configure exactly {CHURN} and {AIR}")
    for name, item in usecases.items():
        _identifier(item.get("compute"), f"usecases.{name}.compute")
        rows = item.get("inference_rows")
        if type(rows) is not int or not 1 <= rows <= 100:
            raise ValueError(f"usecases.{name}.inference_rows must be 1-100")
    if type(usecases[CHURN].get("inference_seed")) is not int:
        raise ValueError("The churn use case needs an explicit inference_seed")
    champion = usecases[AIR].get("champion_model_id")
    if not isinstance(champion, str) or not re.fullmatch(r"azureml:M05_air_passengers:\d+", champion):
        raise ValueError("air-passengers needs the reviewed champion model id")
    _directory(usecases[AIR].get("champion_receipts"), "usecases.air-passengers.champion_receipts")
    return config


def load_config(path: Path) -> dict:
    return validate(read_json(path))


def make_config(factory, *, factory_config: Path, target: str, orange_root: Path, reviewed_rollout: Path,
                project_endpoint: str, model_deployment: str, state_root: Path, champion_receipts: Path,
                champion_model_id: str = "azureml:M05_air_passengers:2", version: str = "v1") -> dict:
    """Build a draft consumer configuration from the factory selection and the reviewed rollout."""
    rollout = read_json(reviewed_rollout)
    runtime = rollout.get("runtime", {})
    if (runtime.get("tenant_id") != factory.tenant_id or runtime.get("subscription_id") != factory.subscription_id
            or int(rollout.get("project_number", 0)) != int(factory.project_number)
            or runtime.get("environment_name") != factory.environment):
        raise ValueError("Reviewed rollout and factory target describe different scopes")
    targets = rollout.get("storage_targets", {})
    common = targets.get("common") if rollout.get("use_common_datalake_storage") else None
    if not isinstance(common, dict):
        raise ValueError("The reviewed rollout must select the common shared lake")
    air = rollout.get("scenarios", {}).get(AIR)
    if not isinstance(air, dict) or air.get("mode") != "custom":
        raise ValueError("The reviewed rollout must contain the custom air-passengers binding")
    orange_root = Path(orange_root).resolve()
    config = {
        "schema": SCHEMA,
        "owner": f"aif49-project{int(factory.project_number):03d}-{factory.environment}",
        "version": version,
        "tenant_id": factory.tenant_id,
        "subscription_id": factory.subscription_id,
        "aifactory": rollout["aifactory"],
        "project_number": int(factory.project_number),
        "environment": factory.environment,
        "factory_config": str(Path(factory_config).resolve()),
        "target": target,
        "project_endpoint": project_endpoint,
        "model_deployment": model_deployment,
        "ml_factory_root": str(orange_root / "aifactory-usecase-code" / "50-ml-model-factory"),
        "evidence_root": str(orange_root / "aifactory" / "ml-model-factory" / "runs"),
        "state_root": str(Path(state_root).resolve()),
        "reviewed_rollout": str(Path(reviewed_rollout).resolve()),
        "shared_lake": {
            "account_url": f"https://{common['account_name']}.blob.core.windows.net",
            "container": common["container"], "datastore": common["datastore"],
            "prefix": rollout.get("storage", {}).get("prefix", "mlops/v1"),
        },
        "usecases": {
            CHURN: {"compute": "m02-cpu-dev", "inference_rows": 50, "inference_seed": 4901},
            AIR: {"compute": air["compute"], "inference_rows": 12, "champion_model_id": champion_model_id,
                  "champion_receipts": str(Path(champion_receipts).resolve())},
        },
    }
    return validate(config)
