"""Read-only export uses the configured API; fixtures contain only synthetic config."""

import base64
import io
import json
import shutil
import stat
import uuid
import zipfile
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from azurefactory import esaf
from azurefactory.client import AzureFactoryClient
from azurefactory.errors import APIError, ConfigError


FOLDER = r"C:\synthetic\azurefactory"
ROUTE = "/api/v1/esaf/export-allowed-projects"
LOCK = {"allowed-azurefactory-names": ["spider-001"], "allowed-project-numbers": ["001", "003"]}


def archive(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, value in (entries or {
            "azurefactory/register.json": b'{"factories":[]}',
            "azurefactory/project-lock.json": json.dumps(LOCK).encode(),
        }).items():
            zipped.writestr(name, value)
    return output.getvalue()


def envelope(zip_bytes=None):
    return {
        "contract_version": 1,
        "file_name": "spider-001-projects.zip",
        "zip_base64": base64.b64encode(archive() if zip_bytes is None else zip_bytes).decode(),
        "allowed_azurefactory_names": ["spider-001"],
        "allowed_project_numbers": ["001", "003"],
    }


def selected_envelope(projects, factory="spider-001"):
    lock = {"allowed-azurefactory-names": [factory], "allowed-project-numbers": projects}
    response = envelope(archive({
        "azurefactory/register.json": b"{}",
        "azurefactory/project-lock.json": json.dumps(lock).encode(),
    }))
    response["allowed_azurefactory_names"] = [factory]
    response["allowed_project_numbers"] = projects
    return response


@pytest.fixture
def api(monkeypatch):
    state = {"response": envelope(), "requests": [], "reads": [], "status": 200}
    monkeypatch.setattr(esaf, "_default", None)

    class Response(io.BytesIO):
        headers = Message()
        headers["Content-Type"] = "application/json"

        def read(self, size=-1):
            state["reads"].append(size)
            return super().read(size)

    class Opener:
        def open(self, request, timeout):
            state["requests"].append(request)
            data = json.dumps(state["response"]).encode()
            if state["status"] != 200:
                raise HTTPError(request.full_url, state["status"], "Rejected", {}, io.BytesIO(data))
            return Response(data)

    monkeypatch.setattr("azurefactory.client.build_opener", lambda *args: Opener())
    state["client"] = AzureFactoryClient("http://127.0.0.1:8766", "synthetic-key")
    state["session"] = esaf.connect(folder=FOLDER, factory="ignored-session-default", client=state["client"])
    return state


@pytest.mark.parametrize("entry", ["module", "session", "explicit-session", "client", "environment"])
def test_export_is_one_authenticated_post_and_returns_bytes_without_a_job(api, entry, monkeypatch):
    projects = ["001", "003"]
    if entry == "module":
        package = esaf.export_allowed_projects("spider-001", projects)
    elif entry == "session":
        package = api["session"].export_allowed_projects("spider-001", projects)
    elif entry == "explicit-session":
        monkeypatch.setattr(esaf, "_default", None)
        package = esaf.export_allowed_projects("spider-001", projects, session=api["session"])
    elif entry == "client":
        package = api["client"].esaf_export_allowed_projects(FOLDER, "spider-001", projects)
    else:
        monkeypatch.setattr(esaf, "_default", None)
        monkeypatch.setenv("ESAF_FOLDER", FOLDER)
        monkeypatch.setattr(esaf, "AzureFactoryClient", lambda **kwargs: api["client"])
        package = esaf.export_allowed_projects("spider-001", projects)
    assert isinstance(package, esaf.EsafExportPackage)
    assert package.file_name == "spider-001-projects.zip"
    assert package.zip_bytes == base64.b64decode(api["response"]["zip_base64"])
    assert package.allowed_azurefactory_names == ("spider-001",)
    assert package.allowed_project_numbers == ("001", "003")
    assert package.contract_version == 1
    assert projects == ["001", "003"]
    assert len(api["requests"]) == 1
    request = api["requests"][0]
    assert request.method == "POST"
    assert request.full_url == api["client"].base_url + ROUTE
    assert request.get_header("X-api-key") == "synthetic-key"
    assert json.loads(request.data) == {"folder": FOLDER, "factory": "spider-001", "project_numbers": projects}
    assert 0 < api["reads"][0] <= 24 * 1024 * 1024 + 1
    assert "export_allowed_projects" in esaf.__all__
    assert "EsafExportPackage" in esaf.__all__


@pytest.mark.parametrize("factory,projects", [
    ("", ["001"]), ("../factory", ["001"]), ("factory\n", ["001"]), (None, ["001"]),
    ("Spider Factory", ["001"]), ("Spider-001", ["001"]), ("factory_name", ["001"]),
    ("a" * 129, ["001"]), ("a", ["001"]), ("0factory", ["001"]),
    ("spider-001", []), ("spider-001", "001"), ("spider-001", [1]),
    ("spider-001", ["1"]), ("spider-001", ["0001"]), ("spider-001", ["٠٠١"]),
    ("spider-001", ["001", "001"]), ("spider-001", ["../001"]), ("spider-001", None),
    ("spider-001", [f"{number:03d}" for number in range(1, 202)]),
])
def test_invalid_identifiers_fail_before_http(api, factory, projects):
    with pytest.raises(ConfigError):
        esaf.export_allowed_projects(factory, projects)
    assert api["requests"] == []


@pytest.mark.parametrize("field,value", [
    ("contract_version", 2), ("contract_version", True), ("contract_version", "1"),
    ("file_name", "../export.zip"), ("file_name", r"C:\export.zip"), ("file_name", "/export.zip"),
    ("file_name", "export.zip:payload"), ("file_name", "export.zip\n"), ("file_name", "CON.zip"),
    ("file_name", "export.txt"), ("zip_base64", "%%%"), ("zip_base64", "AA==="),
    ("zip_base64", ""), ("zip_base64", 42),
    ("allowed_azurefactory_names", []), ("allowed_azurefactory_names", ["spider-001", "other"]),
    ("allowed_azurefactory_names", ["../factory"]), ("allowed_azurefactory_names", "spider-001"),
    ("allowed_project_numbers", ["001"]), ("allowed_project_numbers", ["001", "003", "007"]),
    ("allowed_project_numbers", ["001", "001"]), ("allowed_project_numbers", [1, 3]),
])
def test_bad_response_contract_is_rejected(api, field, value):
    api["response"][field] = value
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])
    assert len(api["requests"]) == 1


@pytest.mark.parametrize("missing", list(envelope()))
def test_missing_contract_fields_are_rejected(api, missing):
    del api["response"][missing]
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


@pytest.mark.parametrize("payload", [[], None, {"job_id": "not-an-export"}, envelope(b"not a zip")])
def test_non_export_payloads_are_rejected(api, payload):
    api["response"] = payload
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


@pytest.mark.parametrize("name", ["../escape", "/absolute", r"azurefactory\escape", "azurefactory/../escape",
                                "azurefactory/C:escape", "azurefactory/CON.json", "other/file.json"])
def test_unsafe_archive_paths_are_rejected_without_extracting(api, name):
    api["response"] = envelope(archive({name: b"bad"}))
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


def test_archive_lock_must_match_metadata_exactly(api):
    wrong = {**LOCK, "extra": True}
    api["response"] = envelope(archive({
        "azurefactory/register.json": b"{}",
        "azurefactory/project-lock.json": json.dumps(wrong).encode(),
    }))
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


def test_duplicate_project_lock_keys_are_rejected(api):
    duplicate = json.dumps(LOCK)[:-1] + ', "allowed-project-numbers": ["001", "003"]}'
    api["response"] = envelope(archive({
        "azurefactory/register.json": b"{}",
        "azurefactory/project-lock.json": duplicate.encode(),
    }))
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


@pytest.mark.parametrize("kind", ["symlink", "duplicate", "crc", "unsupported-compression"])
def test_bad_archive_entries_are_rejected(api, kind):
    buffer = io.BytesIO(archive())
    with zipfile.ZipFile(buffer, "a") as zipped:
        if kind == "symlink":
            entry = zipfile.ZipInfo("azurefactory/link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            zipped.writestr(entry, "../outside")
        elif kind == "duplicate":
            zipped.writestr("azurefactory/REGISTER.json", b"{}")
        elif kind == "unsupported-compression":
            zipped.writestr("azurefactory/config.json", b"{}", compress_type=zipfile.ZIP_BZIP2)
        else:
            zipped.writestr("azurefactory/config.json", b"uncorrupted", compress_type=zipfile.ZIP_STORED)
    data = buffer.getvalue()
    if kind == "crc":
        data = data.replace(b"uncorrupted", b"corrupted!!")
    api["response"] = envelope(data)
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


@pytest.mark.parametrize("factory_id", [
    "a3d973a6-1906-4eaf-9285-6da9335de5c8",
    "13d973a6-1906-4eaf-9285-6da9335de5c8",
])
def test_factory_id_can_resolve_to_a_canonical_key(api, factory_id):
    package = esaf.export_allowed_projects(factory_id, ["003", "001"])
    assert package.allowed_azurefactory_names == ("spider-001",)


@pytest.mark.parametrize("projects", [
    ["000", "999"],
    [f"{number:03d}" for number in range(200)],
])
def test_export_accepts_existing_project000_and_up_to200_exact_selections(api, projects):
    api["response"] = selected_envelope(projects)
    package = esaf.export_allowed_projects("spider-001", list(reversed(projects)))
    assert package.allowed_project_numbers == tuple(projects)
    assert len(api["requests"]) == 1


def test_response_project_count_is_bounded_even_when_selection_matches():
    from azurefactory.export_package import parse_export

    projects = [f"{number:03d}" for number in range(1, 202)]
    with pytest.raises(APIError):
        parse_export(selected_envelope(projects), projects)


@pytest.mark.parametrize("factory", [
    "Spider-001", "factory_name", "a", "0factory", "a" * 81,
    "13d973a6-1906-4eaf-9285-6da9335de5c8",
])
def test_response_factory_must_be_a_canonical_catalog_key(api, factory):
    api["response"] = selected_envelope(["001", "003"], factory)
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


@pytest.mark.parametrize("bound", ["MAX_ZIP_BYTES", "MAX_EXPANDED_BYTES", "MAX_RESPONSE_BYTES"])
def test_export_size_bounds_are_enforced(api, monkeypatch, bound):
    monkeypatch.setattr("azurefactory.export_package." + bound, 8)
    with pytest.raises(APIError):
        esaf.export_allowed_projects("spider-001", ["001", "003"])


@pytest.mark.parametrize("status", [401, 403, 404, 405, 409, 422, 500, 503])
def test_api_errors_never_retry_poll_or_fall_back(api, status):
    api["status"] = status
    api["response"] = {"detail": "Unavailable"}
    with pytest.raises(APIError) as raised:
        esaf.export_allowed_projects("spider-001", ["001", "003"])
    assert raised.value.status == status
    assert len(api["requests"]) == 1


def test_missing_export_route_names_the_missing_capability(api):
    api["status"] = 404
    api["response"] = {"detail": "Not Found"}
    with pytest.raises(ConfigError, match="/api/v1/esaf/export-allowed-projects"):
        esaf.export_allowed_projects("spider-001", ["001", "003"])
    assert len(api["requests"]) == 1


def test_error_body_is_bounded_too(api, monkeypatch):
    monkeypatch.setattr("azurefactory.export_package.MAX_RESPONSE_BYTES", 8)
    api["status"] = 500
    api["response"] = {"detail": "x" * 100}
    with pytest.raises(APIError, match="size") as raised:
        esaf.export_allowed_projects("spider-001", ["001", "003"])
    assert raised.value.status == 500


def test_save_is_explicit_and_does_not_overwrite(api):
    directory = Path.cwd() / ("export-test-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        package = esaf.export_allowed_projects("spider-001", ["001", "003"])
        assert list(directory.iterdir()) == []
        destination = directory / package.file_name
        assert package.save(destination) == destination
        assert destination.read_bytes() == package.zip_bytes
        with pytest.raises(FileExistsError):
            package.save(destination)
        assert destination.read_bytes() == package.zip_bytes
    finally:
        shutil.rmtree(directory)
