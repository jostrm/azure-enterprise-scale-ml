# Shared Agent Factory operator and runtime support

This Python package implements the reusable control plane behind the examples:
target discovery, private-network checks, ingestion, Foundry IQ configuration,
prompt/hosted deployment and invocation. Keep customer resource selections in
the consumer's configuration, not in this package.

## Use case summary

- Use case type: RAG with LLM (shared implementation support, not a separate agent)
- Data type: Tabular | Document (helpdesk ingestion); structured JSON configuration and operational metadata
- Number of source data sets: 1 for the helpdesk ingestion path; 0 for deployment, Azure inventory and offline monitoring
- Data sources: ADF's reported `<selected-storage>/<selected-container>/<prefix>/knowledge/items.json` (`kaggle-rag-v1/adf/<project-id-hash>` prefix with explicit storage profiles; `kaggle-rag-v1` in legacy mode), or a pinned `45-rag-agent` corpus. See [storage selection](../readme.md#one-storage-selection-for-every-example).
- Inference type: Online (invocation) | Batch (ingestion preparation only); configuration/monitoring commands do not infer
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Entra ID | Azure Container Apps / Azure MCP in the expanded profile

## Responsibilities

| Modules | Responsibility |
| --- | --- |
| `config`, `azure`, `discovery`, `network` | Explicit target selection, OAuth, actual resource discovery and private-network checks. |
| `data`, `datafactory`, `knowledge` | Pinned corpus preparation, evaluation separation and Foundry IQ setup. |
| `catalog`, `prompt`, `hosted`, `cli` | Agent roles, allowed tools, persistent versions, package construction and invocation. |
| `mcp_control`, `mcp_connection` | Private Azure MCP identity, infrastructure preflight, DNS/connection checks and tool-output verification. |
| `rag_sources`, `rag_materialization`, `rag_indexing` | Explicit common/project source bindings, exact-file managed-identity copies and verified private retrieval for `45-rag-agent`. |
| `monitoring` | Offline projection of recorded aggregates; no live polling, model inference or fabricated quality scores. |

## Prerequisites

This is a shared library and operator, not a separately deployed use case.
Use Python 3.13 and PowerShell. CLI help, configuration plans and monitoring
exports are offline; live commands additionally require the
[operator prerequisites](../readme.md#prerequisites): Azure CLI tenant sign-in,
resolved consumer configuration, existing services, scoped permissions and
VPN/private connectivity.

## How to set up the Python environment

From this `agent_factory` folder, move to its parent before creating the
**shared operator** environment. If already created, reuse it.

```powershell
Set-Location ..
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

The working directory must contain the `agent_factory` package; do not run
`cli.py` as a standalone script or install framework packages into this
environment. See [shared setup](../readme.md#how-to-set-up-the-python-environment)
for full checkout/consumer paths.

## How to run the code

Stay in the parent `40-agent-factory` folder. Help needs no Azure configuration:

```powershell
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory monitoring-export --help
```

For an offline target plan, first prepare
[consumer configuration](../readme.md#how-to-run-the-code), then replace the
path and target key below:

```powershell
$Config = "C:\code\my-aifactory\aifactory\agent-factory\config.json"
$Target = "project001-dev"
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge
```

Expect JSON describing one resolved target and the selected agent with
`"mutations": false`; it does not establish Azure readiness. Continue with the
root guide's `discover`/`preflight`, ingestion, explicit `deploy --apply` and
`invoke` sequence, or the dedicated [RAG entry point](../45-rag-agent/readme.md).
Do not run every module as if each were an independent application.

To exercise the offline monitoring implementation without a live result file:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_monitoring.py
```

This runs synthetic contract checks, not an inference request or Azure report
publication. For exporting real recorded results, use the
[monitoring example](../readme.md#offline-monitoring-ml-reports).

## Storage and format boundaries

None of these utilities turns arbitrary
PDFs, images or audio into supported training/retrieval inputs without an
explicit adapter. `load_selection` merges root storage defaults with per-target
selection profiles. `FactoryConfig` and exported `Target` carry
`use_common_datalake_storage`, `storage_resource_group` and `storage_container`;
`Target.storage_id` uses the selected storage RG, never the Foundry project RG
by assumption. `Target.resolve_container` rejects contradictory overrides.

The flag is strictly boolean: true selects configured common storage, false
configured project data storage. Only omission retains legacy `2001` discovery
and route-specific containers. All examples, including
[45-rag-agent](../45-rag-agent/readme.md), inherit explicit selection without
moving Foundry/Search/project identities or renaming physical lake paths.
