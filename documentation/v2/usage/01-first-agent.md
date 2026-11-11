[Docs](../README.md) › [Usage docs](README.md)

# Quickstart: Run your first agent in your ESAF project

In this quickstart, you plan, deploy and ask your first agent in your ESAF project. You use a **prompt
agent**: Microsoft Foundry runs its model and its tools, so you have no server to build.

> [!TIP]
> This page gives you the short path. The template's own guide has every option:
> [Foundry prompt agents](../../../usecase_code/40-agent-factory/41-single-agent/prompt-agent/readme.md).

You deploy `aif-reviewer`. It reviews a draft that you give it, so it needs no data of its own.

## Prerequisites

- The [usage prerequisites](prerequisites.md): an ESAF project, access to it and Python 3.13.
- A Microsoft Foundry project with a chat model deployment in your ESAF project. Your platform team enables
  both.
- From your platform team: your target key, for example `project001-dev`, and the path of your project's
  variables file.

## Prepare your environment

1. Open PowerShell in your checkout of this repository.
2. Create the environment and install the tools:

   ```powershell
   Set-Location .\usecase_code\40-agent-factory
   py -3.13 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
   ```

3. Copy `config.example.json` to a folder of your own, for example `aifactory\agent-factory\config.json`.
4. In your copy, set the target key and the variables file path that your platform team gave you.
5. Point two variables at them:

   ```powershell
   $Config = 'C:\work\my-project\aifactory\agent-factory\config.json'
   $Target = 'project001-dev'
   ```

## Plan the agent offline

A plan reads only your configuration. It calls nothing in Azure.

```powershell
.\.venv\Scripts\python.exe -m agent_factory plan --config $Config --target $Target --agent aif-reviewer
```

To see every agent in the catalog first, save this as `inspect_agents.py` and run it with the same Python:

```python
import json
from agent_factory.catalog import agent_catalog

print(json.dumps([{"name": agent["name"], "kind": agent["kind"]} for agent in agent_catalog()], indent=2))
```

## Deploy and ask the agent

1. Sign in: `az login --tenant <your tenant ID>`. Connect your VPN if your project is private.
2. Check your access. This step only reads Azure:

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory preflight --config $Config --target $Target
   ```

3. Deploy the agent. This step changes your Foundry project:

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory deploy --config $Config --target $Target --agent aif-reviewer --apply
   ```

4. Ask it to review a draft. This call uses your model, so it can cost money:

   ```powershell
   .\.venv\Scripts\python.exe -m agent_factory invoke --config $Config --target $Target --agent aif-reviewer `
     --input "Review this draft: Everyone must reset passwords daily. No evidence was supplied."
   ```

## Verify the result

The plan reports that it changes nothing:

```json
{
  "mutations": false
}
```

The deploy step reports a version record with `created` or `unchanged`. The answer is JSON with `agent`,
`response_id` and `text`. In `text`, the reviewer points out that the draft has no supporting evidence.

| Symptom | Fix |
|---|---|
| The plan fails | Check the target key and the variables file path in your configuration. |
| Preflight can't reach Foundry | Connect your VPN, and check that you're in your project's Entra group. |
| The answer asks for a tool approval | You invoked another agent. `aif-reviewer` has no tools by default. |

## Clean up resources

The tools never delete an agent. To remove it, delete `aif-reviewer` in your Foundry project in the Foundry
portal. Then remove your local environment:

```powershell
Remove-Item -Recurse -Force .\.venv
```

## Next step

**Back:** [Usage prerequisites](prerequisites.md)

**Next:** [Quickstart: Train your first model in your ESAF project](02-first-ml-model.md)

Related:

- [Single agent](../../../usecase_code/40-agent-factory/41-single-agent/readme.md): the knowledge agent,
  which needs your data first.
- [Agent Factory](../../../usecase_code/40-agent-factory/readme.md): data ingestion, hosted agents and
  multi-agent teams.
- [Usage docs](README.md): every starting point.
