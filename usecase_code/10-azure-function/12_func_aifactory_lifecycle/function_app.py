"""Azure Functions entry point (Python v2 model). Thin on purpose: every route forwards to aif_lifecycle.

Lifecycle routes need a function key (AuthLevel.FUNCTION); add App Service authentication with an Entra app role
before real deployments. The events and runner-results routes are anonymous but HMAC-checked (X-Hub-Signature-256).
"""

import functools
import json
import logging
import os
from urllib.parse import urlsplit

import azure.functions as func

from aif_lifecycle.composition import build_runtime
from aif_lifecycle.domain.errors import ConfigurationInvalid, InvalidSignature, LifecycleError
from aif_lifecycle.http_api import ApiRequest
from aif_lifecycle.problem import PROBLEM_MEDIA_TYPE, problem_document

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
log = logging.getLogger("aif_lifecycle")


@functools.lru_cache(maxsize=1)
def runtime():
    return build_runtime()


def _forward(handler: str, req: func.HttpRequest) -> func.HttpResponse:
    path = urlsplit(req.url).path
    try:
        api = runtime().api
    except LifecycleError as error:
        log.error("configuration invalid: %s", error.detail)
        document = problem_document(ConfigurationInvalid(error.detail), correlation_id="startup", instance=path)
        return func.HttpResponse(body=json.dumps(document), status_code=503, mimetype=PROBLEM_MEDIA_TYPE)
    request = ApiRequest(method=req.method, path=path, route_params=dict(req.route_params),
                         headers={key.lower(): value for key, value in req.headers.items()}, body=req.get_body() or b"")
    response = getattr(api, handler)(request)
    headers = dict(response.headers)
    media_type = headers.pop("Content-Type", "application/json")
    return func.HttpResponse(body=response.body, status_code=response.status, headers=headers, mimetype=media_type)


@app.route(route="v1/health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("health", req)


@app.route(route="v1/lifecycle/{scenario}/prepare", methods=["POST"])
def prepare(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("prepare", req)


@app.route(route="v1/operations", methods=["GET"])
def list_operations(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("list_operations", req)


@app.route(route="v1/operations/{operation_id}", methods=["GET"])
def get_operation(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("get_operation", req)


@app.route(route="v1/operations/{operation_id}/confirm", methods=["POST"])
def confirm(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("confirm", req)


@app.route(route="v1/github/events", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def github_events(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("github_events", req)


@app.route(route="v1/runner/results", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def runner_results(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("runner_results", req)


@app.route(route="v1/catalog/refresh", methods=["POST"])
def refresh_catalog(req: func.HttpRequest) -> func.HttpResponse:
    return _forward("refresh_catalog", req)


@app.timer_trigger(schedule="0 */2 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def reconcile(timer: func.TimerRequest) -> None:
    log.info("reconcile %s", runtime().service.reconcile())


if os.environ.get("AIF_EVENT_PROCESSING", "inline").strip().lower() == "queue":
    from aif_lifecycle.adapters.queue import decode

    @app.queue_trigger(arg_name="message", queue_name=os.environ.get("AIF_EVENT_QUEUE", "aif-github-events"),
                       connection="AzureWebJobsStorage")
    def process_event(message: func.QueueMessage) -> None:
        try:
            log.info("queued event %s", runtime().api.process_queued(decode(message.get_body())))
        except InvalidSignature:
            log.warning("dropped a queued event that this Function did not sign (message id %s)", message.id)
