import subprocess
from unittest.mock import Mock

import pytest
from azure.core.exceptions import ResourceNotFoundError

from azure_esml.base_layer import AzureMLCLIBackend, WorkspaceTarget


TARGET = WorkspaceTarget("11111111-1111-1111-1111-111111111111",
                         "22222222-2222-2222-2222-222222222222", "rg", "workspace")


@pytest.mark.parametrize("message", [
    "ERROR: (UserError) Job expected-job not found.\nCode: UserError\n",
    "ERROR: (ResourceNotFound) Missing\n",
    "ERROR: (UserError) Asset lookup failed\nError Code: UserError/NotFoundError\n",
])
def test_cli_missing_job_uses_same_exception_as_sdk(message):
    runner = Mock(side_effect=subprocess.CalledProcessError(3, ["az"], stderr=message))
    backend = AzureMLCLIBackend(TARGET, runner)
    backend._checked = True
    with pytest.raises(ResourceNotFoundError):
        backend.get_job("expected-job")


@pytest.mark.parametrize("message", [
    "ERROR: (AuthorizationFailed) permission denied",
    "ERROR: resource missing or permission denied",
    "ERROR: (UserError) Job a-different-job not found.",
])
def test_cli_other_errors_never_look_like_safe_absence(message):
    error = subprocess.CalledProcessError(3, ["az"], stderr=message)
    backend = AzureMLCLIBackend(TARGET, Mock(side_effect=error))
    backend._checked = True
    with pytest.raises(subprocess.CalledProcessError) as caught:
        backend.get_job("expected-job")
    assert caught.value is error


@pytest.mark.parametrize("suffix", ["", " (version: 1)"])
def test_cli_component_absence_requires_the_exact_requested_name(suffix):
    error = subprocess.CalledProcessError(
        3, ["az"], stderr=f"ERROR: (UserError) Not found component inference{suffix}.\nCode: UserError\n")
    backend = AzureMLCLIBackend(TARGET, Mock(side_effect=error))
    backend._checked = True
    assert backend._get_optional("component", "--name", "inference", "--version", "1") is None
    with pytest.raises(subprocess.CalledProcessError):
        backend._get_optional("component", "--name", "different", "--version", "1")
    if suffix:
        with pytest.raises(subprocess.CalledProcessError):
            backend._get_optional("component", "--name", "inference", "--version", "2")
