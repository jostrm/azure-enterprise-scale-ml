"""Optional installed-consumer contract: actual PINK adapter and ProviderState CAS.

Set AIFACTORY_PINK_SOURCE to an explicitly selected PINK source checkout. The
standalone PURPLE suite does not require or fetch an external backend.
"""

import importlib
import os
from pathlib import Path
import copy
import json
import shutil
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from unit.test_lifecycle_admission import Authority, admission, en, request, shared, FACTORY, SCOPE, REPOSITORY


@pytest.fixture
def pink(monkeypatch):
    source = os.environ.get("AIFACTORY_PINK_SOURCE")
    if not source:
        pytest.skip("Explicit separately installed PINK source is not selected")
    path = Path(source).resolve()
    assert (path / "src" / "lifecycle_admission.py").is_file()
    monkeypatch.syspath_prepend(str(path))
    return importlib.import_module("src.lifecycle_admission")


def test_actual_api_adapter_and_pipeline_contend_on_same_provider_transport(shared, pink):
    provider, store = shared
    api = pink.Adapter(admission.Admission(store(), Authority()))
    pipeline = admission.Admission(store(), Authority())
    winner = []
    provider.contender = lambda: winner.append(pipeline.acquire(request("pipeline", "pipeline-job")))
    with pytest.raises(en.EnrollmentError, match="non-fast-forward"):
        api.acquire(Path.cwd(), request())
    assert provider.state()["records"][admission.RECORD]["claim"] == winner[0]
    with pytest.raises(admission.AdmissionError, match="busy"):
        pink.Adapter(admission.Admission(store(), Authority())).acquire(Path.cwd(), request())


def test_actual_api_uncertain_response_is_retained_and_never_automatically_retried(shared, pink):
    provider, store = shared
    api = pink.Adapter(admission.Admission(store(), Authority()))
    provider.uncertain = True
    with pytest.raises(en.EnrollmentError, match="uncertain"):
        api.acquire(Path.cwd(), request())
    claim = provider.state()["records"][admission.RECORD]["claim"]
    assert claim["route"] == "api"
    calls = len(provider.calls)
    with pytest.raises(admission.AdmissionError, match="reconciliation"):
        api.acquire(Path.cwd(), request())
    assert len(provider.calls) == calls


def test_automatic_service_composition_contends_before_any_api_effect(shared, pink, monkeypatch):
    integration = importlib.import_module("src.lifecycle_admission_service")
    catalog = importlib.import_module("src.factory_catalog")
    storage = importlib.import_module("src.catalog_storage")
    provider, store = shared
    workspace = Path.cwd() / ".validation-work" / ("api-composition-" + str(uuid4()))
    root = workspace / "azurefactory"
    (root / ".azurefactory").mkdir(parents=True)
    (root / ".azurefactory" / "lifecycle-admission.json").write_text(json.dumps({
        "protocol": admission.PROTOCOL, "required": True}))
    try:
        document = catalog.empty_document(root)
        document["factories"] = [{"id": FACTORY, "key": "fixture-factory", "kind": "ai",
                                  "prefix": "test-", "region": "swedencentral", "default_orchestrator": "gha",
                                  "status": "configured", "scale_sets": [], "projects": []}]
        document["configurations"][FACTORY] = {"factory": {}, "scale_sets": {}, "projects": {}, "variables": {}}
        catalog.validate_document(document)
        (root / "register.json").write_text(json.dumps(document))
        state = provider.state()
        state["records"][admission.RECORD] = admission.new_record(
            state["records"][admission.RECORD]["policy"], {FACTORY: document})
        provider.set_state(state)
        selected = SimpleNamespace(store=store(), factory_id=FACTORY, scopes=[SCOPE], repository=REPOSITORY)
        selected.coordinator = admission.Admission(selected.store, Authority())
        monkeypatch.setattr(integration, "backend", lambda *args: selected)
        revision = catalog.source_revision(root)
        with storage.database(root) as db:
            db.execute("INSERT INTO confirmations VALUES(?,?,?,?,?,?)", ("confirmation", "owner", time.time() + 60,
                       revision, json.dumps({"request": {"factory_id": FACTORY, "action": "configure-settings"},
                                                   "preview": {"can_execute": True}}), 0))
        effects = []

        class Service:
            clock = staticmethod(time.time)

            @integration.api_mutation("catalog")
            def confirm(self, folder, confirmation_id, owner):
                effects.append("write")

        pipeline = admission.Admission(store(), Authority())
        provider.contender = lambda: pipeline.acquire({
            **request("pipeline", "pipeline-job"), "configuration_revision": admission.revision(document)})
        with pytest.raises(en.EnrollmentError, match="non-fast-forward"):
            Service().confirm(str(root), "confirmation", "owner")
        assert effects == []
        assert provider.state()["records"][admission.RECORD]["claim"]["route"] == "pipeline"
        assert json.loads((root / "register.json").read_text()) == document
        assert sum(method == "PATCH" for method, _, _ in provider.calls) == 2
        with storage.database(root) as db:
            assert db.execute("SELECT consumed FROM confirmations WHERE id='confirmation'").fetchone()[0] == 0
    finally:
        shutil.rmtree(workspace)
