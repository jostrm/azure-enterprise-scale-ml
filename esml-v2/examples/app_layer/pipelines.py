"""Customer-owned composition; rendering is offline and never submits a job."""

from pathlib import Path

from azure_esml import ESMLProject, PipelineRequest, PipelineType


def create_training(settings: Path, destination: Path):
    project = ESMLProject.from_json(settings)
    return project.create_pipeline(
        PipelineType.IN_2_GOLD_TRAINING_AUTOML,
        PipelineRequest(data_date_utc="2026-09-13", run_id="training-example-001"),
        output=destination,
    )


def create_inference(settings: Path, destination: Path, *, data_date_utc: str, model_version: str, run_id: str):
    project = ESMLProject.from_json(settings)
    return project.create_pipeline(
        PipelineType.IN_2_GOLD_INFERENCE,
        PipelineRequest(data_date_utc=data_date_utc, model_version=model_version, run_id=run_id),
        output=destination,
    )
