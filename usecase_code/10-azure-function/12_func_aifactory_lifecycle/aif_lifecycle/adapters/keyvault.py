"""Key Vault secrets read with the Function's managed identity (the vault's private endpoint, over the VNet)."""

from __future__ import annotations

from ..domain.errors import UpstreamUnavailable


class KeyVaultSecrets:
    def __init__(self, vault_name: str, credential=None, dns_suffix: str = "vault.azure.net"):
        from azure.keyvault.secrets import SecretClient

        if credential is None:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
        self._client = SecretClient(vault_url=f"https://{vault_name}.{dns_suffix}", credential=credential)

    def get(self, name: str) -> str:
        from azure.core.exceptions import AzureError

        try:
            value = self._client.get_secret(name).value
        except AzureError:
            raise UpstreamUnavailable(f"Key Vault secret '{name}' could not be read with the Function's identity.") from None
        if not value:
            raise UpstreamUnavailable(f"Key Vault secret '{name}' is empty.")
        return value
