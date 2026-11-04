"""ASGI factory for an explicitly approved Graph notification host; no server starts here."""
import os
from pathlib import Path

from sales_demo.configuration import read_json
from sales_demo.graph_webhooks import GraphWebhookApp
from sales_demo.sync_state import SyncState


def create_app():
    configured = os.environ.get("AIF48_GRAPH_SYNC_CONFIG")
    if not configured:
        raise ValueError("Set AIF48_GRAPH_SYNC_CONFIG to the approved consumer sync configuration.")
    config = read_json(Path(configured))
    database = Path(config["database"])
    if not database.is_absolute() or not database.is_file():
        raise ValueError("Initialize the durable consumer synchronization database before hosting the callback.")
    store = SyncState(database)
    scope = store.scope(config["scope_id"])
    if scope["tenant_id"] != config["tenant_id"] or scope["drive_id"] != config["drive_id"]:
        raise ValueError("Callback configuration differs from the initialized tenant/drive scope.")
    return GraphWebhookApp(store)
