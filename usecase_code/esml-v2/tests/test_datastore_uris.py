import pytest

from azure_esml.base_layer.contracts import WorkspaceTarget
from azure_esml.base_layer.uris import same_data_path


TARGET = WorkspaceTarget("11111111-1111-1111-1111-111111111111",
                         "22222222-2222-2222-2222-222222222222", "project-rg", "workspace")
FULL = f"azureml://subscriptions/{TARGET.subscription_id}/resourcegroups/project-rg/workspaces/workspace/datastores/lake/paths/Project/Gold/"


def test_service_expanded_uri_is_same_exact_workspace_datastore_key():
    assert same_data_path("azureml://datastores/lake/paths/Project/Gold/", FULL, TARGET)


@pytest.mark.parametrize("different", [
    FULL.replace("project-rg", "other-rg"), FULL.replace("/workspace/", "/another/"),
    FULL.replace(TARGET.subscription_id, TARGET.tenant_id), FULL.replace("/lake/", "/other/"),
    FULL.replace("/Gold/", "/gold/"), FULL + "?sig=secret",
    FULL.replace("/Gold/", "/Gold/../other/"),
])
def test_other_scope_case_sensitive_key_or_unsafe_uri_never_matches(different):
    assert not same_data_path("azureml://datastores/lake/paths/Project/Gold/", different, TARGET)
