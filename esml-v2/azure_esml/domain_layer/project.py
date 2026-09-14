"""Consumer-facing project facade; every cloud mutation is an explicit method."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import math
import time
from types import SimpleNamespace

from ml_model_factory.selection import canonical_hash
from ml_model_factory.tags import assert_scope

from azure_esml.base_layer.contracts import IFolderCatalog, MLBackend, WorkspaceTarget
from .contracts import IPipelineStepMap, PipelineRequest, PipelineType
from .naming import ESMLNaming
from .settings import LakeSettings


class _RegistrationJobReader:
    """Adapt generic backend reads to the existing shared v2 registration gate."""

    def __init__(self, backend: MLBackend):
        self.backend = backend

    def get(self, name):
        return SimpleNamespace(**self.backend.get_job(name))

    def download(self, *, name, download_path, output_name):
        self.backend.download_job(name, Path(download_path) / "download", output_name)


class ESMLProject:
    def __init__(self, settings: LakeSettings, *, backend: MLBackend | None = None,
                 folder_catalog: IFolderCatalog | None = None, step_map: IPipelineStepMap | None = None):
        self.settings = deepcopy(settings)
        self.backend = backend
        self.folder_catalog = folder_catalog
        self.step_map = step_map
        target = getattr(backend, "target", None)
        if target is not None and target != self.target:
            raise ValueError("Backend workspace differs from the selected project settings")

    @classmethod
    def from_json(cls, path: str | Path, *, overrides: dict | None = None, **dependencies):
        return cls(LakeSettings.load(path, overrides=overrides), **dependencies)

    @property
    def target(self) -> WorkspaceTarget:
        return WorkspaceTarget(**{key: self.settings.runtime[key] for key in (
            "tenant_id", "subscription_id", "resource_group", "workspace_name",
        )})

    def _backend(self) -> MLBackend:
        if self.backend is None:
            raise ValueError("Inject an AzureMLSDKBackend or AzureMLCLIBackend before requesting cloud operations")
        return self.backend

    def pipeline_factory(self):
        from .pipeline import ESMLPipelineFactory
        return ESMLPipelineFactory(self.settings, step_map=self.step_map, folder_catalog=self.folder_catalog)

    def create_pipeline(self, pipeline_type: PipelineType, request: PipelineRequest, *, output: Path,
                        model_number: int | None = None):
        return self.pipeline_factory().create_batch_pipeline(pipeline_type, request, output=output, model_number=model_number)

    def with_shared_silver(self, catalog, *, dataset: str, producer_project: str,
                           variation: str, version: str, input_name: str | None = None,
                           model_number: int | None = None):
        """Resolve an approved local/mounted catalog and return a new project configuration."""
        from .settings import DatasetSettings
        if (catalog.layout.aifactory != self.settings.aifactory
                or catalog.layout.environment != self.settings.scope["environment"]):
            raise ValueError("Shareback catalog is outside the selected factory/environment")
        selected = catalog.resolve(dataset, producer_project, variation, version, consumer_project=self.settings.project)
        model = self.settings.model(model_number)
        name = input_name or dataset
        if name not in [source.name for source in model.datasets]:
            raise ValueError("Select an existing model dataset input_name for the shared silver binding")
        from azure_esml.base_layer.tables import table_info
        info = table_info(catalog.root / selected["table_key"], version=selected["delta_version"])
        required = next(source.required_columns for source in model.datasets if source.name == name)
        if not set(required).issubset(info["columns"]):
            raise ValueError("Shared silver does not satisfy this consumer's required columns")
        inputs = tuple(DatasetSettings(
            name=source.name, input_path=selected["table_key"], format=selected["format"],
            required_columns=source.required_columns, source_stage="silver", delta_version=selected["delta_version"],
        ) if source.name == name else source for source in model.datasets)
        models = tuple(replace(item, datasets=inputs) if item.number == model.number else item for item in self.settings.models)
        return ESMLProject(replace(self.settings, models=models), backend=self.backend,
                           folder_catalog=self.folder_catalog, step_map=self.step_map)

    def connect_datastore(self) -> dict:
        storage = self.settings.storage
        kind = storage.get("type", "azure_blob")
        definition = {"name": storage["datastore"], "type": kind,
                      "account_name": storage.get("account_name")}
        if kind == "azure_blob":
            definition["container_name"] = storage.get("container")
        elif kind == "azure_data_lake_gen2":
            definition["filesystem"] = storage.get("container")
        else:
            raise ValueError("ESML lake binding supports credentialless Blob or ADLS Gen2 datastores")
        return self._backend().ensure_datastore(definition)

    def execute_pipeline(self, plan) -> dict:
        return self.submit_document(plan.document, plan.base_path)

    def _verify_document(self, document: dict, base_path: Path) -> tuple[str, str]:
        assert_scope(document.get("tags", {}), self.settings.scope)
        name = document.get("name")
        digest = document.get("tags", {}).get("esml_request_sha256")
        if not isinstance(name, str) or not name or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Submission requires an ESML-generated named job and request digest")
        from .pipeline import bundle_fingerprint
        unsigned = deepcopy(document)
        unsigned["tags"].pop("esml_request_sha256")
        if (canonical_hash(unsigned) != digest or
                document["tags"].get("esml_bundle_sha256") != bundle_fingerprint(document, base_path)):
            raise ValueError("Pipeline document or code/configuration changed after rendering; rebuild with a new run_id")
        return name, digest

    def submit_document(self, document: dict, base_path: Path) -> dict:
        from azure.core.exceptions import ResourceNotFoundError
        name, digest = self._verify_document(document, base_path)
        try:
            existing = self._backend().get_job(name)
        except ResourceNotFoundError:
            existing = None
        if existing is not None:
            assert_scope(existing.get("tags", {}), self.settings.scope)
            if (existing.get("tags", {}).get("esml_request_sha256") != digest
                    or existing.get("experiment_name") != document.get("experiment_name")):
                raise ValueError("run_id already identifies a different request or code/configuration; use a new run_id")
            return existing
        if document.get("inputs", {}).get("model"):
            reference = document["inputs"]["model"]["path"]
            name, version = reference.removeprefix("azureml:").rsplit(":", 1)
            model = self._backend().get_model(name, version)
            assert_scope(model.get("tags", {}), self.settings.scope)
            configured = [item for item in self.settings.models if item.options.get("model_name", item.folder) == name]
            if (len(configured) != 1 or model.get("tags", {}).get("use_case") != configured[0].use_case
                    or model.get("tags", {}).get("task_type") != configured[0].task):
                raise ValueError("Registered model use case/task differs from the selected lake mapping")
        return self._backend().submit(document, base_path)

    def wait_for_completion(self, job_name: str, *, timeout_seconds: float = 7200,
                            poll_seconds: float = 30, clock=time.monotonic, sleep=time.sleep) -> dict:
        if any(isinstance(value, bool) or not math.isfinite(value) or value <= 0
               for value in (timeout_seconds, poll_seconds)):
            raise ValueError("Polling timeout and interval must be finite positive seconds")
        deadline = clock() + timeout_seconds
        active = {"NotStarted", "Starting", "Provisioning", "Preparing", "Queued", "Running",
                  "Finalizing", "CancelRequested", "Paused", "Scheduled"}
        while clock() < deadline:
            job = self._backend().get_job(job_name)
            assert_scope(job.get("tags", {}), self.settings.scope)
            status = job.get("status")
            if status in ("Completed", "Succeeded"):
                return job
            if status not in active:
                raise RuntimeError(f"Job {job_name} ended in {status!r}; no successful outputs are assumed")
            sleep(min(poll_seconds, max(0, deadline - clock())))
        raise TimeoutError(f"Job {job_name} exceeded the wait limit; it may still be running and was not cancelled")

    def list_runs(self, *, pipeline_type: PipelineType | None = None, limit: int = 100) -> list[dict]:
        jobs = self._backend().list_jobs(limit=limit)
        expected = ESMLNaming(self.settings, self.settings.model()).experiment(pipeline_type) if pipeline_type else None
        return [job for job in jobs if all(job.get("tags", {}).get(key) == value
                                          for key, value in self.settings.scope.items())
                and (expected is None or job.get("experiment_name") == expected)]

    def get_dataset(self, name: str, version: str) -> dict:
        asset = self._backend().get_data(name, version)
        assert_scope(asset.get("tags", {}), self.settings.scope)
        return asset

    def register_outputs(self, plan, job_name: str) -> list[dict]:
        job = self._backend().get_job(job_name)
        assert_scope(job.get("tags", {}), self.settings.scope)
        if job.get("status") not in ("Completed", "Succeeded"):
            raise ValueError("Data outputs can only be registered from a successful job")
        if job.get("experiment_name") != plan.document.get("experiment_name"):
            raise ValueError("Job experiment differs from the compiled pipeline")
        expected_run = plan.document.get("tags", {}).get("run_id")
        if not expected_run or job.get("tags", {}).get("run_id") != expected_run:
            raise ValueError("Job run lineage differs from the compiled pipeline")
        assets = plan.manifest.get("data_assets", [])
        definitions = []
        for asset in assets:
            output = asset.get("output")
            if not output:
                raise ValueError("Data asset manifest must identify its named pipeline output")
            actual = job.get("outputs", {}).get(output)
            if not isinstance(actual, dict) or actual.get("path") != asset["path"]:
                raise ValueError(f"Completed job output {output!r} differs from the planned lake path")
            definition = {key: value for key, value in asset.items() if key != "output"}
            definitions.append(definition)
        return [self._backend().register_data(definition) for definition in definitions]

    def download_output(self, job_name: str, output_name: str, destination: Path) -> None:
        job = self._backend().get_job(job_name)
        assert_scope(job.get("tags", {}), self.settings.scope)
        if job.get("status") not in ("Completed", "Succeeded") or output_name not in job.get("outputs", {}):
            raise ValueError("A successful job and an existing named output are required")
        self._backend().download_job(job_name, destination, output_name)

    def register_model(self, job_name: str, *, model_number: int | None = None, selection_policy: dict | None = None,
                       champion_evaluation: dict | None = None, no_champion: bool = False,
                       decision_path: Path | None = None) -> str:
        from ml_model_factory.azureml import registration_definition
        # The existing v2 registration gate independently reads the real model/report lineage.
        runtime = {**self.settings.runtime, **self.settings.scope}
        model = self.settings.model(model_number)
        backend = self._backend()
        definition = registration_definition(
            job_name, runtime, model.options.get("model_name", model.folder),
            selection_policy=selection_policy, champion_evaluation=champion_evaluation,
            no_champion=no_champion, decision_path=decision_path,
            client=SimpleNamespace(jobs=_RegistrationJobReader(backend)),
        )
        if (definition["tags"].get("use_case") != model.use_case
                or definition["tags"].get("task_type") != model.task):
            raise ValueError("Evaluated training job does not belong to the selected model use case/task")
        registered = backend.register_model(definition)
        if not registered.get("id"):
            raise RuntimeError("Model registration did not return an asset ID")
        return registered["id"]

    def publish_pipeline(self, plan, *, version: str, endpoint_name: str | None = None,
                         deployment_name: str | None = None) -> dict:
        self._verify_document(plan.document, plan.base_path)
        pipeline_type = PipelineType(plan.manifest["pipeline_type"])
        if not pipeline_type.is_inference:
            raise ValueError("Batch endpoint publication is for inference plans; submit training pipelines directly")
        naming = ESMLNaming(self.settings, self.settings.model(plan.manifest.get("model_number")))
        name = endpoint_name or naming.endpoint(pipeline_type)
        component = plan.as_component(naming.component(pipeline_type), version)
        result = self._backend().publish(
            component, {"name": name, "tags": self.settings.scope},
            {"name": deployment_name or f"release-{version}",
             "settings": {"default_compute": self.settings.runtime["compute"],
                          "continue_on_step_failure": False,
                          "force_rerun": plan.document["settings"].get("force_rerun", False)},
             "tags": self.settings.scope},
            plan.base_path,
        )
        return {**result, "plan_sha256": canonical_hash(plan.document)}

    def invoke_pipeline(self, plan, published: dict) -> dict:
        if published.get("plan_sha256") != canonical_hash(plan.document):
            raise ValueError("Published deployment is bound to a different plan; rebuild/submit daily requests or republish explicitly")
        self._verify_document(plan.document, plan.base_path)
        invocation = plan.invocation()
        return self._backend().invoke(published["endpoint_name"], published["deployment_name"],
                                      invocation["inputs"], invocation["outputs"])
