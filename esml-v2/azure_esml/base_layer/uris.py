"""Compare Azure ML datastore URIs without discarding workspace or case-sensitive keys."""

import re

from .contracts import WorkspaceTarget


def datastore_path(value: str, target: WorkspaceTarget):
    if not isinstance(value, str):
        return None
    short = re.fullmatch(r"azureml://datastores/([^/]+)/paths/(.*)", value)
    full = re.fullmatch(
        r"azureml://subscriptions/([^/]+)/resourcegroups/([^/]+)/workspaces/([^/]+)/datastores/([^/]+)/paths/(.*)",
        value, flags=re.IGNORECASE,
    )
    if short:
        datastore, key = short.groups()
    elif full:
        subscription, group, workspace, datastore, key = full.groups()
        if (subscription.casefold(), group.casefold(), workspace.casefold()) != (
            target.subscription_id.casefold(), target.resource_group.casefold(), target.workspace_name.casefold(),
        ):
            return None
    else:
        return None
    if "?" in key or "#" in key or "\\" in key or any(part in (".", "..") for part in key.split("/")):
        return None
    return datastore.casefold(), key


def same_data_path(left, right, target: WorkspaceTarget) -> bool:
    if left == right:
        return True
    parsed = datastore_path(left, target)
    return parsed is not None and parsed == datastore_path(right, target)
