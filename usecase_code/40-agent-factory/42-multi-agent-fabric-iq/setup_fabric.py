# Creates the Fabric IQ side that Inventory-Agent uses, on an existing Fabric capacity:
# workspace -> lakehouse + table "inventory" from data/inventory.csv -> published data agent
# -> Foundry project connection (RemoteTool, the caller's Entra token) named fabric_connection_name.
# Re-runnable: existing items are reused and the data agent definition is updated.

import base64
import json
import os
import time
import uuid

import requests
from azure.identity import DefaultAzureCredential

from agents import HERE, load_settings

SETUP = ("fabric_capacity_name",)
WORKSPACE, LAKEHOUSE, DATA_AGENT = "zava-fabric-iq", "zava_inventory_lh", "zava_inventory_agent"
FABRIC = "https://api.fabric.microsoft.com"
ONELAKE = "https://onelake.dfs.fabric.microsoft.com"
ARM = "https://management.azure.com"
COLUMNS = (("ProductId", "string", "Zava product id, e.g. PROD000281"),
           ("ProductName", "string", "Product name"),
           ("StoreLocation", "string", "Store that holds the stock"),
           ("QuantityOnHand", "int", "Units in stock at that store"),
           ("ReorderPoint", "int", "Stock level that triggers a reorder"),
           ("InventoryStatus", "string", "In stock or At risk of stockout"))
INSTRUCTIONS = ("You answer Zava inventory questions from the inventory table only. Always return ProductId, "
                "ProductName, QuantityOnHand, InventoryStatus and StoreLocation. Match products by ProductId, or by "
                "ProductName with LOWER(ProductName) LIKE '%word%' for each distinctive word in singular form "
                "(shelves -> shelf), never by exact name equality and never on the brand word Zava.")


def data_agent_definition(workspace_id, lakehouse_id):
    # Draft and published stages are identical: the published stage is what the MCP endpoint serves
    datasource = {
        "$schema": "1.0.0", "artifactId": lakehouse_id, "workspaceId": workspace_id, "displayName": LAKEHOUSE,
        "type": "lakehouse_tables", "userDescription": "Zava store inventory per product and store",
        "dataSourceInstructions": "Table inventory has one row per product and store.",
        "elements": [{
            "id": str(uuid.uuid4()), "display_name": "dbo", "type": "lakehouse_tables.schema", "is_selected": True,
            "children": [{
                "id": str(uuid.uuid4()), "display_name": "inventory", "type": "lakehouse_tables.table",
                "is_selected": True, "description": "Zava stock levels, status and store location",
                "children": [{"id": str(uuid.uuid4()), "display_name": name, "type": "lakehouse_tables.column",
                              "is_selected": True, "data_type": kind, "description": text}
                             for name, kind, text in COLUMNS],
            }],
        }],
    }
    stage = {"$schema": "1.0.0", "aiInstructions": INSTRUCTIONS}
    files = {"Files/Config/data_agent.json": {"$schema": "2.1.0"},
             "Files/Config/publish_info.json": {"$schema": "1.0.0", "description": "Zava inventory for Inventory-Agent"}}
    for stage_name in ("draft", "published"):
        files[f"Files/Config/{stage_name}/stage_config.json"] = stage
        files[f"Files/Config/{stage_name}/lakehouse_tables-{LAKEHOUSE}/datasource.json"] = datasource
    return {"parts": [{"path": path, "payloadType": "InlineBase64",
                       "payload": base64.b64encode(json.dumps(value).encode()).decode()} for path, value in files.items()]}


def connection_definition(workspace_id, data_agent_id):
    return {"properties": {
        "category": "RemoteTool", "authType": "UserEntraToken", "isSharedToAll": False,
        "audience": "https://analysis.windows.net/powerbi/api",
        "target": f"{FABRIC}/v1/mcp/workspaces/{workspace_id}/dataagents/{data_agent_id}/agent",
    }}


def main():
    settings = load_settings()
    capacity_name, project_resource_id = os.getenv("fabric_capacity_name", ""), os.getenv("project_resource_id", "")
    if not (capacity_name and project_resource_id and settings["fabric_connection_name"]):
        raise SystemExit("Set fabric_capacity_name, project_resource_id and fabric_connection_name in parameters.env")
    credential = DefaultAzureCredential()

    def request(method, url, audience, body=None, data=None, params=None):
        headers = {"Authorization": f"Bearer {credential.get_token(f'{audience}/.default').token}", "x-ms-version": "2023-11-03"}
        response = requests.request(method, url, json=body, data=data, params=params, headers=headers, timeout=120)
        while response.status_code == 202 and "Location" in response.headers:  # Fabric long-running operation
            time.sleep(int(response.headers.get("Retry-After", 5)))
            operation = response.headers["Location"]
            response = requests.get(operation, headers=headers, timeout=60)
            if response.ok and response.json().get("status") == "Succeeded":
                result = requests.get(f"{operation}/result", headers=headers, timeout=60)
                response = result if result.ok else response
            elif response.ok and response.json().get("status") in ("NotStarted", "Running"):
                response.status_code, response.headers["Location"] = 202, operation
        if not response.ok or (response.content and response.json().get("status") == "Failed"):
            raise SystemExit(f"{method} {url} -> {response.status_code}: {response.text[:800]}")
        print(f"{method} {url.split('?')[0]} -> {response.status_code}")
        return response.json() if response.content else {}

    def fabric(method, path, body=None):
        return request(method, f"{FABRIC}/v1{path}", FABRIC, body)

    def get_or_create(path, name, body):
        found = [item for item in fabric("GET", path)["value"] if item["displayName"] == name]
        return found[0] if found else fabric("POST", path, {"displayName": name, **body})

    capacities = [c for c in fabric("GET", "/capacities")["value"] if c["displayName"] == capacity_name]
    if not capacities or capacities[0]["state"] != "Active":
        raise SystemExit(f"Fabric capacity {capacity_name} not found or not Active (resume it first)")
    workspace = get_or_create("/workspaces", WORKSPACE, {"capacityId": capacities[0]["id"]})["id"]
    lakehouse = get_or_create(f"/workspaces/{workspace}/lakehouses", LAKEHOUSE, {})["id"]

    csv = (HERE / "data" / "inventory.csv").read_bytes()
    file_url = f"{ONELAKE}/{workspace}/{lakehouse}/Files/inventory.csv"
    request("PUT", file_url, "https://storage.azure.com", params={"resource": "file"})
    request("PATCH", file_url, "https://storage.azure.com", data=csv, params={"action": "append", "position": "0"})
    request("PATCH", file_url, "https://storage.azure.com", params={"action": "flush", "position": str(len(csv))})
    fabric("POST", f"/workspaces/{workspace}/lakehouses/{lakehouse}/tables/inventory/load", {
        "relativePath": "Files/inventory.csv", "pathType": "File", "mode": "Overwrite",
        "formatOptions": {"format": "Csv", "header": True, "delimiter": ","}})

    definition = data_agent_definition(workspace, lakehouse)
    agent = get_or_create(f"/workspaces/{workspace}/dataAgents", DATA_AGENT, {"definition": definition})
    fabric("POST", f"/workspaces/{workspace}/dataAgents/{agent['id']}/updateDefinition", {"definition": definition})

    request("PUT", f"{ARM}{project_resource_id}/connections/{settings['fabric_connection_name']}?api-version=2025-10-01-preview",
            ARM, connection_definition(workspace, agent["id"]))
    print(f"Fabric IQ ready: run agents.py to give Inventory-Agent the {settings['fabric_connection_name']} connection")


if __name__ == "__main__":
    main()
