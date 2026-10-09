# Multi-agent helpdesk: retrieve, review and synthesize

`aif-helpdesk-team` coordinates two separately persisted prompt agents.
It asks `aif-knowledge` for evidence, passes those findings to `aif-reviewer`,
and synthesizes the reviewed answer. Both participants retain their own Foundry
identity and definition; the coordinator does not create duplicate agents.

Both participants inherit the
[root common/project storage selection](../readme.md#one-storage-selection-for-every-example)
through the shared knowledge agent. No participant-specific paths change;
Foundry/Search and their identities remain in the project resource group.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus, not one dataset per participant
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` through `aif-knowledge`. See [source paths](../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Azure AI Projects SDK | Python | Microsoft Entra ID

`<ADF-prefix>` is `kaggle-rag-v1/adf/<project-id-hash>` for an explicit storage
profile; use the ingestion result's actual prefix. Only legacy omitted-flag
ADF mode retains the shorter `kaggle-rag-v1` prefix.

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, private Foundry/Search connectivity,
  and the [root operator prerequisites](../readme.md#prerequisites).
  Select a consumer `aifactory\agent-factory\config.json`, its variables file and
  an existing project/model deployment.
- Complete [ingestion](../43-data/readme.md) and
  [Foundry IQ verification](../readme.md#how-to-run-the-code). The config directory's
  `.agent-factory\<account>\<project>` must contain verified `ingestion.json`
  (ADF mode) and `knowledge.json` for the same target and storage selection.
- Both `aif-knowledge` and `aif-reviewer` must be active, persisted **prompt**
  agents before deploying the coordinator. Commands below create/reuse these
  participants first; they are not packaged into the coordinator.
- Hosted build/compute quota, package-build network access, and dedicated
  runtime identity access to the participants and model are required. See
  [hosted boundaries](../41-single-agent/hosted-agent/readme.md#framework-prerequisites-and-boundaries).
  Expanded-readonly deployments also need [verified private MCP](../44-azure-mcp/readme.md).

## How to set up the Python environment

Use the factory root rather than `42-multi-agent`. For a copied consumer tree,
substitute `C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` for the
first path. Replace the config placeholder and target with real consumer values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

No activation is required. The root requirements install the operator only.
Foundry installs [this runtime's requirements](requirements.txt), including
`azure-ai-projects`, during its Python 3.13 remote build; do not merge them with
other framework environments. See [shared setup](../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same root directory/session. These exact names use the default
`agent_prefix` of `aif`; replace every prefix if your config changes it.

```powershell
# Offline: help and a plan listing both participants and their coordinator.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-reviewer --agent aif-helpdesk-team

# Online, read-only Azure/network preflight.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target

# MUTATING: after grounding verification, deploy participants first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --agent aif-reviewer --apply

# MUTATING: after both prompt participants are active, deploy the hosted coordinator.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-helpdesk-team --apply

# Online inference, potentially billable.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-helpdesk-team --input "How do I reset my password?"
```

An explicit hosted `--agent` is sufficient; do not add `--include-hosted` to
deploy unrelated frameworks. Expect `mutations: false` in the plan, service
version/ID and `active` status for the hosted deployment, then JSON with `agent`,
`response_id` and a reviewed `text` answer preserving source links and uncertainty.
The outer response's `tool_calls` may be empty: knowledge-tool validation happens
inside the coordinator. Preflight or a greeting alone does not test this chain.
No live deployment or successful inference is implied by the examples.

Do not run `python .\42-multi-agent\main.py` directly on your workstation.
The deployment packages `main.py`, this runtime's requirements, generated
`agent_spec.json` and shared `hosted_common.py`. Foundry supplies
`FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_RESOURCE_ENDPOINT`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME` and its managed/workload identity.
The worker excludes local CLI/browser credentials; the operator's Azure login
does not become runtime authentication.

## Execution

```text
Question -> knowledge participant -> evidence-aware reviewer -> synthesis -> answer
```

The sequence matters: review receives the actual draft, not just the original
question. Source URLs are retained after synthesis. In the expanded profile,
the knowledge participant can alternatively inspect live Azure inventory using
the private read-only MCP server. Inventory is not synthetic helpdesk policy.

Deploy the active prompt participants first, then select
`--agent aif-helpdesk-team` in the [operator workflow](../readme.md#how-to-run-the-code).
Public documentation approval is not propagated by this text-only coordinator;
call the documentation agent separately. There is no training pipeline and no
automatic Agent Map relationship rendering.
