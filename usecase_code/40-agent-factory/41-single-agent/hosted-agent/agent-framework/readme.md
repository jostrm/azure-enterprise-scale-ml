# Microsoft Agent Framework helpdesk agent

`aif-agent-framework` demonstrates a Foundry-hosted Python agent implemented
with Microsoft Agent Framework. The shared host first obtains cited evidence
from `aif-knowledge`; `main.py` then uses `Agent`, `Message` and
`OpenAIChatClient` to produce the final response through Foundry.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json`, accessed indirectly through `aif-knowledge`. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Agent Framework | Microsoft Entra ID

The expanded read-only profile also lets the knowledge participant retrieve
live Azure resource inventory. It does not give this worker arbitrary Azure
commands or a public-model fallback. No model training, image processing or
event-stream processing is implemented.

Deploy through the [shared hosted lifecycle](../readme.md#persistent-deployment-integration),
using `--agent aif-agent-framework` and a configured Foundry model.
Keep [requirements.txt](requirements.txt) isolated per runtime.

Source: [Microsoft Agent Framework](https://github.com/microsoft/agent-framework).

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, a configured consumer target and
  private Foundry/Search access; follow the [root prerequisites](../../../readme.md#prerequisites).
- An existing Foundry model compatible with the `OpenAIChatClient` adapter,
  hosted build/compute access and runtime identity permissions. Complete the
  [hosted prerequisites](../readme.md#prerequisites), including verified ingestion
  and `knowledge.json` for the same target/storage under the config directory's
  `.agent-factory\<account>\<project>`, then deploy the knowledge prompt participant.
  Expanded-readonly also requires verified private MCP.

## How to set up the Python environment

Use the factory root, **not this framework folder**. A copied consumer uses
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` instead of the first
path below. Replace the config placeholder and target with actual consumer values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

This installs the operator only, without shell activation. Foundry's Python 3.13
remote build installs [this runtime's requirements](requirements.txt), including
`agent-framework-core` and `agent-framework-openai`; do not merge them with other
frameworks. See [shared setup](../../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same root/session. `aif` is the default `agent_prefix`; replace
it in **both** names if customized.

```powershell
# Offline: no Azure calls; plan does not validate runtime/model availability.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-agent-framework
# Online, read-only Azure/network preflight.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
# MUTATING: after grounding verification, deploy the prompt participant first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
# MUTATING: requires the knowledge participant to be active.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-agent-framework --apply
# Online inference, potentially billable.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-agent-framework --input "How do I reset my password?"
```

Expect `mutations: false` from the plan, an `active` hosted version/ID from
deployment, then JSON with `agent`, `response_id` and grounded `text` retaining
source links. Participant tool checks occur inside the host; outer `tool_calls`
can be empty. These are expected outcomes, not a claim of live validation.

Do not execute raw `main.py` on the workstation: deployment adds generated
`agent_spec.json` and shared `hosted_common.py`. Foundry sets the project/resource
endpoints and model (`FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_RESOURCE_ENDPOINT`,
`AZURE_AI_MODEL_DEPLOYMENT_NAME`) and supplies managed/workload identity.
Local CLI/browser credentials are excluded by the worker. Use the
[hosted deployment workflow](../readme.md#how-to-run-the-code), not a local
`python main.py` workaround.
