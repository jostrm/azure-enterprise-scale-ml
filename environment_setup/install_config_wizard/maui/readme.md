# AI Factory Configuration Wizard for Windows 11

A native .NET MAUI desktop app with the Python API from the Tkinter wizard included.

## Install

1. Download **all four files** below and keep them together in one local folder. These are direct download links.
2. Double-click the setup EXE and follow the short wizard. It installs for your Windows account; administrator rights are not normally required.
3. Open **Enterprise Scale AI Factory** from Start. The app starts its bundled local API automatically.

| Download | Size |
| --- | --- |
| [Setup EXE](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup.exe) | 2.3 MB |
| [Data part 1](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup-1.bin) | 93.7 MB |
| [Data part 2](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup-2.bin) | 96.0 MB |
| [Data part 3](https://raw.githubusercontent.com/jostrm/azure-enterprise-scale-ml/main/environment_setup/install_config_wizard/maui/ESAIF.ConfigWizard-1.0.0-win-x64-setup-3.bin) | 33.3 MB |

The `.bin` files are parts of the same installer, split to stay below GitHub's file-size limit. Do not run them separately. [SHA256SUMS.txt](SHA256SUMS.txt) lists the expected hashes; compare a download with `Get-FileHash .\filename -Algorithm SHA256`.

**Unsigned preview:** Windows SmartScreen or your organization's application policy may warn or block installation. Verify the download source and hashes. Follow your organization's approval process; do not disable security controls. This is not a Microsoft Store or signed enterprise deployment package.

Installation, bundled API/schema/templates, Python/Tcl/Tk files and uninstall were exercised on Windows 11 x64 build 26100. The current desktop preview also ran with .NET and Windows App SDK loaded locally. This is not a clean-VM certification of every Windows 11 build or managed-device policy.

## Prerequisites

| Purpose | What you need |
| --- | --- |
| Open the app | Windows 11 **x64** (build 22000 or later) and [Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). WebView2 is normally already installed on Windows 11; setup checks for it. |
| App/API runtimes | **Included:** .NET, Windows App SDK, Python, Tcl/Tk, FastAPI and API dependencies. No Visual Studio, .NET SDK, MAUI workload or separate Python installation is needed just to use the desktop UI. |
| Run deployment scripts | [Git for Windows with Git Bash](https://git-scm.com/downloads/win), [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli-windows), and a **host Python 3.10+** available in Git Bash. The embedded API interpreter does not replace the standalone Python command required by the Bash launchers. |
| GitHub Actions projects | [GitHub CLI](https://cli.github.com/), plus access to the target repository and appropriate Azure permissions. |
| Azure DevOps projects | Access to the target Azure DevOps organization/project, configured pipelines and appropriate Azure permissions. |

Internet access is required for sign-in, Azure inventory, source-version checks and deployments. Installing the app does **not** grant Azure or repository permissions. The [deployment prerequisites](../../../documentation/v2/10-19/12-prerequisites-setup.md) still apply.

## First use

- Choose **Configuration wizard** to open or create your configuration; point it at your consumer repository's `aifactory` folder, not this accelerator source repository.
- Use **Connection** if you need to inspect the API connection or intentionally connect to a separately hosted API.
- On **AI Factory**, **Plan to Stage** saves a Stage card with **Status: Not deployed**. Planning does not deploy resources.
- Use **Deploy** for a planned environment and **Update** for an observed deployment. Both open an explicit review before a script starts. **Patch** unchecked passes `--project-only`; checked refreshes the shared templates as well.
- The launcher is in the parent of `aifactory`: `ADO-update-aifactory-and-run-project.sh` or `GHA-update-aifactory-and-run-project.sh`. Keep your consumer launchers and templates current.
- The main menu retains the current page's project-style gradient highlight. **Manage factories** handles the newer factory catalog; legacy views can redirect there when a catalog root is selected.

## Updates and uninstall

Close the app and finish or explicitly resolve any active deployment before updating. Run the newer installer to update the same per-user installation. Uninstall through **Settings > Apps > Installed apps > Enterprise Scale AI Factory**.

Your repositories, saved configurations and Azure resources are separate from the app installation. Uninstall is not an Azure cleanup operation.

## Build from the checked-in source

The [`source`](source) folder contains the MAUI app, its BaseLayer/DomainLayer projects, the Python API, assets and tests. `source-manifest.json` records source file SHA-256 hashes. Local developer outputs, sign-in state and saved projects are not shipped.

Build prerequisites: .NET 10 SDK with the Windows MAUI workload/Windows SDK, a Windows x64 Python installation including Tcl/Tk, Git for Windows, and PowerShell 7. The build restores application dependencies and obtains a pinned, signature-checked Inno Setup compiler when one is not supplied.

From this directory:

```powershell
.\prepare-accelerator.ps1
python -m venv .\source\python-api\.venv
.\source\python-api\.venv\Scripts\python.exe -m pip install -r .\source\python-api\requirements.txt
.\source\ESAIF.ConfigWizard\build-windows.ps1 `
  -ApiSource "$PWD\source\python-api" `
  -Python "$PWD\source\python-api\.venv\Scripts\python.exe" `
  -AcceleratorSource "$PWD\artifacts\accelerator-source" `
  -SkipApiRestore
```

Outputs are under `source\ESAIF.ConfigWizard\artifacts\installer`. The accelerator preparation script pins the published source revision and supplies the clean Git objects required for version/readiness checks. It excludes installer files from the runtime working tree, avoiding recursive bundling. Updating that pinned revision is an explicit build decision.

For maintainers importing changes from the separate development directories, `export-source.ps1 -SourceReposRoot <parent-of-ESAIF-projects> -ApiSource <python-api-repo> -Destination <new-empty-folder>` creates a new source snapshot without overwriting an existing one.

## Screenshots

![AI Factory overview](../images/maui-aifactories-1.png)
![AI Factory configuration and model SKU](../images/maui-config-sku.png)
