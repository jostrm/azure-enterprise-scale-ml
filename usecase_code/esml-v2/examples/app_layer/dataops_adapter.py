"""Azure Functions v2 route replacing the SDK v1 ADF ExecutePipeline activity.

Install azure-functions in the Function host, then expose ``app = create_app(
server_settings_path, backend=server_backend)`` from its function_app.py. Select
the settings and scoped SDK v2/CLI v2 backend on the server, never from HTTP input.
No Azure connection or submission occurs merely by importing this example.

ADF POST /api/esml/inference sends the same body for one or many datasets:
    {"esml_data_date_utc": "2026-09-13", "esml_model_version": "7",
     "esml_run_id": "<ADF pipeline().RunId>"}
Use the caller's UTC processing date, not the Function's current date. Optional
keys are esml_data_version, esml_project_name, esml_environment, esml_allow_reuse.
Keep the same body/run ID on transport retries; a new attempt needs a new run ID.

The 202 response is acceptance only. Poll GET /api/esml/inference/{name} using an
ADF Until + Wait loop with a finite timeout; only Completed/Succeeded is success.
Fail on Failed/Canceled/Cancelled, and do not interpret unknown states as success.
By default routes require a Function key. For the generated ADF MSI Web activities,
use create_app(..., entra_protected=True) ONLY after configuring host EasyAuth to
require authentication, validate the adapter application's audience, and restrict
allowed callers to the ADF managed identity. The routes are then ANONYMOUS only at
the Functions layer, behind mandatory host authentication. The flag neither
configures nor deploys EasyAuth. Never expose those routes without that protection,
disable network restrictions, or put keys/workspace settings in the request body.
Render bundles use the host's writable temporary storage, not its deployed package.
"""

import json
from pathlib import Path

from azure_esml.base_layer.contracts import MLBackend
from azure_esml.domain_layer.dataops import DataOpsAdapter
from azure_esml.domain_layer.project import ESMLProject


def create_app(settings_path: str | Path, *, backend: MLBackend, entra_protected: bool = False):
    """Construct routes for one fixed project; the caller owns host authentication."""
    if type(entra_protected) is not bool:
        raise ValueError("entra_protected must be an explicit boolean")
    import azure.functions as func

    adapter = DataOpsAdapter(ESMLProject.from_json(settings_path, backend=backend))
    auth_level = func.AuthLevel.ANONYMOUS if entra_protected else func.AuthLevel.FUNCTION
    app = func.FunctionApp(http_auth_level=auth_level)

    def response(body, code):
        return func.HttpResponse(json.dumps(body), status_code=code, mimetype="application/json")

    @app.route(route="esml/inference", methods=["POST"])
    def submit_inference(req):
        try:
            parameters = req.get_json()
        except ValueError:
            return response({"error": "Request body must be a JSON object"}, 400)
        try:
            job = adapter.submit(parameters)
        except ValueError:
            return response({"error": "Invalid inference request or server-selected scope"}, 400)
        return response(job, 202)

    @app.route(route="esml/inference/{job_name}", methods=["GET"])
    def inference_status(req):
        try:
            job = adapter.status(req.route_params["job_name"])
        except ValueError:
            return response({"error": "Job is not valid for this inference route"}, 400)
        return response(job, 200)

    return app
