# Enterprise Scale AI Factory for Windows 11

A native .NET MAUI desktop app with its Python API included: configuration,
reviewed IaC execution, Azure monitoring, project operations and tickets.

## Install

1. Download the **`.msi` and all its `.cab` parts** from this folder into one folder
   (for example `ESAIF.ConfigWizard-<version>-win-x64.msi` with `...-1.cab`, `...-2.cab`, ...).
2. Double-click the `.msi`. It installs for your Windows account into
   `%LOCALAPPDATA%\Programs\ESAIF.ConfigWizard`; administrator rights are not normally required.
3. Open **Enterprise Scale AI Factory** from Start. The app starts its bundled local API automatically.

**All `.cab` parts and the `.msi` are required.** The parts hold the compressed application and its
included components; Windows Installer reads them from beside the `.msi`. They are split so that no file
reaches GitHub's 100 MiB limit. Keep the original file names, then run **only the `.msi`**.
`SHA256SUMS.txt` lists every file's hash; compare a download with `Get-FileHash .\filename -Algorithm SHA256`.

An earlier Inno Setup installation (`ESAIF.ConfigWizard_1`) is migrated by the local build script; with the
`.msi` alone, uninstall the older version first. User settings and browser profiles stay. Older installers
are kept in [previous-release](previous-release/).

**Unsigned preview:** Windows SmartScreen or your organization's application policy may warn or block
installation. Verify the download source and hashes. Follow your organization's approval process; do not
disable security controls. This is not a Microsoft Store or signed enterprise deployment package.

## Prerequisites

| Purpose | What you need |
| --- | --- |
| Open the app | Windows 11 **x64** (build 22000 or later) and [Microsoft Edge WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). WebView2 is normally already installed on Windows 11; the installer checks for both. |
| App/API runtimes | **Included:** .NET, Windows App SDK, Python, FastAPI and API dependencies. No Visual Studio, .NET SDK, MAUI workload or separate Python installation is needed just to use the desktop UI. |
| Run deployment scripts | [Git for Windows with Git Bash](https://git-scm.com/downloads/win), [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli-windows), and a **host Python 3.10+** available in Git Bash. |
| GitHub Actions projects | [GitHub CLI](https://cli.github.com/), plus access to the target repository and appropriate Azure permissions. |
| Azure DevOps projects | Access to the target Azure DevOps organization/project, configured pipelines and appropriate Azure permissions. |

Internet access is required for sign-in, Azure inventory, source-version checks and deployments. Installing
the app does **not** grant Azure or repository permissions. The
[deployment prerequisites](../../../documentation/v2/10-19/12-prerequisites-setup.md) still apply.

## First use

Follow the [end-to-end setup guide](../../../documentation/v2/20-29/24-end-2-end-setup.md). The
[configuration wizard page](../readme.md) describes the same Factory API in the Tkinter wizard.

## Updates and uninstall

Close the app and finish or explicitly resolve any active deployment before updating. Run the newer `.msi`
(with its parts) to update the same per-user installation. Uninstall through
**Settings > Apps > Installed apps > Enterprise Scale AI Factory**.

Your repositories, saved configurations and Azure resources are separate from the app installation.
Uninstall is not an Azure cleanup operation.
