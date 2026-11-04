"""Small, dataset-independent ADF contract for a server-selected ESML project."""

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from ml_model_factory.lake import identifier
from ml_model_factory.tags import assert_scope

from .contracts import PipelineRequest, PipelineType
from .naming import ESMLNaming
from .project import ESMLProject


_ACTIVE_STATUSES = (
    "NotStarted", "Starting", "Provisioning", "Preparing", "Queued", "Running",
    "Finalizing", "CancelRequested", "Paused", "Scheduled",
)
_SUCCESS_STATUSES = ("Completed", "Succeeded")
_FAILURE_STATUSES = ("Failed", "Canceled", "Cancelled", "NotResponding")


class DataOpsAdapter:
    """Submit asynchronously; ADF polls ``status`` instead of holding an HTTP call.

    The server owns project settings, workspace, model selection and dataset paths.
    Retry an unchanged request with the same run ID; use a new run ID for a new
    attempt. Deterministic job names identify retries; the adapter is not a
    distributed exactly-once lock.
    """

    _REQUIRED = frozenset({"esml_data_date_utc", "esml_model_version", "esml_run_id"})
    _OPTIONAL = frozenset({
        "esml_data_version", "esml_project_name", "esml_environment", "esml_allow_reuse",
    })

    def __init__(self, project: ESMLProject,
                 pipeline_type: PipelineType = PipelineType.IN_2_GOLD_INFERENCE):
        if not isinstance(pipeline_type, PipelineType) or not pipeline_type.is_inference:
            raise ValueError("DataOpsAdapter requires an inference PipelineType")
        self.project = project
        self.pipeline_type = pipeline_type

    def _request(self, parameters: dict) -> PipelineRequest:
        if not isinstance(parameters, dict):
            raise ValueError("ADF parameters must be a JSON object")
        if set(parameters) - self._REQUIRED - self._OPTIONAL:
            raise ValueError("Unsupported ADF parameters; workspace, model selection and paths are server-owned")
        missing = self._REQUIRED - set(parameters)
        if missing:
            raise ValueError("Missing required ADF parameters: " + ", ".join(sorted(missing)))
        expected = {
            "esml_project_name": self.project.settings.project_folder,
            "esml_environment": self.project.settings.scope["environment"],
        }
        for name, value in expected.items():
            if name in parameters and parameters[name] != value:
                raise ValueError(f"{name} differs from the server-selected project")
        if not isinstance(parameters["esml_run_id"], str):
            raise ValueError("esml_run_id must be an explicit string identifier for retries")
        versions = {}
        for name in ("esml_model_version", "esml_data_version"):
            if name in parameters:
                value = identifier(parameters[name], name)
                if value.isdecimal() and int(value) == 0:
                    raise ValueError(f"{name} must be nonzero and immutable")
                versions[name] = value
        return PipelineRequest(
            data_date_utc=parameters["esml_data_date_utc"],
            run_id=parameters["esml_run_id"],
            model_version=versions["esml_model_version"],
            data_version=versions.get("esml_data_version"),
            allow_reuse=parameters.get("esml_allow_reuse", True),
        )

    @staticmethod
    def _response(job: dict) -> dict:
        fields = ("name", "id", "status")
        if not isinstance(job, dict) or any(
            not isinstance(job.get(key), str) or not job[key].strip() for key in fields
        ):
            raise RuntimeError("Backend must return a job with nonempty name, id and status")
        if job["status"] not in _ACTIVE_STATUSES + _SUCCESS_STATUSES + _FAILURE_STATUSES:
            raise RuntimeError("Backend returned an unknown Azure ML job status")
        return {key: job[key] for key in fields}

    def submit(self, parameters: dict) -> dict:
        """Validate the common ADF body and return accepted job metadata, not success."""
        request = self._request(parameters)
        # Function deployment packages may be read-only; upload before removing the bundle.
        with TemporaryDirectory(prefix=".esml-dataops-") as directory:
            plan = self.project.create_pipeline(
                self.pipeline_type, request, output=Path(directory) / "pipeline",
            )
            return self._response(self.project.execute_pipeline(plan))

    def status(self, job_name: str) -> dict:
        """Read once, checking project and pipeline scope before exposing metadata."""
        if not isinstance(job_name, str):
            raise ValueError("job_name must be a safe Azure ML job name")
        identifier(job_name, "job_name")
        job = self.project._backend().get_job(job_name)
        assert_scope(job.get("tags", {}), self.project.settings.scope)
        naming = ESMLNaming(self.project.settings, self.project.settings.model())
        if (job.get("tags", {}).get("esml_pipeline_type") != self.pipeline_type.value
                or job.get("experiment_name") != naming.experiment(self.pipeline_type)):
            raise ValueError("Job differs from the server-selected model or inference pipeline")
        if job.get("name") != job_name:
            raise ValueError("Backend returned a different job")
        return self._response(job)


def _adapter_uri(value: str, field: str, *, schemes: tuple[str, ...]) -> str:
    if (not isinstance(value, str) or not value
            or any(character.isspace() or ord(character) < 32 or character in "'\"\\"
                   for character in value)):
        raise ValueError(f"{field} must be an explicit, safe application URI")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid application URI") from exc
    if (parsed.scheme not in schemes or not parsed.hostname or not parsed.netloc
            or parsed.username is not None or parsed.password is not None
            or "?" in value or "#" in value or port == 0):
        raise ValueError(f"{field} must not contain credentials, query parameters or fragments")
    return value


def adf_pipeline(adapter_url: str, adapter_resource: str, name: str = "esml-inference") -> dict:
    """Build an ADF pipeline resource; never deploy it or acquire credentials.

    ``adapter_url`` is the HTTPS POST route; GET appends the returned job name.
    ``adapter_resource`` is the Entra application ID URI accepted by the adapter,
    not the Azure ML or ARM audience. The Function host must enforce EasyAuth,
    the expected audience and an allowlist containing the calling ADF identity.
    Provide esml_request with esml_data_date_utc, esml_model_version and
    esml_run_id; optional keys use the same DataOpsAdapter contract.
    """
    identifier(name, "pipeline_name")
    adapter_url = _adapter_uri(adapter_url, "adapter_url", schemes=("https",)).rstrip("/")
    adapter_resource = _adapter_uri(adapter_resource, "adapter_resource", schemes=("api", "https"))
    audience_host = urlsplit(adapter_resource).hostname.lower()
    if (audience_host in {"management.azure.com", "management.core.windows.net", "ml.azure.com",
                          "api.azureml.ms", "management.usgovcloudapi.net",
                          "management.chinacloudapi.cn", "ml.azure.us", "ml.azure.cn"}
            or adapter_resource.endswith("/.default")):
        raise ValueError("adapter_resource must identify the adapter's Entra application, not Azure ML or ARM")

    def expression(value):
        return {"value": value, "type": "Expression"}

    def dependency(activity, condition="Succeeded"):
        return {"activity": activity, "dependencyConditions": [condition]}

    def web(activity_name, method, url, *, body=None):
        properties = {
            "method": method, "url": url, "turnOffAsync": True,
            "authentication": {"type": "MSI", "resource": adapter_resource},
            "httpRequestTimeout": "00:10:00",
        }
        if body is not None:
            properties.update(body=body, headers={"Content-Type": "application/json"})
        return {
            "name": activity_name, "type": "WebActivity",
            "policy": {"timeout": "0.00:10:00", "retry": 0, "secureInput": True, "secureOutput": True},
            "typeProperties": properties,
        }

    active = "createArray(" + ",".join(f"'{value}'" for value in _ACTIVE_STATUSES) + ")"
    success = "createArray(" + ",".join(f"'{value}'" for value in _SUCCESS_STATUSES) + ")"
    submit = web("Submit", "POST", adapter_url,
                 body=expression("@string(pipeline().parameters.esml_request)"))
    poll = web("GetStatus", "GET",
               expression(f"@concat('{adapter_url}/', activity('Submit').output.name)"))
    remember_status = {
        "name": "RememberStatus", "type": "SetVariable", "dependsOn": [dependency("GetStatus")],
        "typeProperties": {
            "variableName": "esml_job_status", "value": expression("@activity('GetStatus').output.status"),
        },
    }
    poll_failure = {
        "name": "PollFailed", "type": "SetVariable",
        "dependsOn": [dependency("GetStatus", "Failed")],
        "typeProperties": {"variableName": "esml_job_status", "value": "AdapterError"},
    }
    delay = {
        "name": "PollDelay", "type": "Wait", "dependsOn": [dependency("GetStatus", "Completed")],
        "typeProperties": {"waitTimeInSeconds": 30},
    }
    until = {
        "name": "WaitForInference", "type": "Until", "dependsOn": [dependency("Submit")],
        "typeProperties": {
            "expression": expression(f"@not(contains({active}, variables('esml_job_status')))"),
            "timeout": "0.02:00:00", "activities": [poll, remember_status, poll_failure, delay],
        },
    }
    succeeded = {
        "name": "RequireSuccessfulInference", "type": "IfCondition",
        "dependsOn": [dependency("WaitForInference")],
        "typeProperties": {
            "expression": expression(f"@contains({success}, variables('esml_job_status'))"),
            "ifTrueActivities": [],
            "ifFalseActivities": [{
                "name": "InferenceFailed", "type": "Fail",
                "typeProperties": {
                    "errorCode": "ESML_INFERENCE_FAILED",
                    "message": expression("@concat('Inference did not succeed: ', variables('esml_job_status'))"),
                },
            }],
        },
    }
    return {
        "name": name,
        "properties": {
            "parameters": {"esml_request": {"type": "Object"}},
            "variables": {"esml_job_status": {"type": "String", "defaultValue": "NotStarted"}},
            "activities": [submit, until, succeeded],
        },
    }
