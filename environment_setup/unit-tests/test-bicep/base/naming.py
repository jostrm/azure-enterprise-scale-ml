"""Base layer: AI Factory resource naming conventions.

Mirrors the bicep naming so integration tests can predict resource names and
hostnames (e.g. for nslookup / az show) without re-deploying. Pure functions.
"""
from __future__ import annotations


def common_rg(prefix: str, env: str, salt: str, suffix: str) -> str:
    return f"{prefix}common-{env}-{salt}{suffix}"


def project_rg(prefix: str, project: str, env: str, salt: str, suffix: str) -> str:
    return f"{prefix}{project}-{env}-{salt}{suffix}"


def storage_blob_host(account: str) -> str:
    return f"{account}.blob.core.windows.net"


def acr_login_host(registry: str) -> str:
    return f"{registry}.azurecr.io"


def search_host(service: str) -> str:
    return f"{service}.search.windows.net"


def foundry_host(account: str) -> str:
    return f"{account}.cognitiveservices.azure.com"
