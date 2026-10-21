"""Option 2: the Factory API through the `azurefactory` Python SDK (AzureFactoryClient).

The SDK is pinned to a purple commit in requirements.txt and imported lazily, so the mock and REST options do not
need it at runtime. Runtime deploy has no SDK method; it goes through `catalog_prepare` with the CLI's body.
"""

from __future__ import annotations

from typing import Any, Callable

from ..domain.errors import UpstreamError, UpstreamTimeout, ValidationFailed
from .api_errors import UpstreamRefused, error_for_status
from .factory_api import FactoryApiBackend


def _translated(call: Callable[[], Any]) -> Any:
    from azurefactory.errors import APIError, AuthError, ConfigError, FailureError, RequestTimeout

    try:
        return call()
    except RequestTimeout:
        raise UpstreamTimeout("The Factory API did not answer in time.") from None
    except AuthError as error:
        raise UpstreamRefused(error.message) from None
    except ConfigError as error:
        raise ValidationFailed(error.message, code="sdk-config") from None
    except FailureError as error:
        raise UpstreamError(error.message) from None
    except APIError as error:
        if error.status is None:
            raise UpstreamError(error.message) from None
        raise error_for_status(error.status, error.message) from None


class SdkFactoryBackend(FactoryApiBackend):
    name = "sdk"

    def __init__(self, base_url: str, api_key: str | None, folder: str, timeout: float = 30.0, client=None):
        super().__init__(folder)
        if client is None:
            from azurefactory import AzureFactoryClient
            client = _translated(lambda: AzureFactoryClient(base_url=base_url, api_key=api_key, timeout=timeout))
        self._client = client

    def _call(self, call: Callable[[], Any]) -> Any:
        return _translated(call)

    def _catalog_list(self):
        return self._call(lambda: self._client.catalog_list(self.folder))

    def _create_factory(self, *, prefix, region, region_short_name, scale_sets, settings, expected_revision):
        return self._call(lambda: self._client.factory_create_prepare(
            self.folder, prefix=prefix, region=region, scale_sets=scale_sets, settings=settings,
            expected_revision=expected_revision, region_short_name=region_short_name))

    def _add_scaleset(self, factory_id, scale_sets, expected_revision):
        return self._call(lambda: self._client.scaleset_add_prepare(
            self.folder, factory_id, scale_sets, expected_revision=expected_revision))

    def _add_project(self, factory_id, number, display_name, placements, settings, expected_revision):
        return self._call(lambda: self._client.project_add_prepare(
            self.folder, factory_id, number=number, display_name=display_name, placements=placements,
            settings=settings, expected_revision=expected_revision))

    def _configure_settings(self, factory_id, settings, scale_set_id, project_id, expected_revision):
        return self._call(lambda: self._client.catalog_settings_prepare(
            self.folder, factory_id, settings, scale_set_id=scale_set_id, project_id=project_id,
            expected_revision=expected_revision))

    def _deploy(self, body):
        return self._call(lambda: self._client.catalog_prepare(body))

    def _delete_project(self, factory_id, project_id, environments, include_project_subnets,
                        include_keyvault_and_resource_group, expected_revision, scale_set_id):
        return self._call(lambda: self._client.project_delete_prepare(
            self.folder, factory_id, project_id, environments=environments,
            include_project_subnets=include_project_subnets,
            include_keyvault_and_resource_group=include_keyvault_and_resource_group,
            expected_revision=expected_revision, scale_set_id=scale_set_id))

    def _delete_scaleset(self, factory_id, scale_set_id, expected_revision):
        return self._call(lambda: self._client.scaleset_delete_prepare(
            self.folder, factory_id, scale_set_id, expected_revision=expected_revision))

    def _delete_factory_prepare(self, body):
        return self._call(lambda: self._client.delete_aifactory_prepare(body))

    def _catalog_confirm(self, confirmation_id):
        return self._call(lambda: self._client.catalog_confirm(self.folder, confirmation_id))

    def _delete_factory_confirm(self, confirmation_id, preview_hash, phrase):
        return self._call(lambda: self._client.delete_aifactory_confirm(
            folder=self.folder, confirmation_id=confirmation_id, preview_hash=preview_hash,
            confirmation_phrase=phrase))

    def _workflow_prepare(self, body):
        return self._call(lambda: self._client.creation_workflow_prepare(body))

    def _workflow_start(self, workflow_id, confirmation_id, authorization_hash):
        return self._call(lambda: self._client.creation_workflow_start(
            self.folder, workflow_id, confirmation_id, authorization_hash=authorization_hash))

    def _workflow_status(self, workflow_id):
        return self._call(lambda: self._client.creation_workflow_status(self.folder, workflow_id))

    def _job(self, job_id):
        return self._call(lambda: self._client.catalog_job(self.folder, job_id))
