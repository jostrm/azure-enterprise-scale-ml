"""Settings come from app settings (environment) and one composition root wires the adapters."""

import pytest

from aif_lifecycle.composition import build_runtime
from aif_lifecycle.domain.errors import ProtectedTarget, ValidationFailed
from aif_lifecycle.settings import Settings

SELF = "spider-esml-project001-sdc-dev-001-rg"


def test_defaults_are_the_local_mock_loop():
    settings = Settings.from_env({})
    assert (settings.backend, settings.executor, settings.store) == ("mock", "inprocess", "memory")
    assert settings.factory_api_url == "http://127.0.0.1:8765"
    assert settings.event_processing == "inline"


def test_secrets_support_rotation_and_never_appear_in_repr():
    settings = Settings.from_env({"AIF_EVENT_SECRET": "new-secret,old-secret", "AIF_GITHUB_TOKEN": "ghp_hidden",
                                  "AIF_FACTORY_API_KEY": "api-hidden"})
    assert settings.event_secrets == [b"new-secret", b"old-secret"]
    text = repr(settings)
    assert "ghp_hidden" not in text and "new-secret" not in text and "api-hidden" not in text


def test_protected_ids_start_with_the_functions_own_project():
    settings = Settings.from_env({"AIF_SELF_PROJECT_ID": SELF, "AIF_PROTECTED_IDS": "spider-sdc-dev-001, ,"})
    assert settings.protected_ids == [SELF, "spider-sdc-dev-001"]


@pytest.mark.parametrize("env", [
    {"AIF_BACKEND": "soap"},
    {"AIF_EXECUTOR": "magic"},
    {"AIF_STORE": "redis"},
    {"AIF_STORE": "table"},
    {"AIF_BACKEND": "rest"},
    {"AIF_EXECUTOR": "github-dummy"},
    {"AIF_EXECUTOR": "github-dummy", "AIF_GITHUB_REPOSITORY": "o/r", "AIF_GITHUB_TOKEN": "t", "AIF_BACKEND": "rest",
     "AIF_FACTORY_FOLDER": "C:/f"},
    {"AIF_EVENT_PROCESSING": "queue"},
    {"AIF_POLL_AFTER_SECONDS": "soon"},
    {"AIF_EXECUTOR": "github-runner", "AIF_BACKEND": "rest", "AIF_GITHUB_REPOSITORY": "o/r", "AIF_GITHUB_TOKEN": "t"},
    {"AIF_REQUIRED_ROLE": "Lifecycle.Operator"},  # without App Service authentication the principal header is forgeable
])
def test_invalid_settings_fail_fast(env):
    with pytest.raises(ValidationFailed):
        Settings.from_env(env)


def test_a_required_role_needs_app_service_authentication_on_the_app():
    settings = Settings.from_env({"AIF_REQUIRED_ROLE": "Lifecycle.Operator", "WEBSITE_AUTH_ENABLED": "True"})
    assert settings.required_role == "Lifecycle.Operator"
    assert Settings.from_env({}).required_role is None


@pytest.mark.parametrize("name", ["AIF_EVENT_SECRET", "AIF_GITHUB_TOKEN", "AIF_FACTORY_API_KEY"])
def test_an_unresolved_key_vault_reference_fails_closed(name):
    with pytest.raises(ValidationFailed) as error:
        Settings.from_env({name: "@Microsoft.KeyVault(VaultName=kv;SecretName=s)"})
    assert name in error.value.detail


class FakeVault:
    def __init__(self, values):
        self.values = values
        self.asked = []

    def get(self, name):
        self.asked.append(name)
        return self.values[name]


def test_secrets_can_be_read_from_key_vault_by_name():
    vault = FakeVault({"aif-event-secret": "from-vault", "aif-github-token": "ghp_vault"})
    settings = Settings.from_env({"AIF_KEY_VAULT_NAME": "kv-p001-sdc-dev-bltsc01",
                                  "AIF_EVENT_SECRET_NAME": "aif-event-secret",
                                  "AIF_GITHUB_TOKEN_NAME": "aif-github-token"}, vault=vault)
    assert settings.event_secrets == [b"from-vault"]
    assert settings.github_token == "ghp_vault"
    assert vault.asked == ["aif-event-secret", "aif-github-token"]


def test_secret_names_need_a_key_vault():
    with pytest.raises(ValidationFailed):
        Settings.from_env({"AIF_EVENT_SECRET_NAME": "aif-event-secret"})


def test_build_runtime_wires_the_mock_loop_with_self_protection():
    runtime = build_runtime({"AIF_SELF_PROJECT_ID": SELF})
    assert runtime.service.health()["backend"] == "mock"
    with pytest.raises(ProtectedTarget):
        runtime.service.prepare("delete-project", {"projectId": SELF})


def test_build_runtime_wires_the_github_dummy_executor_without_network():
    runtime = build_runtime({"AIF_EXECUTOR": "github-dummy", "AIF_GITHUB_REPOSITORY": "jostrm/byor-121",
                             "AIF_GITHUB_TOKEN": "t"})
    assert runtime.service.health()["executor"] == "github-dummy"


@pytest.mark.parametrize("backend", ["rest", "sdk"])
def test_build_runtime_selects_the_rest_or_sdk_backend(backend):
    runtime = build_runtime({"AIF_BACKEND": backend, "AIF_FACTORY_FOLDER": "C:/repos/byor-121/azurefactory",
                             "AIF_FACTORY_API_KEY": "k"})
    assert runtime.service.health()["backend"] == backend


def test_the_file_store_keeps_state_between_runtimes(tmp_path):
    env = {"AIF_STORE": "file", "AIF_STORE_PATH": str(tmp_path / "state.json")}
    created = build_runtime(env).service.prepare("init-factory", {"factoryId": "aif-121-sdc-dev"})
    assert build_runtime(env).service.get(created.id).status.value == "awaiting_confirmation"
