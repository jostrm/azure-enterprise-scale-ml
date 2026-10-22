# Retail agents on Foundry IQ and Fabric IQ

Zava, a DIY and interior design retailer, answers customer questions with three
prompt agents behind one Foundry workflow. A `Supervisor-Agent` reads the
question and names the agent that should answer it:

- `Sales-Associate-Agent` recommends and upsells products from the product
  catalogue (Foundry IQ knowledge base).
- `Rewards-Campaign-Agent` explains loyalty tiers and Black Friday discounts and
  returns JSON with the discount (same Foundry IQ knowledge base).
- `Inventory-Agent` checks stock level, status and store location in Microsoft
  Fabric through the Fabric IQ tool.

The example is deliberately small: about 150 lines of Python, one workflow YAML
and sample data. It is based on the Microsoft Learn lab "agents with Foundry IQ
and Fabric IQ" and runs on an AI Factory project's Foundry and AI Search
resources. It does not use the `agent_factory` operator CLI.

## Use case summary

- Use case type: Multi-agent RAG with LLM (supervisor routing to three grounded prompt agents)
- Data type: Document | Tabular (product and loyalty JSON; inventory table in Fabric)
- Number of source data sets: 2 (Zava product and rewards knowledge; Zava store inventory)
- Data sources: [data/products.json](data/products.json) and [data/rewards.json](data/rewards.json) in an Azure AI Search knowledge base; [data/inventory.csv](data/inventory.csv) loaded into a Fabric lakehouse behind a published Fabric data agent
- Inference type: Online
- Technology used in full chain: Microsoft Foundry (prompt agents, workflow, Responses API) | Foundry IQ (Azure AI Search knowledge base over MCP) | Fabric IQ (Microsoft Fabric data agent) | Azure AI Projects SDK | Python | Microsoft Entra ID

## How it works

```text
question --> FoundryIQ-Workflow
               |-- Supervisor-Agent  -> replies with one agent name (not shown to the user)
               |-- "Sales-Associate-Agent"  -> MCP tool -> AI Search knowledge base (products)
               |-- "Rewards-Campaign-Agent" -> MCP tool -> AI Search knowledge base (rewards)
               |-- "Inventory-Agent"        -> Fabric IQ tool (your Entra token) -> Fabric data agent MCP -> lakehouse table
               '-- anything else            -> empty reply
```

| File | What it does |
|---|---|
| [setup_knowledge.py](setup_knowledge.py) | Creates the AI Search index from `data/*.json`, the knowledge source, the knowledge base (minimal effort, extractive, no Search-side model) and the Foundry project connection to its MCP endpoint. |
| [setup_fabric.py](setup_fabric.py) | On an existing Fabric capacity: creates the workspace `zava-fabric-iq`, the lakehouse table `inventory` from [data/inventory.csv](data/inventory.csv), a published Fabric data agent over it and the Foundry Fabric IQ connection (`RemoteTool`, the caller's Entra token). Optional. |
| [agents.py](agents.py) | Creates a new version of the four agents and the workflow from [workflow.yaml](workflow.yaml). |
| [chat.py](chat.py) | Asks the workflow, or one agent with `--agent`, a question and prints the answering agent and its reply. |
| [parameters.env.template](parameters.env.template) | Settings to copy to `parameters.env` (git-ignored). |

Without a Fabric connection (`fabric_connection_name` empty), `Inventory-Agent`
is still created so the workflow route works, but without tools: it says that
stock can't be checked yet and never guesses.

## Prerequisites

- Python 3.13, PowerShell and Azure CLI signed in to the project tenant
  (`az login`). `DefaultAzureCredential` uses that login.
- An AI Factory project (or any Foundry project) with:
  - a Foundry project and a chat model deployment (tested with `gpt-5.1`);
  - an Azure AI Search service with semantic ranker `free` or `standard`, which
    the Foundry agents can reach (a private AI Factory project already has the
    network path; this was verified on project001);
  - the project's managed identity with **Search Index Data Reader** on Search.
- Network access from your machine to the private Foundry and Search endpoints
  (Azure VPN for a private AI Factory).
- Your roles: **Search Service Contributor** (or Contributor/Owner) and
  **Search Index Data Contributor** on Search to run `setup_knowledge.py`;
  **Azure AI User** (Foundry User) on the project to create and call agents; a
  role that can write project connections (Azure AI Project Manager or Owner).
- For `Inventory-Agent` with real data (optional, step 2 below):
  - a paid Microsoft Fabric capacity, **F2 or larger** (Fabric trial capacity
    does not support data agents), in the same tenant as Foundry, where you are a
    capacity admin. F2 costs money while Active: pause it when you are done;
  - Fabric tenant settings that allow data agents: "Users can use Copilot and
    other features powered by Azure OpenAI" and "Capacities can be designated as
    Fabric Copilot capacities" (Fabric admin portal). Regions outside the EU data
    boundary and the US also need cross-geo processing;
  - every user who chats with `Inventory-Agent` needs read access to the Fabric
    workspace (the Fabric IQ connection passes their own Entra token).

## How to set up the Python environment

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory\41-single-agent-fabric-iq"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
Copy-Item .\parameters.env.template .\parameters.env
```

Edit `parameters.env`. Pick a knowledge base name (for example `zava-retail-kb`):
`server_url` ends in `/knowledgebases/<name>/mcp?api-version=2026-08-01-preview`
and `setup_knowledge.py` derives the index and knowledge source names from it.

## How to run the code

```powershell
# 1. Foundry IQ: search index, sample documents, knowledge base and project connection (re-runnable)
.\.venv\Scripts\python.exe .\setup_knowledge.py

# 2. Optional, Fabric IQ: a paid F2 capacity (skip if you have one), then workspace, table, data agent, connection.
#    Set fabric_capacity_name and fabric_connection_name (for example zava-fabric-iq) in parameters.env first.
$Sub = "<subscription-id>"; $Rg = "<resource-group>"; $Capacity = "<fabric-capacity>"
az provider register -n Microsoft.Fabric --subscription $Sub --wait
@{ location = "swedencentral"; sku = @{ name = "F2"; tier = "Fabric" }
   properties = @{ administration = @{ members = @("<you@tenant>") } } } | ConvertTo-Json -Depth 5 | Set-Content "$env:TEMP\capacity.json"
az rest --method put --body "@$env:TEMP\capacity.json" `
  --url "https://management.azure.com/subscriptions/$Sub/resourceGroups/$Rg/providers/Microsoft.Fabric/capacities/$Capacity`?api-version=2023-11-01"
.\.venv\Scripts\python.exe .\setup_fabric.py

# 3. Agents and workflow (each run creates a new version only when the definition changed)
.\.venv\Scripts\python.exe .\agents.py

# 4. Ask the workflow; the supervisor picks the agent
.\.venv\Scripts\python.exe .\chat.py "Want paint recommendation for my living room"
.\.venv\Scripts\python.exe .\chat.py "I am Anna Berg. What discount do I get on paint this Black Friday?"
.\.venv\Scripts\python.exe .\chat.py "Is PROD000281 in stock?"

# Or ask one agent directly
.\.venv\Scripts\python.exe .\chat.py --agent Sales-Associate-Agent "Which paint sprayer do you sell?"
```

Expected output: each answer starts with the agent that wrote it, for example
`[Rewards-Campaign-Agent] { "answer": "Hi Anna Berg ...", "discount_percentage": "30%" }`.
You can also open `FoundryIQ-Workflow` in the Foundry portal (Build > Workflows)
to see the visual flow and chat with it in the playground.

With Fabric IQ set up, inventory answers come from the lakehouse table, for example
`[Inventory-Agent] ProductId: PROD000281 ... QuantityOnHand: 2, InventoryStatus: At risk of stockout, StoreLocation: Stockholm City`.
Without it, `Inventory-Agent` says it cannot check stock.

Pause the capacity when you are done, and resume it before the next demo
(Fabric items stay; queries fail while it is paused):

```powershell
$CapacityId = "/subscriptions/$Sub/resourceGroups/$Rg/providers/Microsoft.Fabric/capacities/$Capacity"
az rest --method post --url "https://management.azure.com$CapacityId/suspend?api-version=2023-11-01"
az rest --method post --url "https://management.azure.com$CapacityId/resume?api-version=2023-11-01"
```

Offline contract tests (no Azure calls), from the factory root `40-agent-factory`:

```powershell
.\41-single-agent-fabric-iq\.venv\Scripts\python.exe -m unittest tests.test_fabric_iq_usecase -v
```

## Lifecycle notes

- Foundry retires workflows on 2026-12-01. After that, a workflow YAML runs only
  as a hosted agent through Agent Framework; the prompt agents keep working.
- The lab's original `MicrosoftFabricPreviewTool` (Fabric data agent tool) is
  deprecated on 2026-11-06. This example uses its replacement,
  `FabricIQPreviewTool`.
- Clean up in the Foundry portal (delete the four agents, the workflow and the two
  project connections), in AI Search (knowledge base, knowledge source, index),
  in Fabric (workspace `zava-fabric-iq`) and in Azure (the Fabric capacity).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Missing in parameters.env: ...` | Copy `parameters.env.template` to `parameters.env` and fill the named settings. |
| `agent_not_found` for `Inventory-Agent` (HTTP 500 from the workflow) | The workflow routed to an agent that does not exist. Run `agents.py`, which always creates all four agents. |
| Name resolution or connection errors to `*.services.ai.azure.com` or `*.search.windows.net` | The endpoints are private: connect the Azure VPN and check that the names resolve to private IPs. |
| `403` from Search in `setup_knowledge.py` | Your user needs Search Service Contributor (or Contributor/Owner) and Search Index Data Contributor on the search service. |
| Agents answer without products or citations | Check the project managed identity has Search Index Data Reader, and that `server_url` and `project_connection_id` match what `setup_knowledge.py` created. |
| Inventory answers "not configured" | Expected until `fabric_connection_name` is set and `agents.py` has run again; see step 2. |
| `setup_fabric.py`: capacity not found or not Active | The capacity is paused or you are not its admin: resume it, or add yourself to `administration.members`. |
| Inventory errors or empty answers while the capacity is paused | Fabric data agents need an Active capacity: resume it. |
| Inventory says a product is not found although it is in the table | The data agent writes SQL from the question. Use the ProductId, or improve `INSTRUCTIONS` in `setup_fabric.py` and run it again (it republishes the agent). |
