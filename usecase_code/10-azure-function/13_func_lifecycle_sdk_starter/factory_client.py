"""The Factory API client: the real azurefactory SDK, or a mock with the same method names and reply shapes.

AIF_BACKEND=mock (default) returns MockFactoryClient; AIF_BACKEND=sdk returns azurefactory.AzureFactoryClient.
lifecycle.py only calls the methods below, so switching to the real API changes nothing else.
"""

import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone


class MockApiError(Exception):
    """Shaped like azurefactory.errors.APIError: a message and an HTTP status."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class MockFactoryClient:
    """A Factory API in memory: one factory (scale set dev/001 with project001) and pink's two-step semantics."""

    name = "mock"

    def __init__(self, prefix="aif-130-", region="swedencentral", region_short="sdc", review_minutes=10):
        self._review = timedelta(minutes=review_minutes)
        self._pending, self._jobs = {}, {}
        scale_set = str(uuid.uuid4())
        self._catalog = {"factories": [{
            "id": str(uuid.uuid4()), "key": f"{prefix}{region}", "prefix": prefix, "region": region,
            "region_short_name": region_short,
            "scale_sets": [{"id": scale_set, "environment": "dev", "suffix": "001", "status": "deployed"}],
            "projects": [{"id": str(uuid.uuid4()), "key": "project-001", "number": "001", "settings": {},
                          "placements": [{"environment": "dev", "scale_set_id": scale_set}]}],
        }]}

    # ----- reads -----

    def health(self):
        return {"status": "ok"}

    def catalog_list(self, folder):
        text = json.dumps(self._catalog["factories"], sort_keys=True)
        return {**copy.deepcopy(self._catalog), "revision": hashlib.sha256(text.encode()).hexdigest()}

    def catalog_job(self, folder, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            raise MockApiError(404, "Unknown job.")
        job["status"] = {"queued": "running", "running": "succeeded"}.get(job["status"], job["status"])
        return copy.deepcopy(job)

    # ----- prepare: a review that changes nothing -----

    def project_add_prepare(self, folder, factory_id, *, number, display_name="", placements=None,
                            environments=None, settings=None, expected_revision=None):
        body = {"folder": folder, "action": "add-project", "factory_id": factory_id, "expected_revision": expected_revision,
                "project": {"number": number, "display_name": display_name, "placements": placements or [],
                            "settings": settings or {}}}
        return self._prepare(body, f"Add project {number} to the catalog (configuration only, no Azure change).")

    def catalog_settings_prepare(self, folder, factory_id, settings, *, scale_set_id=None, project_id=None,
                                 expected_revision=None):
        body = {"folder": folder, "action": "configure-settings", "factory_id": factory_id, "settings": settings,
                "scale_set_id": scale_set_id, "project_id": project_id, "expected_revision": expected_revision}
        return self._prepare(body, f"Change the settings {', '.join(sorted(settings))} (configuration only, no Azure change).")

    def catalog_prepare(self, body):
        if body.get("action") != "deploy":
            raise MockApiError(400, f"The mock only deploys, not {body.get('action')}.")
        return self._prepare(dict(body), "Deploy the project's resource group.")

    def _prepare(self, body, summary):
        if body.get("expected_revision") not in (None, self.catalog_list(body["folder"])["revision"]):
            raise MockApiError(409, "The catalog revision changed; refresh and prepare again.")
        confirmation_id = str(uuid.uuid4())
        self._pending[confirmation_id] = body
        expires = (datetime.now(timezone.utc) + self._review).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"contract_version": 1, "confirmation_id": confirmation_id, "can_execute": True, "blockers": [],
                "summary": summary, "effects": [], "warnings": [], "expires_at": expires, "action": body["action"]}

    # ----- confirm: the one call that changes something -----

    def catalog_confirm(self, folder, confirmation_id):
        body = self._pending.pop(confirmation_id, None)
        if body is None:
            raise MockApiError(409, "Unknown or already used confirmation.")
        factory = next(f for f in self._catalog["factories"] if f["id"] == body["factory_id"])
        job = None
        if body["action"] == "add-project":
            factory["projects"].append({"id": str(uuid.uuid4()), "key": f"project-{body['project']['number']}",
                                        "number": body["project"]["number"], "settings": body["project"]["settings"],
                                        "placements": body["project"]["placements"]})
        elif body["action"] == "configure-settings":
            project = next(p for p in factory["projects"] if p["id"] == body["project_id"])
            project["settings"].update(body["settings"])
        else:
            job = {"id": str(uuid.uuid4()), "action": "deploy", "status": "queued", "pipeline_runs": []}
            self._jobs[job["id"]] = job
        return {"contract_version": 1, "catalog": self.catalog_list(folder), "job": copy.deepcopy(job)}


def make_client(env=None):
    """AIF_BACKEND picks the client; the key comes only from the environment (or Key Vault in Azure)."""
    env = os.environ if env is None else env
    backend = (env.get("AIF_BACKEND") or "mock").strip().lower()
    if backend == "mock":
        return MockFactoryClient()
    if backend == "sdk":
        from azurefactory import AzureFactoryClient
        return AzureFactoryClient(base_url=env.get("AIF_FACTORY_API_URL") or "http://127.0.0.1:8765",
                                  api_key=env.get("AIF_FACTORY_API_KEY"),
                                  timeout=float(env.get("AIF_FACTORY_API_TIMEOUT_SECONDS") or 540))
    raise ValueError("AIF_BACKEND must be mock or sdk.")
