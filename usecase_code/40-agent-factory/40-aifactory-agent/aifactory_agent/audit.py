import json
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from azure.storage.blob import ContainerClient

from .config import credential


class ToolAudit:
    """Store only caller, scope and outcome metadata, never prompts or tool content."""

    def __init__(self, settings, principal, scope_key, correlation_id):
        self.settings = settings
        self.principal = principal
        self.scope_key = scope_key
        self.correlation_id = correlation_id
        self.container = ContainerClient(
            settings.azure.storage_endpoint, settings.azure.storage_container,
            credential=credential(settings), retry_total=0,
        )

    @contextmanager
    def operation(self, name, call_id=None):
        event = {
            "event_id": str(uuid4()), "correlation_id": self.correlation_id,
            "tenant_id": self.principal.tenant_id, "object_id": self.principal.object_id,
            "scope_key": self.scope_key,
            "scope": self.settings.scopes[self.scope_key].model_dump(mode="json"),
            "operation": name, "call_id": call_id, "changes_state": False,
            "started_at": datetime.now(timezone.utc).isoformat(), "outcome": "failed",
        }
        try:
            yield event
        finally:
            event["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.container.get_blob_client(
                f"audit/tools/{self.correlation_id}/{event['event_id']}.json",
            ).upload_blob(json.dumps(event, sort_keys=True), overwrite=False)
