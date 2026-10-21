"""Queue-Based Load Leveling for events: the HTTP route answers fast and a queue trigger applies the event."""

from __future__ import annotations

import base64
import json
from typing import Any


class EventQueue:
    """Storage queue through Entra ID (the Function's managed identity). Messages are base64 JSON, the
    Functions queue trigger's default encoding."""

    def __init__(self, account: str, queue: str, credential=None, endpoint_suffix: str = "core.windows.net"):
        from azure.storage.queue import QueueClient

        if credential is None:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
        self._client = QueueClient(account_url=f"https://{account}.queue.{endpoint_suffix}", queue_name=queue,
                                   credential=credential)
        self._created = False

    def send(self, message: dict[str, Any]) -> None:
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

        content = base64.b64encode(json.dumps(message, separators=(",", ":")).encode("utf-8")).decode("ascii")
        try:
            self._client.send_message(content)
        except ResourceNotFoundError:
            try:
                self._client.create_queue()
            except ResourceExistsError:
                pass
            self._client.send_message(content)


def decode(body: bytes | str) -> dict[str, Any]:
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(base64.b64decode(text).decode("utf-8"))
