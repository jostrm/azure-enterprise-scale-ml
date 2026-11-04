"""Stable AML names derived from the project/model/dataset lake mapping."""

from dataclasses import dataclass
import hashlib
import re

from .contracts import PipelineType
from .settings import LakeSettings, ModelSettings


def azure_name(value: str, limit: int = 255) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", value)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit - 9] + "-" + hashlib.sha256(value.encode()).hexdigest()[:8]
    return cleaned


@dataclass(frozen=True)
class ESMLNaming:
    settings: LakeSettings
    model: ModelSettings

    def experiment(self, pipeline_type: PipelineType) -> str:
        if self.model.options.get("naming_style", "legacy") == "model-prefix":
            return azure_name(f"{self.model.alias}_{self.model.use_case}_{pipeline_type.value}")
        return azure_name(f"{self.settings.project_folder}_{self.model.folder}_pipe_{pipeline_type.value}")

    def data(self, stage: str, *, dataset: str | None = None, inference: bool = False) -> str:
        if self.model.options.get("naming_style", "legacy") == "model-prefix":
            stage = stage.lower()
            stage = {
                "train": "gold_train", "validation": "gold_validation", "test": "gold_test",
                "prepared": "gold_prepared", "report": "evaluation",
                "inference": "predictions", "out": "predictions",
            }.get(stage, stage)
            if inference and stage != "predictions" and not stage.endswith("_inference"):
                stage += "_inference"
            parts = [self.model.alias, self.model.use_case]
            if dataset is not None and len(self.model.datasets) > 1:
                parts.append(dataset)
            return azure_name("_".join([*parts, stage]))
        purpose = "inference" if inference else "training"
        parts = [self.model.alias]
        if dataset is not None:
            parts.append(dataset)
        parts.extend((purpose, stage.upper(), self.settings.scope["environment"]))
        return azure_name("_".join(parts))

    def component(self, pipeline_type: PipelineType) -> str:
        if self.model.options.get("naming_style", "legacy") == "model-prefix":
            # Azure ML component IDs require lowercase letters, digits and underscores.
            return azure_name(self.experiment(pipeline_type).lower(), 200).replace("-", "_")
        return azure_name("esml_" + self.experiment(pipeline_type), 200)

    def endpoint(self, pipeline_type: PipelineType) -> str:
        if self.model.options.get("naming_style", "legacy") == "model-prefix":
            suffix = {
                PipelineType.IN_2_GOLD_INFERENCE: "batch",
                PipelineType.IN_2_GOLD_INFERENCE_DBX: "batch-dbx",
                PipelineType.GOLD_INFERENCE: "batch-gold",
                PipelineType.IN_2_GOLD: "gold",
                PipelineType.IN_2_GOLD_TRAINING_AUTOML: "train-automl",
                PipelineType.IN_2_GOLD_TRAINING_MANUAL: "train-manual",
            }[pipeline_type]
            value = f"{self.model.alias}-{self.model.use_case}-{suffix}".replace("_", "-").lower()
            return azure_name(value, 32)
        return azure_name("esml-" + self.experiment(pipeline_type).replace("_", "-").lower(), 32)

    def compute(self, purpose: str = "cpu") -> str:
        """Suggest a lowercase compute resource name; never select or provision it."""
        if not isinstance(purpose, str) or not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", purpose):
            raise ValueError("Compute purpose must contain letters, digits or separating hyphens")
        value = f"{self.model.alias}-{purpose}-{self.settings.scope['environment']}".lower()
        value = re.sub(r"[^a-z0-9-]", "-", value)
        if not value[0].isalpha():
            value = "m-" + value
        return azure_name(value, 16)
