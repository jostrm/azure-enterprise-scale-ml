# GitHub Copilot SDK helpdesk agent

`aif-copilot-sdk` uses the GitHub Copilot SDK as its agent runtime, with a
bring-your-own-model Responses provider pointed at Microsoft Foundry. Grounding
is performed by the shared host through `aif-knowledge`, before Copilot receives
the conversation and evidence.

## Use case summary

- Use case type: RAG with LLM
- Data type: Tabular | Document (CSV-packaged knowledge articles; text at inference)
- Number of source data sets: 1 shared helpdesk corpus
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` through the persisted knowledge agent. See [source paths](../../../43-data/readme.md#data-sources-and-lake-layout).
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | GitHub Copilot SDK | Microsoft Entra ID

This is not a desktop coding assistant. Built-in tools, shell/file permissions,
host Git operations, MCP discovery and GitHub auto-login are disabled. Optional
Azure inventory comes from the verified private knowledge-participant path,
not a general-purpose command executor.

The native SDK runtime must be available or its supported release download must
be reachable. Scratch state is isolated in a writable temporary directory and
cleaned up after each request; the application directory may be read-only.

Deploy with `--agent aif-copilot-sdk` using the
[shared hosted lifecycle](../readme.md#persistent-deployment-integration).
Source: [GitHub Copilot SDK](https://github.com/github/copilot-sdk).

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, a configured consumer target and
  private Foundry/Search access; see [root prerequisites](../../../readme.md#prerequisites).
- An existing Foundry Responses-compatible model, hosted build/compute access,
  and runtime identity permissions. Follow [hosted prerequisites](../readme.md#prerequisites):
  verify ingestion and `knowledge.json` for this exact target/storage under the
  config directory's `.agent-factory\<account>\<project>`, and deploy the active
  knowledge prompt participant. Expanded-readonly needs verified private MCP too.
- Stage the SDK-compatible native runtime through supported runtime configuration/cache,
  or allow its pinned, checksum-verified release download. Private networks must
  have these artifacts available; installing the Python package alone is not proof.
  Runtime terms/eligibility and writable per-request scratch space are prerequisites.
  Neither GitHub login nor a public model/API key is used.

## How to set up the Python environment

Use the factory root, **not** `github-copilot-sdk`. For a copied consumer tree use
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` as the first path.
Replace the config placeholder and target with actual consumer values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

No activation is required. This installs the operator; Foundry's Python 3.13
remote build installs [this runtime's requirements](requirements.txt), including
`github-copilot-sdk`. Keep runtime dependencies separate from the operator and
other frameworks. See [shared setup](../../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same root/session. The selector is `aif-copilot-sdk`, not the
folder name. Replace `aif` in both names if the configured `agent_prefix` differs.

```powershell
# Offline help/plan; does not validate model or native runtime availability.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-copilot-sdk
# Online, read-only Azure/network preflight.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
# MUTATING: after grounding verification, deploy the prompt participant first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
# MUTATING: requires an active participant and the native runtime prerequisites.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-copilot-sdk --apply
# Online inference, potentially billable; also exercises the native SDK runtime.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-copilot-sdk --input "How do I reset my password?"
```

Expect `mutations: false` in the plan, an `active` hosted version/ID from deploy,
and invocation JSON with `agent`, `response_id` and grounded `text` preserving
source links. Outer `tool_calls` can be empty because the host checks grounding
internally. An active deployment alone does not prove native runtime startup;
these instructions make no claim of a live successful invocation.

Do not execute raw `main.py` locally. Deployment adds generated `agent_spec.json`
and shared `hosted_common.py`; Foundry supplies `FOUNDRY_PROJECT_ENDPOINT`,
`FOUNDRY_RESOURCE_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME` and managed/workload
identity. Local Azure CLI/browser credentials are excluded. Follow the
[hosted workflow](../readme.md#how-to-run-the-code), not a desktop coding session.
