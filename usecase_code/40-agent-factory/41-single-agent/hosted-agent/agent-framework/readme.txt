# Agent Framework - Microsoft
- https://github.com/microsoft/agent-framework

This legacy pointer supplements the complete guide in the adjacent readme.md.

Prerequisites
-------------
Reuse cached Azure CLI OAuth first; browser sign-in is needed only if that
cached authentication is unavailable for the selected tenant.

Python 3.13, PowerShell, Azure CLI OAuth for the selected tenant, private
Foundry/Search connectivity, an existing compatible Foundry model, hosted
build/compute access and runtime identity RBAC are required. Complete data
ingestion and Foundry IQ verification for the exact target/storage first;
knowledge.json (and ingestion.json in ADF mode) belongs under the consumer
config directory's .agent-factory\<account>\<project>. Deploy the knowledge
prompt participant and wait until it is active before deploying this worker.
Expanded-readonly additionally requires verified private MCP. See the factory
root readme.md and hosted-agent\readme.md for the full prerequisites.

How to set up the Python environment
-----------------------------------
Run these PowerShell commands from the factory root, NOT this framework folder.
For a copied consumer use
C:\path\to\consumer\aifactory-usecase-code\40-agent-factory instead of the
source-tree path below. Replace the config placeholder and target with your values.

Set-Location "C:\code\code_py_25\003_aifactory_sub\azure-enterprise-scale-ml\usecase_code\40-agent-factory"
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$Config = "C:\path\to\consumer\aifactory\agent-factory\config.json"
$Target = "project001-dev"

No activation is needed. These are operator dependencies; Foundry's Python 3.13
remote build installs this framework's requirements.txt separately. Do not
combine framework runtime dependencies in the operator virtual environment.

How to run the code
-------------------
Keep the same root directory/session. The names below use the default
agent_prefix of aif; replace it in both agent names if your config customizes it.

# Offline help and catalog/config plan; no Azure calls.
.\.venv\Scripts\python.exe -m agent_factory --help
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-knowledge --agent aif-agent-framework
# Online, read-only Azure/network preflight.
.\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
# MUTATING: only after grounding verification; deploy the participant first.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-knowledge --apply
# MUTATING: requires the knowledge participant to be active.
.\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-agent-framework --apply
# Online inference, potentially billable.
.\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-agent-framework --input "How do I reset my password?"

Expect a mutations:false plan, an active hosted version/ID, and invocation JSON
with agent, response_id and grounded text retaining source links. Outer tool_calls
may be empty because participant verification runs inside the host. These are
expected results, not evidence of a live deployment.

Do not execute raw main.py on your workstation. Deployment generates
agent_spec.json and packages hosted_common.py; Foundry sets
FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_RESOURCE_ENDPOINT and
AZURE_AI_MODEL_DEPLOYMENT_NAME, and supplies managed/workload identity.
The runtime excludes local Azure CLI/browser credentials. The adjacent
readme.md contains the maintained framework-specific explanation and links.
