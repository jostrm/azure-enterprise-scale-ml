[Docs](../README.md) › Reference

# Settings

This page lists the settings you meet in the quickstarts: how a tool connects to the Factory API, and the
naming limits that apply to every Factory.

## Connection settings

Set the connection once. Every call then names only what it changes.

| Setting | Required | What it does |
|---|---|---|
| `ESAF_FOLDER` | Yes | Points to the absolute path of your `azurefactory` folder, on the machine that runs the API. |
| `AIFACTORY_API_KEY` | Yes | Carries the API key you entered in the app. Never put it in a script, a URL or a log. |
| `AIFACTORY_API_URL` | No | Sets the API address. The default is `http://127.0.0.1:8765`. |
| `ESAF_TIMEOUT` | No | Sets how many seconds one request may take. The default is `1800`. |

```powershell
$env:AIFACTORY_API_URL = 'http://127.0.0.1:8765'
$env:AIFACTORY_API_KEY = Read-Host 'API key you entered in the app'
$env:ESAF_FOLDER = (Resolve-Path .\azurefactory).Path
```

In Python, you can connect in code instead:

```python
from azurefactory import esaf

esaf.connect(folder=r"C:\work\team-factory\azurefactory", url="http://127.0.0.1:8765", factory="acme-ai")
```

| `connect()` parameter | What it does |
|---|---|
| `folder` | Points to the `azurefactory` folder. The default is `ESAF_FOLDER`. |
| `url` | Sets the API address. The default is `AIFACTORY_API_URL`. |
| `api_key` | Carries the API key. The default is `AIFACTORY_API_KEY`. |
| `factory` | Selects a Factory by key or ID. You need it only when the folder holds more than one. |

Over REST, send the key in the `X-API-Key` header. The API accepts plain HTTP on your own machine only.

## Naming limits

Azure limits a deployment name to 64 characters, and ESAF builds names from your prefixes.

| Rule | Why |
|---|---|
| Keep the Factory prefix and the project prefix to six characters or fewer. | Longer prefixes can push a deployment name over the limit. |
| Use three digits for a project number and a scale-set suffix, as a string: `"002"`. | The tools reject other forms. |
| Use `dev`, `stage` or `prod` for the environment, in lower case. | The same number can exist in several environments. |

The app checks prefix lengths and warns you before a name is cut.

## Project metadata and secret names

| Setting | What it does |
|---|---|
| `org-department-id`, `org-department-name` | Label a project with its department. They provision nothing. |
| `inputCommonSPSecretKey`, `project_service_principal_Secret_seeding_kv_name` | Name a Key Vault secret. They hold the secret's name, never its value. |

Supply a secret name only when your sign-in method needs one. Saving the name doesn't create the secret.

## Project settings

Each project's settings live in its `variables.json`. Change them with scenario 3:

```python
from azurefactory import esaf

esaf.upsert_project("002", "dev", settings={"tag_costcenter": "lab"})
```

See [Quickstart: Add a project for your team](../quickstarts/03-add-project.md) and, for the Agent Chat
switches, [Quickstart: Create your first agent by enabling ESAF Agent Chat](../quickstarts/04-first-agent-chat.md).

**Next:** [The six scenarios](scenarios.md)

Related: [Folder structure](folder-structure.md) · [Hub and network modes](../concepts/hub-and-network-modes.md)
