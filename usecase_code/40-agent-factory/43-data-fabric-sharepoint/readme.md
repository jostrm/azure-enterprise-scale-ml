# Agent data sources: SharePoint, Foundry IQ, Fabric IQ and own documents

A generic template for an agent with a **"Settings > Data sources"** screen. The
user switches four data sources on or off, and one Foundry prompt agent gets
exactly one tool per enabled source:

| Data source | Tool on the agent | What it reads |
|---|---|---|
| SharePoint | `SharepointPreviewTool` (SharePoint grounding) | Sites and documents the signed-in user may open |
| Foundry IQ | `MCPTool` to an Azure AI Search knowledge base | An existing Foundry IQ knowledge base |
| Fabric IQ | `FabricIQPreviewTool` | A published Microsoft Fabric data agent (lakehouse, warehouse, semantic model) |
| Upload own documents | `MCPTool` to a second knowledge base | Files the user uploads to the **project's data storage account** (for example project 2001 Dev), in a separate container |

The settings live in one JSON file, `data-sources.json`, so any client can own
the Settings screen (a CLI, a web app, or a desktop app such as the ESAF Agent
chat) and validate it with the same rules in [data_sources.py](data_sources.py)
before saving. The example is small: plain Python, no `agent_factory` operator
CLI. Compare [42-multi-agent-fabric-iq](../42-multi-agent-fabric-iq/readme.md),
which shows Foundry IQ and Fabric IQ in a multi-agent workflow.

## Use case summary

- Use case type: RAG with LLM (one grounded prompt agent, data sources chosen in settings)
- Data type: Document | Tabular (SharePoint and uploaded documents; Fabric tables through a data agent)
- Number of source data sets: 0-4, one per enabled data source; never mixed into one index
- Data sources: SharePoint Online sites; an existing Foundry IQ knowledge base; a published Fabric data agent; own documents in the project data storage account, container `agent-uploads`, folder `users/<user>/`
- Inference type: Online (agent questions) | Batch (upload, then knowledge-base indexing)
- Technology used in full chain: Microsoft Foundry (prompt agent, Responses API) | Foundry IQ (Azure AI Search knowledge base over MCP) | Fabric IQ (Microsoft Fabric data agent) | SharePoint grounding | Azure Storage (Blob, private endpoint) | Azure AI Projects SDK | Python | Microsoft Entra ID

## How it works

```text
Settings screen --> data-sources.json --(data_sources.py validates)--> agents.py
                                                                         |
  Data-Sources-Agent (prompt agent, one tool per enabled source) <-------'
     |-- SharePoint grounding  -> SharePoint project connection (user's Entra identity)
     |-- MCP tool              -> Foundry IQ knowledge base (AI Search)
     |-- Fabric IQ tool        -> Fabric data agent (user's Entra token)
     '-- MCP tool              -> "uploads" knowledge base -> blob knowledge source
                                    ^
upload_documents.py --(Entra, private endpoint)--> <project storage>/agent-uploads/users/<user>/
```

| File | What it does |
|---|---|
| [data_sources.py](data_sources.py) | Domain: parses and validates the settings, maps each enabled source to a tool through a `ToolFactory` port (Factory Method per kind), writes the grounding instructions, checks upload names, types and sizes. No Azure SDK imports. |
| [agents.py](agents.py) | Foundry adapter (`FoundryToolFactory`) and the script that creates a new version of the agent with the enabled tools. |
| [upload_documents.py](upload_documents.py) | Uploads files to the `uploaded_documents` container with your Entra identity. Validates every file before the first upload. |
| [chat.py](chat.py) | Asks the agent a question in a new conversation. |
| [data-sources.example.json](data-sources.example.json) | The settings shape. Copy to `data-sources.json` (git-ignored), fill in, set `enabled`. |
| [parameters.env.template](parameters.env.template) | Foundry endpoint, model and agent name. Copy to `parameters.env` (git-ignored). |

Rules the settings enforce: unknown sources or fields are rejected (no silent
fallback), a disabled source needs no other fields, knowledge-base URLs must be
https `.../knowledgebases/<kb>/mcp` endpoints without credentials, storage and
container names follow Azure naming, and the upload folder is a relative prefix
that cannot escape the container (`..`, leading `/` and `\` are rejected).
With no source enabled the agent gets no tools and says it cannot answer from
company data, instead of guessing.

### Where uploaded documents are stored

Use the **project's data storage account** (the project 2001 Dev account in the
AI Factory demo), not the common lake: uploads are project data and user content.
The account is private (private endpoint, no public access, no shared keys), so
`upload_documents.py` uses `DefaultAzureCredential` and needs the network path
(AI Factory VPN, Bastion or jumpbox). Keep uploads in their own container
(`agent-uploads`) with one folder per user, separate from curated data such as
`agent-factory` or `agent-factory-rag` used by [45-rag-agent](../45-rag-agent/readme.md).

The upload knowledge base indexes that container. Create it like the Foundry IQ
one in [42-multi-agent-fabric-iq/setup_knowledge.py](../42-multi-agent-fabric-iq/setup_knowledge.py),
but with an Azure Blob knowledge source on `agent-uploads` (Search's managed
identity needs **Storage Blob Data Reader** on the account). New files are
searchable after the next indexer run. Allowed types: pdf, docx, pptx, xlsx,
txt, md, html, csv, json; maximum 16 MB per file (the Search Basic blob limit).
Per-user folders organize files; they are not an access boundary. For
per-user permissions use ADLS ACLs as in
[48-rag-with-splitted-tables-acl-adlsgen2](../48-rag-with-splitted-tables-acl-adlsgen2/readme.md).

## Prerequisites

- Python 3.13, PowerShell and Azure CLI signed in to the project tenant (`az login`).
- An AI Factory project (or any Foundry project) with a chat model deployment and
  network access to its private endpoints (Azure VPN for a private AI Factory).
- Your role **Azure AI User** on the Foundry project to create and call agents.
- Per data source you enable:
  - SharePoint: a SharePoint project connection in Foundry (Management center >
    Connected resources > SharePoint, with the site URL). Users need a Microsoft
    365 Copilot license or pay-as-you-go, and only see what they may open.
  - Foundry IQ: an AI Search knowledge base and its Foundry project connection;
    the project managed identity needs **Search Index Data Reader**.
  - Fabric IQ: a published Fabric data agent on a paid F2+ capacity and its
    Foundry project connection; see
    [42-multi-agent-fabric-iq](../42-multi-agent-fabric-iq/readme.md#prerequisites).
  - Uploaded documents: **Storage Blob Data Contributor** for the uploader on the
    project data storage account, the `agent-uploads` container, and a knowledge
    base over it (see above).

## How to set up the Python environment

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory\43-data-fabric-sharepoint"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
Copy-Item .\parameters.env.template .\parameters.env
Copy-Item .\data-sources.example.json .\data-sources.json
```

Edit `parameters.env`, then fill in `data-sources.json` and set `"enabled": true`
on the sources you want.

## How to run the code

```powershell
# 1. Optional: upload own documents (uploaded_documents must be enabled)
.\.venv\Scripts\python.exe .\upload_documents.py "C:\docs\travel-policy.pdf" "C:\docs\Q3 report.docx"

# 2. Create a new agent version with one tool per enabled data source (re-run after changing settings)
.\.venv\Scripts\python.exe .\agents.py

# 3. Ask the agent
.\.venv\Scripts\python.exe .\chat.py "What does our travel policy say about train vs. flight?"
```

Expected output of step 2:
`Agent created (id: ..., name: Data-Sources-Agent, version: 3); data sources: sharepoint, foundry_iq, uploaded_documents`.
The answer in step 3 cites the document, site or table it came from, or says the
information could not be found.

Offline tests (no Azure login), from `40-agent-factory`:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_data_fabric_sharepoint_usecase -v
```

The adapter test runs only where this folder's `requirements.txt` is installed;
the settings, tool-mapping and upload tests need only the standard library.
