# Foundry prompt agents

This folder describes the agents created by the shared catalog and prompt
deployment code. Foundry runs their model and managed tool calls; there is no
application server to implement here.

## Use case summary

- Use case type: RAG with LLM (knowledge and documentation); LLM evidence review is a supporting role
- Data type: Tabular | Document (CSV-packaged articles and retrieved text)
- Number of source data sets: 1 for `aif-knowledge`; 0 for the default reviewer and public-documentation agent; the expanded reviewer reuses the same 1 corpus
- Data sources: `<selected-storage>/<selected-container>/<ADF-prefix>/knowledge/items.json` via Foundry IQ; see [source paths](../../43-data/readme.md#data-sources-and-lake-layout). Microsoft Learn uses `https://learn.microsoft.com/api/mcp`, not a lake dataset.
- Inference type: Online
- Technology used in full chain: Azure Data Factory | Azure Storage | Azure AI Search | Microsoft Foundry | Microsoft Learn MCP | Microsoft Entra ID

## Prerequisites

Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

- Python 3.13, PowerShell, Azure CLI OAuth, private Foundry/Search connectivity,
  and operator/project identity permissions from the [root prerequisites](../../readme.md#prerequisites).
- A consumer `aifactory\agent-factory\config.json`, its variables file, an existing
  project and compatible model deployment. `aif` below is the default
  `agent_prefix`; replace all agent-name prefixes if customized.
- Before deploying `aif-knowledge`, complete [ingestion](../../43-data/readme.md)
  and [Foundry IQ configuration/verification](../../readme.md#how-to-run-the-code).
  The config directory's `.agent-factory\<account>\<project>\knowledge.json`
  must record verified retrieval for this target, project connection and storage
  selection; ADF mode also needs verified `ingestion.json`.
- The expanded profile additionally requires [verified private MCP](../../44-azure-mcp/readme.md).
  The default reviewer needs supplied evidence, not its own corpus.
  Microsoft Learn tools always require approval and must never receive private data.

## How to set up the Python environment

Run from the factory root, **not** `prompt-agent`. A copied consumer uses
`C:\path\to\consumer\aifactory-usecase-code\40-agent-factory` instead of the
source-tree path below. Replace `$Config` and `$Target` with your actual values.

```powershell
Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"
```

These are the operator requirements; prompt agents have no local `main.py` or
framework runtime to install. Activation is unnecessary; see
[shared Python setup](../../readme.md#how-to-set-up-the-python-environment).

## How to run the code

Continue in the same factory-root PowerShell session:

```powershell
# Offline help and explicit catalog selection; no Azure calls.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-reviewer --agent aif-docs

# Online, read-only Azure/network checks; this does not verify grounding.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target

# MUTATING: after the grounding prerequisites; creates/reuses and routes prompt versions.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --agent aif-reviewer --agent aif-docs --apply

# Online inference (potentially billable), one exact agent per call.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-knowledge --input "How do I reset my password?"
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-reviewer --input "Review this draft: Everyone must reset passwords daily. No supporting evidence was supplied. Identify unsupported claims."
```

The plan reports `mutations: false`; deploy reports version/ID records with
`created` or `unchanged`. A successful invocation returns `agent`, `response_id`
and `text`; knowledge must also show a successful `knowledge_base_retrieve`
tool call. The default reviewer should identify the missing evidence.
For `aif-docs`, use an approval-capable Foundry client/playground: this CLI does
not implement the approval-response round trip, so a tool-approval request is
not a successful answer. Do not disable approvals to make an invocation pass.
These commands are instructions, not evidence of a live deployment.

## Run this use case with an AI assistant

Copy a prompt, replace the `<...>` placeholders, and paste it into the assistant. Every assistant has a **demo data** prompt and a **your own data** prompt. [How these prompts work](../../readme.md#run-the-use-cases-with-an-ai-assistant) explains where to paste them and what each assistant can and cannot do.

### AI Factory Agent Chat

Paste into the [AI Factory Agent Chat](../../40-aifactory-agent/readme.md) with the **Project** explanation view and your scope selected. It answers from the indexed documentation with citations; the Factory actions panel only prepares a reviewable plan, which a person approves.

<details>
<summary><b>Demo data</b></summary>

```text
Explain the prompt-agent example in usecase_code/40-agent-factory/41-single-agent/prompt-agent (aif-knowledge, aif-reviewer and aif-docs) for my scope <project001-dev>: the prerequisites, the order of the steps (43-data ingestion and Foundry IQ before aif-knowledge), and which steps write to Azure or are billed. Cite the documentation and tell me what my project is still missing.

Then, in the Factory actions panel (it prepares a reviewable plan; a person approves it):
/create-agent-oftype-for-project
  type: 41-single-agent
  project_resource_id: </subscriptions/<sub>/resourceGroups/<project-rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>>
(This works only if the platform team has approved a workload profile for this type; otherwise the chat reports the blocker.)
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
I want aif-knowledge to answer from our own documents: <describe them, e.g. IT support articles as UTF-8 text>. The prompt-agent corpus is the pinned Kaggle helpdesk set, so explain, with citations, how to bind my documents through 45-rag-agent instead: the supported formats, the SHA-256 pin, the required `acl`, the size limits, and whether to use common lake or project storage (`use_common_datalake_storage`). Also tell me how to point the shared config at my own storage account and container.
```

</details>

### GitHub Copilot and Claude Code (one prompt for both)

The same prompt works in **GitHub Copilot** (VS Code Chat in *Agent* mode) and **Claude Code** (run `claude` in the repository root). Use a machine that is signed in to Azure CLI and connected to the AI Factory private network. Both assistants read this repository's `AGENTS.md`.

<details>
<summary><b>Demo data</b></summary>

```text
Deploy the prompt agents in usecase_code/40-agent-factory/41-single-agent/prompt-agent with the demo helpdesk corpus and ask aif-knowledge a question.

First read AGENTS.md, then usecase_code/40-agent-factory/readme.md (shared setup), usecase_code/40-agent-factory/41-single-agent/prompt-agent/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Set up the shared operator from usecase_code/40-agent-factory: a Python 3.13 `.venv` with `requirements.txt`, my consumer config at <C:\path\to\consumer>\aifactory\agent-factory\config.json (create it from config.example.json only if it does not exist yet, then help me fill in the storage, target and variables_file values and show me the result) and target <project001-dev>.
3. Run `plan` for --agent aif-knowledge --agent aif-reviewer --agent aif-docs (offline, `mutations: false`), then `discover` and `preflight` (read-only), and summarize.
4. Check that 43-data ingestion and Foundry IQ knowledge are verified for this target (journals beside my config). If not, stop and tell me to run 43-data first.
5. After my approval, run `deploy ... --apply` for the three agents.
6. After my approval, run the billed `invoke --agent aif-knowledge --input "How do I reset my password?"` and show the answer and the grounding tool call.
7. Then invoke aif-reviewer with: "Review this draft: Everyone must reset passwords daily. No supporting evidence was supplied. Identify unsupported claims." Do not invoke aif-docs from the CLI; it needs an approval-capable client.

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
Deploy the prompt agents in usecase_code/40-agent-factory/41-single-agent/prompt-agent against my own AI Factory storage and ask them my own questions.

First read AGENTS.md, then usecase_code/40-agent-factory/readme.md (shared setup), usecase_code/40-agent-factory/41-single-agent/prompt-agent/readme.md, usecase_code/40-agent-factory/45-rag-agent/readme.md.

1. Check prerequisites and report anything missing: Python 3.13, Azure CLI with a cached sign-in to my tenant (only if missing, ask me to run `az login --tenant <tenant-id>`), and the AI Factory VPN/private DNS.
2. Set up the shared operator from usecase_code/40-agent-factory: a Python 3.13 `.venv` with `requirements.txt`, my consumer config at <C:\path\to\consumer>\aifactory\agent-factory\config.json (create it from config.example.json only if it does not exist yet, then help me fill in the storage, target and variables_file values and show me the result) and target <project001-dev>.
3. Use my storage: `use_common_datalake_storage` = <true | false>, account <storage-account>, resource group <rg>, container <container> (it already exists and is private). Show me the config diff, then run `plan`, `discover` and `preflight`.
4. Follow the README order (43-data ingestion, Foundry IQ, then `deploy --apply` with my approval).
5. Invoke aif-knowledge (billed, after my approval) with my questions: <question 1>, <question 2>.
6. If I want my own documents instead of the pinned helpdesk corpus, do not change the pins: draft a 45-rag-agent source binding for them and stop for my review. My documents: <describe them, e.g. 200 HR policy articles as UTF-8 text>, published as <shared-lake-jsonl | knowledge-json-array> at <container>/<blob path> in <common lake | project storage>.

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
Build a helpdesk assistant prototype with three agent tabs:
- "Knowledge": a chat that answers IT helpdesk questions with a "Sources" list. Mock topics: Android email setup, jammed printer, Webex, wireless network, backups. Example: "How do I reset my password?"
- "Reviewer": paste a draft answer plus evidence; it highlights unsupported claims in red, with a short explanation for each.
- "Docs": a Microsoft Learn search assistant that always shows an "Approval required before calling the tool" card, with Approve and Reject buttons.
Show which agent answered and whether the answer was grounded (a badge with "knowledge_base_retrieve: success | missing").

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

<details>
<summary><b>Your own data</b></summary>

```text
Build the same three-tab helpdesk assistant prototype for <company name>.
Use my own knowledge articles as the mock corpus (title | text): <paste 5-15 articles>.
Use my own example questions: <paste questions>. The Knowledge tab should answer only from the pasted articles, cite the article title, and say "not in the knowledge base" otherwise.

Constraints: front end only, no API keys or secrets in the code, and all data is mock or pasted sample data. Put every backend call behind one clearly named function in a single file, returning mock data for now, so it can later call an API my platform team approves.
```

</details>

## Video walkthrough tutorial - TBA

A video walkthrough tutorial, recorded by a person, will be published here soon. It shows how to run this code, step by step, to achieve the result described in this README.

## Roles and actual tools

| Agent | Default behavior | Expanded read-only profile |
| --- | --- | --- |
| `aif-knowledge` | Retrieves synthetic helpdesk evidence with `knowledge_base_retrieve`. | Also calls `group_resource_list` on the private Azure MCP server. |
| `aif-reviewer` | Reviews supplied drafts/evidence; no default tools. | Adds Foundry IQ and private Azure inventory. |
| `aif-docs` | Uses approval-gated `microsoft_docs_search` and `microsoft_docs_fetch`. | Adds approval-gated `microsoft_code_sample_search` and private Azure inventory. |

The ingestion chain applies to helpdesk grounding; documentation-only questions
do not execute ADF or read the lake. Public documentation queries must not include
private tenant data. An unsupported product-specific question should expose the
evidence gap rather than relabel a generic helpdesk procedure as product guidance.

Definitions live in [catalog.py](../../agent_factory/catalog.py); lifecycle and
tool configuration live in [prompt.py](../../agent_factory/prompt.py).
Use the [operator commands](../../readme.md#how-to-run-the-code) from the
Agent Factory root with the consumer's explicit configuration.

The [data guide](../../43-data/readme.md) explains the selected common/project
storage corpus and the separate common-lake RAG snapshot.