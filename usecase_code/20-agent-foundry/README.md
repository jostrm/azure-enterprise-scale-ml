# Agents Foundry examples – how to run

## Pre-reqs) AI Factory services to have enabled (PREREQUISITES)
IF you have a "core team", ask your core team to enable them: 

- enableAIFoundry: true
- enableAISearch: true
- You can turn these on via the AI Factory install wizard. Full setup (with wizard) is in [documentation/v2/20-29/24-end-2-end-setup.md](../../documentation/v2/20-29/24-end-2-end-setup.md).

## 1) Set up a local Python env
- Use Python 3.10+.
- Create a venv in this folder (not committed):
    - Windows: `python -m venv .venv && .venv\Scripts\activate`
    - macOS/Linux: `python -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install -r agent_foundry/requirements.txt`
- Sign in to Azure so `DefaultAzureCredential` works: `az login` (needs RBAC access to the AI Foundry account/project, AI Search, and the resource group noted in the scripts).

## 1a) Set the .env variables
- TODO: Rename [../.env.template](../.env.template) to `.env` and set the variables.

## 1b) Run code: 
`python .\agent_02_multiagent.py`

, or with a default question: 

`python agent_foundry/agent_02_multiagent.py --query "top 5 fruits by calorie"`

## 1c) Agent examples: Common behaviour
- On start you are prompted to create new agents or reuse existing ones; choose reuse unless you need fresh names.
- On exit you are prompted to keep or delete the agents (and indexes); choose cleanup to remove them.
- Configuration: Subscription ID, Tenant ID, Foundry name, AI Search name etc, are read from the .env file
    - TODO: Rename [../.env.template](../.env.template) to .env and set the variables.


## 2) Single-agent RAG example
- File: [../agent_foundry/agent_01_rag_test.py](../agent_foundry/agent_01_rag_test.py)
- What it does: indexes [../data/Joakim.md](../data/Joakim.md) into Azure AI Search using the AI Foundry account’s embedding deployment, then creates one agent with the AI Search tool and asks “How to reset Robot-Joakim?”.
- Run (from this folder): `python agent_foundry/agent_01_rag_test.py --reindex` (omit `--reindex` to reuse an existing index). The script prompts before cleanup; choose yes to delete the agent/thread when done.

## 3) Multi-agent orchestrator
- File: [../agent_foundry/agent_02_multiagent.py](../agent_foundry/agent_02_multiagent.py)
- What it does: builds three agents plus a router: Router → Coding Agent (CodeInterpreter) or RAG Agent (AI Search / Robot-Joakim) → Presenter Agent (CodeInterpreter). Coding routes produce charts; RAG routes return structured JSON. Agents are loaded from the [../agent_foundry/multi-agent](../agent_foundry/multi-agent) modules via importlib.
- Run examples (from this folder):
    - `python agent_foundry/agent_02_multiagent.py`
    - `python agent_foundry/agent_02_multiagent.py --query "top 5 fruits by calorie"`
    - `python agent_foundry/agent_02_multiagent.py --query "How to reset Robot-Joakim?"`
    - Add `--no-cleanup` to keep agents/threads; add `--new-agents` to force fresh ones.
- Output: presenter response prints to console; CodeInterpreter chart images (for CODING route) are saved under [../agent_foundry/output](../agent_foundry/output).


### Example output (anonymized resources)
If you run in a terminal:
`python agent_foundry/agent_02_multiagent.py --query "top 5 fruits by calorie"`

You will see output similar to:
```
====================================================================
    Multi-Agent Orchestrator
    Router → (CodingAgent | RAGAgent) → PresenterAgent
====================================================================

    Query: "top 5 fruits by calorie"

[1] DefaultAzureCredential (RBAC)…

[2] Connecting to AI Foundry project…
        https://<foundry-account>.services.ai.azure.com/api/projects/<project-name>

[3] Resolving AI Search connection…
        Matched: name='<search-conn>'  target='https://<search-name>.search.windows.net/'

[4] Checking for existing agents…
        Found 2 existing complete set(s):
            salt='t7weh'  router=asst_xxx  coding=asst_xxx  rag=asst_xxx  presenter=asst_xxx
            salt='ktqpv'  router=asst_xxx  coding=asst_xxx  rag=asst_xxx  presenter=asst_xxx

Create new agents? (y/n): y
        Creating fresh agents…
        Generating new salt='us2bf'…
        [01] RouterAgent-us2bf       id=asst_xxx
        [02a] CodingAgent-us2bf      id=asst_xxx
        [02b] RAGAgent-us2bf         id=asst_xxx
        [03] PresenterAgent-us2bf    id=asst_xxx

[5] Router Agent → routing query…
        Raw router response: {"route": "CODING_AGENT", "reason": "User is asking for a data analysis of fruit calorie content."}
        Route: CODING_AGENT  (User is asking for a data analysis of fruit calorie content.)

[6] Coding Agent → running code interpreter…
        Specialist response (1518 chars)

[7] Presenter Agent → formatting output (SOURCE=CODING_AGENT)…

====================================================================
    FINAL OUTPUT  (formatted by Presenter Agent | route=CODING_AGENT)
====================================================================
CHART_TYPE:    Bar chart
TITLE:         Top 5 Fruits by Calorie Content (per 100g)
DATA_SUMMARY:
| Fruit    | Calories (kcal per 100g) |
|----------|--------------------------|
| Coconut  | 354                      |
| Dates    | 277                      |
| Avocado  | 160                      |
| Olives   | 115                      |
| Banana   | 89                       |

INSIGHT:
The chart illustrates the calorie content of the top 5 fruits per 100 grams. Coconut has the highest caloric content at 354 kcal, followed by Dates with 277 kcal, Avocado at 160 kcal, Olives at 115 kcal, and Banana at 89 kcal. This insight is valuable for nutrition planning as it highlights fruits that are higher in calories.
====================================================================

Would you like to delete all agents and clean up? (y/n):
```

## Notes
- Both scripts assume the hard-coded subscription, tenant, resource group, AI Foundry endpoints, and AI Search names are valid for your account. Update those constants if you need to point to a different environment.
- Ensure your account has rights to create/read AI Search indexes and use the AI Foundry deployments referenced in the scripts.

