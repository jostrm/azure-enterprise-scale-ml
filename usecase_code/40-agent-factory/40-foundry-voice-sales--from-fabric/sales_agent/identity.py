"""Explicit, user-only Azure CLI identity for the local application."""

import asyncio
import json
import shutil
import subprocess
from uuid import UUID

from azure.identity.aio import AzureCliCredential

from .contracts import SalesError


class _VerifiedCliCredential:
    """Async TokenCredential that never acquires a token before checking the pinned user."""

    def __init__(self, identity):
        self._identity = identity

    async def get_token(self, *scopes, **kwargs):
        await self._identity.verify()
        return await self._identity._cli_credential.get_token(*scopes, **kwargs)

    async def close(self):
        await self._identity._cli_credential.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()


class UserIdentity:
    def __init__(self, settings):
        self.settings = settings
        self.verified_user = None
        self._cli_credential = AzureCliCredential(
            tenant_id=settings.tenant_id, subscription=settings.subscription_id
        )
        self.credential = _VerifiedCliCredential(self)

    async def verify(self):
        executable = shutil.which("az")
        if not executable:
            raise SalesError("user_authentication_failed", "Azure CLI is not available.", 401)
        command = [
            executable, "account", "show", "--subscription", self.settings.subscription_id,
            "--output", "json", "--only-show-errors",
        ]
        try:
            result = await asyncio.to_thread(
                subprocess.run, command, capture_output=True, text=True,
                timeout=20, check=False, shell=False,
            )
            if result.returncode != 0:
                raise ValueError("Account lookup failed")
            account = json.loads(result.stdout)
            tenant = str(UUID(account["tenantId"]))
            subscription = str(UUID(account["id"]))
            user = account["user"]
            name = user["name"]
            if (
                tenant != str(UUID(self.settings.tenant_id))
                or subscription != str(UUID(self.settings.subscription_id))
                or user["type"].casefold() != "user"
                or not isinstance(name, str)
                or not name.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in name)
                or len(name) > 320
                or (self.settings.expected_user
                    and name.casefold() != self.settings.expected_user.casefold())
                or (self.verified_user is not None
                    and name.casefold() != self.verified_user.casefold())
            ):
                raise ValueError("User account mismatch")
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError):
            raise SalesError(
                "user_authentication_failed",
                "An Azure CLI user sign-in matching the configured tenant, subscription, "
                "expected user, and first verified user is required. "
                "Service principals and managed identities are unsupported.",
                401,
            ) from None
        if self.verified_user is None:
            self.verified_user = name
        return {"tenant": tenant, "subscription": subscription, "user": name}

    async def close(self):
        await self.credential.close()
