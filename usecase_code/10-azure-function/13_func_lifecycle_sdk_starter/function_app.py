"""Azure Functions entry point (Python v2 model). Thin on purpose: every route forwards to lifecycle.py."""

import functools
import json
import os

import azure.functions as func

from factory_client import make_client
from lifecycle import Lifecycle, Problem

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)  # every route needs the function key...


@functools.lru_cache(maxsize=1)
def lifecycle():
    return Lifecycle(make_client(), os.environ.get("AIF_FACTORY_FOLDER") or "")


def _answer(run, status=200, accepted=False):
    try:
        body = run()
    except Problem as problem:
        document = {"type": "about:blank", "status": problem.status, "code": problem.code, "detail": problem.detail}
        return func.HttpResponse(json.dumps(document), status_code=problem.status, mimetype="application/problem+json")
    headers = {"Location": f"/api/v1/operations/{body['operationId']}", "Retry-After": "5"} if accepted else {}
    return func.HttpResponse(json.dumps(body), status_code=202 if accepted else status, headers=headers,
                             mimetype="application/json")


def _json(req):
    try:
        return req.get_json() if req.get_body() else {}
    except ValueError:
        raise Problem(400, "invalid-json", "The request body is not valid JSON.") from None


@app.route(route="v1/health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)  # ...except health
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _answer(lambda: lifecycle().health())


@app.route(route="v1/lifecycle/{scenario}/prepare", methods=["POST"])
def prepare(req: func.HttpRequest) -> func.HttpResponse:
    return _answer(lambda: lifecycle().prepare(req.route_params["scenario"], _json(req)), accepted=True)


@app.route(route="v1/operations", methods=["GET"])
def list_operations(req: func.HttpRequest) -> func.HttpResponse:
    return _answer(lambda: lifecycle().list())


@app.route(route="v1/operations/{operation_id}", methods=["GET"])
def get_operation(req: func.HttpRequest) -> func.HttpResponse:
    return _answer(lambda: lifecycle().get(req.route_params["operation_id"]))


@app.route(route="v1/operations/{operation_id}/confirm", methods=["POST"])
def confirm(req: func.HttpRequest) -> func.HttpResponse:
    return _answer(lambda: lifecycle().confirm(req.route_params["operation_id"], _json(req)), accepted=True)
