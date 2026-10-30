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
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory\42-multi-agent-fabric-iq"
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
.\42-multi-agent-fabric-iq\.venv\Scripts\python.exe -m unittest tests.test_fabric_iq_usecase -v
```

## Run this use case with an AI assistant

Copy a prompt, replace the `<...>` placeholders, and paste it into the assistant. Every assistant has a **demo data** prompt and a **your own data** prompt. [How these prompts work](../readme.md#run-the-use-cases-with-an-ai-assistant) explains where to paste them and what each assistant can and cannot do.

> **Cost:** the optional Fabric IQ step needs a **paid F2 or larger Fabric capacity**, billed while it is Active. Every prompt below asks the assistant to pause it when you are done.

### AI Factory Agent Chat

Paste into the [AI Factory Agent Chat](../40-aifactory-agent/readme.md) with the **Project** explanation view and your scope selected. It answers from the indexed documentation with citations; the Factory actions panel only prepares a reviewable plan, which a person approves.

<details>
<summary><b>Demo data</b></summary>

```text
Explain the Zava retail multi-agent demo in usecase_code/40-agent-factory/42-multi-agent-fabric-iq for my scope <project001-dev>: how the Supervisor-Agent routes to Sales-Associate-Agent, Rewards-Campaign-Agent (Foundry IQ) and Inventory-Agent (Fabric IQ), what parameters.env needs, the roles I need, the paid F2 Fabric capacity and how to pause it, and the workflow and tool retirement dates. Cite the documentation.

Then, in the Factory actions panel (it prepares a reviewable plan; a person approves it):
/create-agent-oftype-for-project
  type: 42-multi-agent-fabric-iq
  project_resource_id: </subscriptions/<sub>/resourceGroups/<project-rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>>
(This works only if the platform team has approved a workload profile for this type; otherwise the chat reports the blocker.)
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
I want to run the Foundry IQ + Fabric IQ retail agents on our own catalog and inventory: products <describe>, loyalty and campaign rules <describe>, inventory per store <describe>. Explain, with citations, the exact fields for data/products.json and data/rewards.json, the columns of data/inventory.csv, and what else in setup_fabric.py (column descriptions and INSTRUCTIONS) must change if my columns differ.
```

</details>

### GitHub Copilot and Claude Code (one prompt for both)

The same prompt works in **GitHub Copilot** (VS Code Chat in *Agent* mode) and **Claude Code** (run `claude` in the repository root). Use a machine that is signed in to Azure CLI and connected to the AI Factory private network. Both assistants read this repository's `AGENTS.md`.

<details>
<summary><b>Demo data</b></summary>

```text
Run the Zava retail demo in usecase_code/40-agent-factory/42-multi-agent-fabric-iq with its synthetic data and ask the supervisor workflow three questions.

First read AGENTS.md, then usecase_code/40-agent-factory/42-multi-agent-fabric-iq/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. In that folder, create its own `.venv`, install `requirements.txt`, and create parameters.env from parameters.env.template only if it does not exist. Help me fill in endpoint, model_deployment_name, server_label, server_url, project_connection_id and project_resource_id; leave fabric_connection_name empty for now.
3. Run the offline unit tests the README lists.
4. setup_knowledge.py writes to Azure directly (index, knowledge source, knowledge base, connection): ask me before running it.
5. Ask me whether to set up Fabric IQ. It needs a paid F2 capacity: only after my explicit approval, create the capacity and run setup_fabric.py as the README shows. Otherwise skip it; Inventory-Agent will then say it cannot check stock.
6. After my approval, run agents.py (creates agent and workflow versions).
7. After my approval, run the billed chat.py with: "Want paint recommendation for my living room", "I am Anna Berg. What discount do I get on paint this Black Friday?" and "Is PROD000281 in stock?". Show which agent answered each one.
8. When I say I am done, suspend the Fabric capacity with the README command and list the manual cleanup items.

Rules:
- Follow AGENTS.md. Use only commands and flags documented in the READMEs above; do not invent new ones.
- Run offline and read-only steps first. Before any command that writes to Azure (`--apply`, `--execute`, or a script the README says writes directly) or makes a billed model call, show me the exact command and its target and wait for my "yes".
- Never enable public network access, change networking or RBAC, approve all pending private links at once, edit integrity hashes, or print or store tokens, keys or SAS.
- Never overwrite an existing configuration file, and never commit configuration, journals, .venv folders or data.
- If a prerequisite is missing (private network, role, quota, upstream step), stop and tell me the blocker instead of working around it.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Run the retail multi-agent demo in usecase_code/40-agent-factory/42-multi-agent-fabric-iq on my own product, rewards and inventory data.

First read AGENTS.md, then usecase_code/40-agent-factory/42-multi-agent-fabric-iq/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Set up the folder's `.venv` and parameters.env as the README shows (never overwrite an existing parameters.env).
3. Convert my data into the demo's formats and show me the result before writing it: products <path to my file> -> data/products.json; loyalty and campaign rules <path> -> data/rewards.json (JSON arrays with string fields id, ProductId, ProductName, Category, ProductDescription, and FormattedPrice for products); inventory <path> -> data/inventory.csv with columns ProductId,ProductName,StoreLocation,QuantityOnHand,ReorderPoint,InventoryStatus. If my columns differ, also update the column descriptions and INSTRUCTIONS in setup_fabric.py and tell me.
4. Run the offline unit tests, then setup_knowledge.py, optional Fabric setup (paid F2, explicit approval), agents.py and chat.py, each only after my approval.
5. Ask these questions: <question about products>, <question about a customer discount>, <question about stock for one of my ProductIds>.
6. When I am done, suspend the Fabric capacity and list the manual cleanup items.

Rules:
- Follow AGENTS.md. Use only commands and flags documented in the READMEs above; do not invent new ones.
- Run offline and read-only steps first. Before any command that writes to Azure (`--apply`, `--execute`, or a script the README says writes directly) or makes a billed model call, show me the exact command and its target and wait for my "yes".
- Never enable public network access, change networking or RBAC, approve all pending private links at once, edit integrity hashes, or print or store tokens, keys or SAS.
- Never overwrite an existing configuration file, and never commit configuration, journals, .venv folders or data.
- If a prerequisite is missing (private network, role, quota, upstream step), stop and tell me the blocker instead of working around it.
```

</details>

### Lovable

Lovable builds a hosted web front end. It cannot run this Python, sign in to your tenant or reach private AI Factory endpoints, so these prompts build a **prototype** with demo data or data you paste in. Paste only data you are allowed to share with an external service, and connect the prototype to the real result only through an API your platform team approves, never by enabling public access. Paste the **your own data** prompt as a follow-up message in the same Lovable project, after the demo prompt.

<details>
<summary><b>Demo data</b></summary>

```text
Build a "Zava retail assistant" prototype for a home-improvement store.
- A chat where each answer shows a routing badge: Sales Associate | Rewards Campaign | Inventory.
- Sales answers recommend paint products with price and description cards.
- Rewards answers show a discount card built from JSON like {"discount_percentage": 15} (example question: "I am Anna Berg. What discount do I get on paint this Black Friday?").
- Inventory answers show a stock table per store (QuantityOnHand, ReorderPoint, InventoryStatus) for questions like "Is PROD000281 in stock?".
Use about 20 mock products and 3 stores.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Build the same retail assistant prototype for <store name>.
Use my products as the mock catalog: <paste rows of ProductId | ProductName | Category | ProductDescription | FormattedPrice>.
Use my loyalty rules: <paste rules>.
Use my inventory: <paste CSV with ProductId,ProductName,StoreLocation,QuantityOnHand,ReorderPoint,InventoryStatus>.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

## Video walkthrough tutorial - TBA

A video walkthrough tutorial, recorded by a person, will be published here soon. It shows how to run this code, step by step, to achieve the result described in this README.

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
