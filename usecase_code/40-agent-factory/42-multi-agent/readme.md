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

## Run this use case with an AI assistant

Copy a prompt, replace the `<...>` placeholders, and paste it into the assistant. Every assistant has a **demo data** prompt and a **your own data** prompt. [How these prompts work](../readme.md#run-the-use-cases-with-an-ai-assistant) explains where to paste them and what each assistant can and cannot do.

### AI Factory Agent Chat

Paste into the [AI Factory Agent Chat](../40-aifactory-agent/readme.md) with the **Project** explanation view and your scope selected. It answers from the indexed documentation with citations; the Factory actions panel only prepares a reviewable plan, which a person approves.

<details>
<summary><b>Demo data</b></summary>

```text
Explain the multi-agent helpdesk team in usecase_code/40-agent-factory/42-multi-agent for my scope <project001-dev>: how aif-helpdesk-team coordinates aif-knowledge (evidence) and aif-reviewer (review) into one synthesized answer, which participants must be deployed first, what hosted quota and runtime identity access it needs, and which steps write to Azure or are billed. Cite the documentation.

Then, in the Factory actions panel (it prepares a reviewable plan; a person approves it):
/create-agent-oftype-for-project
  type: 42-multi-agent
  project_resource_id: </subscriptions/<sub>/resourceGroups/<project-rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>>
(This works only if the platform team has approved a workload profile for this type; otherwise the chat reports the blocker.)
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
I want the multi-agent helpdesk team to answer from our own documents: <describe them>. Explain, with citations, that the team reuses aif-knowledge for evidence, and how to give aif-knowledge my own corpus (through 45-rag-agent or my own storage selection) without changing the team code. List the steps and permissions; do not change anything.
```

</details>

### GitHub Copilot and Claude Code (one prompt for both)

The same prompt works in **GitHub Copilot** (VS Code Chat in *Agent* mode) and **Claude Code** (run `claude` in the repository root). Use a machine that is signed in to Azure CLI and connected to the AI Factory private network. Both assistants read this repository's `AGENTS.md`.

<details>
<summary><b>Demo data</b></summary>

```text
Deploy the hosted multi-agent helpdesk team in usecase_code/40-agent-factory/42-multi-agent with the demo helpdesk corpus and ask it a question.

First read AGENTS.md, then usecase_code/40-agent-factory/readme.md (shared setup), usecase_code/40-agent-factory/42-multi-agent/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Set up the shared operator from usecase_code/40-agent-factory: a Python 3.13 `.venv` with `requirements.txt`, my consumer config at <C:\path\to\consumer>\aifactory\agent-factory\config.json (create it from config.example.json only if it does not exist yet, then help me fill in the storage, target and variables_file values and show me the result) and target <project001-dev>.
3. Run `plan --agent aif-knowledge --agent aif-reviewer --agent aif-helpdesk-team` (offline), then `preflight` (read-only), and summarize.
4. Confirm that 43-data ingestion and Foundry IQ knowledge are verified for this target; if not, stop.
5. After my approval, `deploy --agent aif-knowledge --agent aif-reviewer --apply`; after a second approval, `deploy --agent aif-helpdesk-team --apply`.
6. After my approval, run the billed `invoke --agent aif-helpdesk-team --input "How do I reset my password?"` and show the reviewed answer, its source links and any stated uncertainty.
7. Do not run 42-multi-agent/main.py locally and do not use --include-hosted.

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
Deploy the hosted multi-agent helpdesk team in usecase_code/40-agent-factory/42-multi-agent against my own AI Factory storage and ask it my own questions.

First read AGENTS.md, then usecase_code/40-agent-factory/readme.md (shared setup), usecase_code/40-agent-factory/42-multi-agent/readme.md, usecase_code/40-agent-factory/45-rag-agent/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Set up the shared operator from usecase_code/40-agent-factory: a Python 3.13 `.venv` with `requirements.txt`, my consumer config at <C:\path\to\consumer>\aifactory\agent-factory\config.json (create it from config.example.json only if it does not exist yet, then help me fill in the storage, target and variables_file values and show me the result) and target <project001-dev>.
3. Use my storage: `use_common_datalake_storage` = <true | false>, account <storage-account>, resource group <rg>, container <container>. Show me the diff, then `plan` and `preflight`.
4. Deploy the participants, then the team, each after my approval.
5. Invoke aif-helpdesk-team (billed, after my approval) with: <question 1>, <question 2>, and show how the reviewer changed each draft.
6. For my own documents, do not change the pinned corpus: draft a 45-rag-agent source binding and stop for my review. My documents: <describe them, e.g. 200 HR policy articles as UTF-8 text>, published as <shared-lake-jsonl | knowledge-json-array> at <container>/<blob path> in <common lake | project storage>.

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
Build a "Helpdesk team" prototype that visualizes a multi-agent answer.
- A chat input (default "How do I reset my password?").
- A step timeline: 1) Knowledge agent retrieves evidence (show 2-3 mock source snippets), 2) Reviewer flags unsupported claims in the draft, 3) Synthesis returns the final answer with source links and an uncertainty note.
- Each step can be expanded to show its input and output. Use mock helpdesk topics: Android email setup, jammed printer, Webex, wireless network, backups.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Build the same "Helpdesk team" prototype for <company name>.
Use my own knowledge articles as evidence: <paste 5-15 articles as title | text>.
Use my own review rules for the reviewer step: <paste rules, e.g. "never promise response times">.
Example questions: <paste questions>.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

## Video walkthrough tutorial - TBA

A video walkthrough tutorial, recorded by a person, will be published here soon. It shows how to run this code, step by step, to achieve the result described in this README.

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
