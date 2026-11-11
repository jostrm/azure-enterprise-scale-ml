[Docs](../README.md) › [Setup docs](README.md)

# Quickstart: Install the ESAF tools

In this quickstart, you install one ESAF tool, start the Factory API and check that they connect. The
**Factory API** is the one service that every tool calls. It ships inside the app, so you don't install it
separately.

> [!TIP]
> **Run it guided.** The **ESAF Tutorials** app types each command for you and checks every step: it also
> starts its own Factory API. Open an **ESAF** tutorial and the track **Scenarios 1–3**.
> [Download ESAF Tutorials](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/install_tutorial_guide).
> It's a private preview: ask [Joakim Åström on LinkedIn](https://www.linkedin.com/in/joakimastrom/) for a
> preview code.

<a href="../10-19/10-factory-onion-architecture-v2.md">
<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="../10-19/images/10-factory-onion-architecture-v2.png">
  <img src="../10-19/images/10-factory-onion-architecture-v2.gif" width="560" loading="lazy" alt="Diagram that shows the app, CLI, Python SDK and REST as clients of the same Factory API.">
</picture>
</a>

Every tool is an L1 client of the same Factory API, so the result is the same whichever you pick. See the
[onion architecture](../10-19/10-factory-onion-architecture-v2.md).

## Prerequisites

- **Windows x64:** [Git for Windows](https://git-scm.com/downloads/win), which includes Git Bash. For the
  CLI (PowerShell) tab, also
  [PowerShell](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows) 7.3
  or later.
- **Linux or macOS:** Git and Bash. Use the CLI (bash), Python SDK or REST tab. The one-call scenarios need
  the app package v0.47.100 or later. Check the
  [download table](../../../environment_setup/install_config_wizard/readme.md#download): a Linux or macOS
  package older than that starts the API, but it doesn't have the one-call scenarios yet.
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) and
  [Python](https://www.python.org/downloads/) 3.10 or later.
- A Git repository for your Factory's configuration, in GitHub or Azure DevOps. This is your **consumer
  repository**.

## Start the Factory API

The Factory API ships inside the **AIFactory Config Wizard**, a desktop app for Windows, Linux and macOS.

1. Download the [AIFactory Config Wizard](../../../environment_setup/install_config_wizard/readme.md#download)
   for your system.
2. Extract the archive. On Windows, keep the `_internal` folder beside `aifactory-config.exe`.
3. Open the app. On Windows, that's `aifactory-config.exe`. For the other systems, see
   [macOS](../../../environment_setup/install_config_wizard/readme.md#macos) and
   [Linux](../../../environment_setup/install_config_wizard/readme.md#linux).
4. In the left menu, select **Quick setup**, then **Start API host**. Do this before you open any other
   window in the app, so that you choose the key.
5. In the **API Host Authentication** dialog, enter a private API key. You choose it; remember it for the
   next steps.
6. Copy the API address from the **API Host Started** dialog. The default is `http://127.0.0.1:8765`. The
   status bar shows it too.

Keep the app open. The API stops when you close it.

## Create your Factory folder

Your Factory's configuration lives in an `azurefactory` folder in your consumer repository.

1. Open Bash in the root of your consumer repository. On Windows, that's Git Bash.
2. Add this repository as a submodule and create the folder:

   ```bash
   git submodule add -b release/v1.25 https://github.com/jostrm/azure-enterprise-scale-ml
   bash ./azure-enterprise-scale-ml/01-start-v125-and-above.sh
   ```

Expected output, among other lines:

```text
Initialized empty register: C:\work\team-factory\azurefactory\register.json
```

The script creates `azurefactory\register.json` with no factories in it. It changes nothing in Azure. See
[folder structure](../reference/folder-structure.md).

## Connect your tool

Choose one tool. You can add the others later; they all use the same API address, key and folder.

<details markdown="1" data-factory-tool="App" open>
<summary>App</summary>

The App tabs use **Enterprise Scale AI Factory**, the ESAF desktop app for Windows 11. It starts its own
Factory API, so you can skip "Start the Factory API" above.

1. Install the app from its [download folder](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/install_config_wizard/maui).
   You need version 1.0.24 or later.
2. Open **Enterprise Scale AI Factory** from Start.
3. On **Start Guide**, under **Consumer repository root**, select **Browse repository** and pick your
   consumer repository.

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="CLI (PowerShell)">
<summary>CLI (PowerShell)</summary>

Open PowerShell in the root of your consumer repository:

```powershell
python -m pip install .\azure-enterprise-scale-ml\environment_setup\azurefactory-cli
$env:AIFACTORY_API_URL = 'http://127.0.0.1:8765'
$env:AIFACTORY_API_KEY = Read-Host 'API key you entered in the app'
$env:ESAF_FOLDER = (Resolve-Path .\azurefactory).Path
azurefactory health
```

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="CLI (bash)">
<summary>CLI (bash)</summary>

Open Bash in the root of your consumer repository:

```bash
python3 -m pip install ./azure-enterprise-scale-ml/environment_setup/azurefactory-cli
export AIFACTORY_API_URL='http://127.0.0.1:8765'
read -r -s -p 'API key you entered in the app: ' AIFACTORY_API_KEY && export AIFACTORY_API_KEY
export ESAF_FOLDER="$PWD/azurefactory"
azurefactory health
```

In Git Bash on Windows, the API needs a Windows path:
`export ESAF_FOLDER="$(cygpath -w "$PWD/azurefactory")"`.

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="Python SDK">
<summary>Python SDK</summary>

Install the SDK and set the connection once. This is PowerShell; on Linux or macOS, use the three `export`
lines from the CLI (bash) tab instead:

```powershell
python -m pip install .\azure-enterprise-scale-ml\environment_setup\azurefactory-cli
$env:AIFACTORY_API_KEY = Read-Host 'API key you entered in the app'
$env:ESAF_FOLDER = (Resolve-Path .\azurefactory).Path
```

Then save this as `check_connection.py` and run it:

```python
from azurefactory import esaf

session = esaf.connect()  # reads ESAF_FOLDER, AIFACTORY_API_URL and AIFACTORY_API_KEY
catalog = session.client.catalog_list(session.folder)
print([factory["key"] for factory in catalog["factories"]])
```

</details>
<!-- /factory-tool -->

<details markdown="1" data-factory-tool="REST (curl)">
<summary>REST (curl)</summary>

Open Bash (on Windows: Git Bash). Health needs no key:

```bash
curl --silent --show-error --fail-with-body http://127.0.0.1:8765/health
```

List the scenario routes that the API serves:

```bash
curl --silent --show-error http://127.0.0.1:8765/openapi.json \
  | grep -o '"/api/v1/esaf/[^"]*"' | sort -u
```

Every other request needs your key in the `X-API-Key` header.

</details>
<!-- /factory-tool -->

## Verify the result

Your tool reaches the API, and your folder holds no factory yet.

| Tool | Expected output |
|---|---|
| App | The status light at the bottom shows **API connected**. |
| CLI, in either shell | `azurefactory health` prints `"status": "ok"`. |
| Python SDK | The script prints `[]`. |
| REST | The second command lists seven routes that start with `/api/v1/esaf/`. |

For example, the CLI prints:

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

If something goes wrong:

| Message | Fix |
|---|---|
| `AIFACTORY_API_KEY is required`, or HTTP 401 | Set the key again. It must match the key you entered in the app. |
| `The Factory API has no /api/v1/esaf routes` | Your app package is older than v0.47.100. Download the current package. On Linux and macOS, check the download table for a package with that version. |
| `Select an absolute local factory folder without traversal.` | Set `ESAF_FOLDER` with `Resolve-Path`, as shown. |
| `ModuleNotFoundError: azurefactory` | Run the `pip install` line again with the same `python`. |

## Next step

**Next:** [Quickstart: Create your AI Factory](02-create-factory.md)

Related:

- [Settings](../reference/settings.md): the connection settings in one table.
- [The six scenarios](../reference/scenarios.md): what you can run now.
- [Guide 18](../10-19/18-cli-and-api-and-usage.md): try the tools against a local demo service first.
