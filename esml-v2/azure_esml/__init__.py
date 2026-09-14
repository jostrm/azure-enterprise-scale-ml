"""Enterprise Scale ML accelerators using Azure ML SDK v2 and CLI v2 only."""

from .domain_layer.contracts import DictionaryStepMap, IPipelineStepMap, PipelineRequest, PipelineType, StepOverride, StepType
from .domain_layer.settings import LakeSettings

__version__ = "0.3.0"


def __getattr__(name):
    if name == "ESMLProject":
        from .domain_layer.project import ESMLProject
        return ESMLProject
    if name in ("ESMLPipelineFactory", "PipelinePlan"):
        from .domain_layer import pipeline
        return getattr(pipeline, name)
    raise AttributeError(name)


__all__ = ["ESMLProject", "ESMLPipelineFactory", "PipelinePlan", "LakeSettings", "PipelineRequest",
           "PipelineType", "StepType", "StepOverride", "IPipelineStepMap", "DictionaryStepMap"]
