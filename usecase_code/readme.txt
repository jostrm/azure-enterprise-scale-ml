How to setup & Run code samples
=================================

PREREQUISITES
-------------
- Python 3.10+
- Azure CLI installed (az login)
- An AI Factory with AI Foundry and AI Search enabled
  (see documentation/v2/20-29/24-end-2-end-setup.md)

STEP 1 – Configure environment variables
-----------------------------------------
1. Copy .env.template to .env  (in this folder)
2. Fill in the <TODO> placeholders:
   - SUBSCRIPTION_ID, TENANT_ID, RESOURCE_GROUP
   - FOUNDRY_ACCOUNT_ENDPOINT, FOUNDRY_PROJECT_ENDPOINT
   - AI_SEARCH_NAME, AI_SEARCH_INDEX_NAME
   - CHAT_MODEL, EMBEDDING_MODEL
   - AGENT_NAME, AGENT_INSTRUCTIONS, etc.

STEP 2 – Create a Python virtual environment
---------------------------------------------
From this folder (usecase_code/):

  Bash / macOS / Linux:
    cd 20-agent-foundry
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

  Windows (PowerShell):
    cd 20-agent-foundry
    python -m venv .venv
    .venv\Scripts\Activate.ps1          (run directly, do NOT prefix with 'python')
    pip install -r requirements.txt

  Windows (cmd):
    cd 20-agent-foundry
    python -m venv .venv
    .venv\Scripts\activate.bat
    pip install -r requirements.txt

STEP 3 – Sign in to Azure
--------------------------
  az login

  Make sure your account has RBAC access to the AI Foundry
  account/project, AI Search, and the resource group.

STEP 4 – Run the code samples
------------------------------
Single-agent RAG example:
  python agent_01_rag_test.py --reindex

Multi-agent example:
  python agent_02_multiagent.py

Run with a custom query:
  python agent_02_multiagent.py --query "top 5 fruits by calorie"

NOTES
-----
- On start you are prompted to create new agents or reuse existing ones.
- On exit you are prompted to keep or delete agents and indexes.
- Omit --reindex to reuse an existing AI Search index.
