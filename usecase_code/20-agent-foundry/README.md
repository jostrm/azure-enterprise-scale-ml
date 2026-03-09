# Agents Foundry examples – how to run

## Pre-reqs) AI Factory services to have enabled (PREREQUISITES)
IF you have a "core team", ask your core team to enable them: 

- enableAIFoundry: true
- enableAISearch: true
- You can turn these on via the AI Factory install wizard. Full setup (with wizard) is in [documentation/v2/20-29/24-end-2-end-setup.md](../../documentation/v2/20-29/24-end-2-end-setup.md).

## 1) Set up a local Python env
- Use Python 3.10+.
- Go to this folder: `usecase_code\20-agent-foundry`
- Create a venv in this folder (not committed):
    - Windows: `python -m venv .venv && .venv\Scripts\activate`
    - macOS/Linux: `python -m venv .venv && source .venv/bin/activate`
- Install deps: `pip install -r requirements.txt`
- Sign in to Azure so `DefaultAzureCredential` works: `az login` (needs RBAC access to the AI Foundry account/project, AI Search, and the resource group noted in the scripts).

## 1a) Set the .env variables
- TODO: Rename [../.env.template](../.env.template) to `.env` and set the variables.

## 1b) Run code: 
`python .\agent_02_multiagent.py`

, or with a default question: 

`python agent_02_multiagent.py --query "top 5 fruits by calorie"`

## 1c) Agent examples: Common behaviour
- On start you are prompted to create new agents or reuse existing ones; choose reuse unless you need fresh names.
- On exit you are prompted to keep or delete the agents (and indexes); choose cleanup to remove them.
- Configuration: Subscription ID, Tenant ID, Foundry name, AI Search name etc, are read from the .env file
    - TODO: Rename [../.env.template](../.env.template) to .env and set the variables.


## 2) Single-agent RAG example
- File: [../agent_01_rag_test.py](../agent_01_rag_test.py)
- What it does: indexes [../data/Joakim.md](../data/Joakim.md) into Azure AI Search using the AI Foundry account’s embedding deployment, then creates one agent with the AI Search tool and asks “How to reset Robot-Joakim?”.
- Run (from this folder): `python agent_01_rag_test.py --reindex` (omit `--reindex` to reuse an existing index). The script prompts before cleanup; choose yes to delete the agent/thread when done.

### Example Output

If you run in a terminal:
`python agent_01_rag_test.py`

You will see output similar to (resource names anonymized):
```
================================================================
  AI Foundry Agent  ×  AI Search Tool
  Data: Joakim.md   |  Query: How to reset Robot-Joakim?
================================================================

[1] Building DefaultAzureCredential (RBAC, no keys)…

Reindex? (y/n): y

[2] Connecting to AI Foundry project…
    https://<foundry-account>.services.ai.azure.com/api/projects/<project-name>

[3] Building AzureOpenAI client for embeddings…
    Account endpoint: https://<foundry-account>.services.ai.azure.com

[4] Parsing Joakim.md…
    4 chunk(s) found:
      [chunk-0] Manual for Joakim-robot with article number: 12345
      [chunk-1] How to: “Switch batteries”:
      [chunk-2] How to reset Joakim-robot
      [chunk-3] How to reset your iPhone to factory settings

[5] Setting up AI Search index '<search-index-name>'…
    Deleted existing index '<search-index-name>'
    Created index '<search-index-name>'

[6] Indexing chunks with 'text-embedding-3-large'…
    Embedding: [chunk-0] 'Manual for Joakim-robot with article number: 12345'
    Embedding: [chunk-1] 'How to: “Switch batteries”:'
    Embedding: [chunk-2] 'How to reset Joakim-robot'
    Embedding: [chunk-3] 'How to reset your iPhone to factory settings'
    Uploaded 4 docs – 4 succeeded
    Waiting 15 s for the indexer to settle…

[7] Resolving AI Search connection in AI Foundry project…
    Matched connection: name='<search-conn>' type='ConnectionType.AZURE_AI_SEARCH' target='https://<search-name>.search.windows.net/'

[8] Creating agent '<agent-name>'…
    Agent id: asst_xxx

[9] Creating conversation thread…
    Thread id: thread_xxx

[10] Sending: 'How to reset Robot-Joakim?'
    Running agent…
    Run status: RunStatus.COMPLETED

    Run steps:
      step type=RunStepType.MESSAGE_CREATION status=RunStepStatus.COMPLETED
      tool_call [azure_ai_search] id=call_xxx
        input : ?
        output: ?

[11] Agent answer:
----------------------------------------------------------------
To reset Robot-Joakim to factory settings, follow these steps:

1. Back up the brain by turning the head 90 degrees clockwise and tapping the back of the head.
2. Open the mouth and whisper the word "reset."
3. Tap the nose and left ear twice, then hold for 5 seconds.
4. The Joakim-robot will spin 360 degrees to indicate that the reset is complete【3:1†source】.

Sources:
  【3:1†source】  How to reset Joakim-robot  doc_1
----------------------------------------------------------------

Would you like to delete the agent and clean up the thread? (y/n): y

[12] Cleaning up…
    Deleted agent  : asst_fYb6b7DvY4P2DnatFexUzFAy
    Deleted thread : thread_MriEKAczi1lrmmPgL9HgEOqT
    
```

## 3) Multi-agent orchestrator
- File: [../agent_02_multiagent.py](../agent_02_multiagent.py)
- What it does: builds three agents plus a router: Router → Coding Agent (CodeInterpreter) or RAG Agent (AI Search / Robot-Joakim) → Presenter Agent (CodeInterpreter). Coding routes produce charts; RAG routes return structured JSON. Agents are loaded from the [../multi-agent](../multi-agent) modules via importlib.
- Run examples (from this folder):
    - `python agent_02_multiagent.py`
    - `python agent_02_multiagent.py --query "top 5 fruits by calorie"`
    - `python agent_02_multiagent.py --query "How to reset Robot-Joakim?"`
    - Add `--no-cleanup` to keep agents/threads; add `--new-agents` to force fresh ones.
- Output: presenter response prints to console; CodeInterpreter chart images (for CODING route) are saved under [../output](../output).


### Example output (anonymized resources)
If you run in a terminal:
`python agent_02_multiagent.py --query "top 5 fruits by calorie"`

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

