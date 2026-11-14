from pathlib import Path
from unittest.mock import Mock

import pytest

from azure_esml.base_layer import AzureMLSDKBackend, WorkspaceTarget


TARGET = WorkspaceTarget("11111111-1111-1111-1111-111111111111",
                         "22222222-2222-2222-2222-222222222222", "project-rg", "workspace")


def adapter():
    client = Mock()
    return AzureMLSDKBackend(TARGET, client=client), client


def test_sdk_download_requires_real_files(tmp_path):
    backend, client = adapter()
    def download(*, name, download_path, output_name):
        assert name == "job" and output_name == "report"
        folder = Path(download_path) / "named-outputs" / output_name
        folder.mkdir(parents=True)
        (folder / "quality-gate.json").write_text('{"passed": true}')
    client.jobs.download.side_effect = download
    destination = tmp_path / "download"
    backend.download_job("job", destination, "report")
    assert (destination / "named-outputs" / "report" / "quality-gate.json").is_file()


def test_sdk_empty_download_never_reports_success(tmp_path):
    backend, _ = adapter()
    with pytest.raises(RuntimeError, match="downloaded no files"):
        backend.download_job("job", tmp_path / "download", "report")


def test_sdk_download_errors_propagate_without_another_transport(tmp_path):
    backend, client = adapter()
    client.jobs.download.side_effect = PermissionError("denied")
    with pytest.raises(PermissionError, match="denied"):
        backend.download_job("job", tmp_path / "download", "report")
