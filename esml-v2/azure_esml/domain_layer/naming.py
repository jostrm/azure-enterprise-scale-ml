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
        return azure_name(f"{self.settings.project_folder}_{self.model.folder}_pipe_{pipeline_type.value}")

    def data(self, stage: str, *, dataset: str | None = None, inference: bool = False) -> str:
        purpose = "inference" if inference else "training"
        parts = [self.model.alias]
        if dataset is not None:
            parts.append(dataset)
        parts.extend((purpose, stage.upper(), self.settings.scope["environment"]))
        return azure_name("_".join(parts))

    def component(self, pipeline_type: PipelineType) -> str:
        return azure_name("esml_" + self.experiment(pipeline_type), 200)

    def endpoint(self, pipeline_type: PipelineType) -> str:
        return azure_name("esml-" + self.experiment(pipeline_type).replace("_", "-").lower(), 32)
