"""Small ESML-specific contracts for one request, naming, and customized steps."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ml_model_factory.lake import identifier


class PipelineType(str, Enum):
    IN_2_GOLD_INFERENCE = "IN_2_GOLD_INFERENCE"
    IN_2_GOLD_INFERENCE_DBX = "IN_2_GOLD_INFERENCE_DBX"
    IN_2_GOLD = "IN_2_GOLD"
    GOLD_INFERENCE = "GOLD_INFERENCE"
    IN_2_GOLD_TRAINING_AUTOML = "IN_2_GOLD_TRAINING_AUTOML"
    IN_2_GOLD_TRAINING_MANUAL = "IN_2_GOLD_TRAINING_MANUAL"

    @property
    def is_training(self) -> bool:
        return self in (self.IN_2_GOLD_TRAINING_AUTOML, self.IN_2_GOLD_TRAINING_MANUAL)

    @property
    def is_inference(self) -> bool:
        return self in (self.IN_2_GOLD_INFERENCE, self.IN_2_GOLD_INFERENCE_DBX, self.GOLD_INFERENCE)


class StepType(str, Enum):
    IN_2_BRONZE = "IN_2_BRONZE"
    BRONZE_2_SILVER = "BRONZE_2_SILVER"
    IN_2_SILVER = "IN_2_SILVER"
    SILVER_MERGED_2_GOLD = "SILVER_MERGED_2_GOLD"
    INFERENCE_GOLD = "INFERENCE_GOLD"
    TRAINING_AUTOML = "TRAINING_AUTOML"
    TRAINING_MANUAL = "TRAINING_MANUAL"
    TRAINING_SPLIT_AND_REGISTER = "TRAINING_SPLIT_AND_REGISTER"
    EVALUATE = "EVALUATE"


@dataclass(frozen=True)
class PipelineRequest:
    data_date_utc: str
    run_id: str
    data_version: str | None = None
    snapshot_id: str | None = None
    model_version: str | None = None
    allow_reuse: bool = True

    def __post_init__(self):
        if not isinstance(self.data_date_utc, str):
            raise ValueError("data_date_utc must be an ISO UTC date or timezone-aware timestamp")
        value = self.data_date_utc
        try:
            if len(value) == 10:
                moment = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            else:
                moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if moment.tzinfo is None or moment.utcoffset().total_seconds() != 0:
                    raise ValueError("Timestamp must carry UTC Z or +00:00")
        except ValueError as exc:
            raise ValueError("data_date_utc must be a valid ISO UTC date or timestamp") from exc
        object.__setattr__(self, "data_date_utc", moment.strftime("%Y-%m-%d"))
        identifier(self.run_id, "run_id")
        for name in ("data_version", "snapshot_id", "model_version"):
            value = getattr(self, name)
            if value is not None:
                value = identifier(value, name)
                object.__setattr__(self, name, value)
                if str(value).lower() in ("0", "latest", "active", "champion", "production"):
                    raise ValueError(f"{name} must be pinned, not zero or a mutable alias")
        if type(self.allow_reuse) is not bool:
            raise ValueError("allow_reuse must be a boolean")

    @property
    def version(self) -> str:
        return self.data_version or self.data_date_utc

    @property
    def snapshot(self) -> str:
        return self.snapshot_id or self.run_id


@dataclass(frozen=True)
class StepOverride:
    component: str | dict
    compute: str | None = None
    engine: str = "azureml"
    inputs: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.component, (str, dict)) or not self.component:
            raise ValueError("Step override requires a component definition or explicit versioned component URI")
        if isinstance(self.component, str):
            import re
            if (not re.fullmatch(r"azureml:[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+", self.component)
                    or self.component.rsplit(":", 1)[1].lower() in ("0", "latest", "active", "champion", "production")):
                raise ValueError("Step component references must pin azureml:name:version")
        if self.compute:
            identifier(self.compute.removeprefix("azureml:"), "compute")
        if self.engine not in ("azureml", "databricks"):
            raise ValueError("Step engine must be azureml or databricks")


class IPipelineStepMap(ABC):
    @abstractmethod
    def resolve(self, step: StepType, dataset: str | None = None) -> StepOverride | None:
        """Provide a replacement component with the same ports, or use the built-in step."""


class DictionaryStepMap(IPipelineStepMap):
    def __init__(self, overrides: dict[StepType | tuple[StepType, str], StepOverride]):
        self._overrides = dict(overrides)
        if any(not isinstance(value, StepOverride) for value in self._overrides.values()):
            raise ValueError("Step map values must be StepOverride instances")

    def resolve(self, step: StepType, dataset: str | None = None) -> StepOverride | None:
        return self._overrides.get((step, dataset), self._overrides.get(step))
