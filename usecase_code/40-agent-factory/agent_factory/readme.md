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

<!-- project-team:start -->
## Project-team quickstart

Use the existing `agent_factory` Python modules for agent definitions and
single-target operator commands. This is different from the core team's
`azurefactory` administration client. There is no separate published
`AgentFactoryClient` to install.

### 1. Prepare your project copy

From the repository root, or use the equivalent copied directory
`aifactory-usecase-code\40-agent-factory` in your orange project:

```powershell
Set-Location .\usecase_code\40-agent-factory
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m agent_factory --help
```

Keep your project configuration outside generated use-case code:
copy [config.example.json](../config.example.json) to
`aifactory\agent-factory\config.json`, then have the operator resolve the
target key, environment, variables-file path and selected storage profile.
Do not run the unresolved example against Azure. See
[configuration ownership](../readme.md#separation-and-template-copying) and
[storage selection](../readme.md#one-storage-selection-for-every-example).

### 2. Inspect agent definitions offline with Python

Save this as `inspect_agents.py` in the Agent Factory root and run
`.\.venv\Scripts\python.exe .\inspect_agents.py`.
It reads the maintained catalog without credentials, network access, model
calls, deployment or local writes.

```python
import json
from agent_factory.catalog import agent_catalog

agents = agent_catalog()
print(json.dumps([
    {"name": agent["name"], "kind": agent["kind"],
     "framework": agent["framework"], "role": agent["metadata"]["aifactory.role"]}
    for agent in agents
], indent=2))
```

The default catalog contains knowledge/reviewer/documentation prompt agents,
hosted framework examples and a multi-agent helpdesk team. An entry is a
definition, not proof that its framework, model or knowledge source is deployed.
Read the real [catalog](catalog.py),
[prompt agents](../41-single-agent/prompt-agent/readme.md),
[hosted examples](../41-single-agent/hosted-agent/readme.md) and
[multi-agent examples](../42-multi-agent/readme.md).

### 3. Make an offline single-target plan

Save this separate program as `plan_agents.py` in the same directory. Supply
the absolute path to your reviewed project configuration and its exact target
key when prompted. `plan` validates local configuration; it does not
authenticate, discover Azure resources or prove connectivity.

```python
import json
from pathlib import Path
from agent_factory.cli import parser, run

config_path = Path(input("Reviewed configuration path: ").strip()).resolve(strict=True)
target_key = input("Exact target key from that configuration: ").strip()
if not target_key:
    raise ValueError("Select one target explicitly.")
arguments = parser().parse_args([
    "plan", "--config", str(config_path), "--target", target_key,
])
plan = run(arguments)
assert plan["mutations"] is False
print(json.dumps({"mutations": plan["mutations"],
                  "agents": [agent["name"] for agent in plan["agents"]]}, indent=2))
```

The equivalent CLI plan is also offline:

```powershell
$config = Read-Host "Absolute reviewed configuration path"
$target = Read-Host "Exact target key"
.\.venv\Scripts\python.exe -m agent_factory plan --config $config --target $target
```

### 4. Optional live work: review before applying

Stop after the plan unless the operator has reviewed the target, existing
Foundry/model resources, selected data account, dataset terms, private DNS,
identity permissions and cost budget. `discover` and `preflight` read Azure;
they are not offline tests. Ingestion, knowledge configuration and deployment
are distinct mutations requiring `--apply`; invocation can incur model costs.

Follow the maintained [operator commands](../readme.md#operator-commands-powershell)
and [ingestion/knowledge/deployment sequence](../readme.md#data-and-foundry-iq)
for **one explicit `--target`**. Do not silently enable public access, approve
private links, lift a policy gate or guess a resource name.
Python integrations use the actual [selection and command entry points](cli.py),
[OAuth-backed `project_client` and prompt lifecycle](prompt.py) and
[hosted deployment implementation](hosted.py); the operator CLI preserves the
same ownership, storage and grounding checks.

For source-bound RAG use [45-rag-agent](../45-rag-agent/readme.md), not an
unbounded storage scan. Continue with the
[ML Model Factory SDK](../../50-ml-model-factory/user-config/readme.md#project-team-quickstart)
when your project also trains models.
<!-- project-team:end -->
