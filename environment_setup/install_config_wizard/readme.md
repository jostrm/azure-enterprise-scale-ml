# AI Factory Configuration Wizard

The **AI Factory Configuration Wizard** is a guided, form-based desktop tool that simplifies the initial setup of an Enterprise Scale AI Factory. Instead of manually editing configuration files, the wizard walks you through every required parameter, validates your inputs in real time, and generates a correctly populated `.env.template` (GitHub Actions) or `variables.yaml` (Azure DevOps) file — ready to be used directly in your CI/CD pipeline.

![AI Factory Configuration Wizard](images/aifactory-config-wizard-01.png)

## Why use the Wizard?

- **Reduces misconfiguration risk** — mandatory fields are marked and validated before the file is generated
- **Speeds up first-time setup** — no need to read through a large configuration file to find what to change
- **ITSM-friendly** — core teams can generate the correct configuration directly from a service ticket and trigger the pipeline on behalf of the requesting team. Or get the "initial full configuration", where the ITSM tickets only contain the *project specifics* such as *which resources a team wants to order* e.g. have enabled=true (checkboxes in Wizard)

## Download - Version `0.44`

Stable Version 2026-06-30 is version `0.44`

| Platform | File |
|---|---|
| Windows | [aifactory-config-windows.zip](windows/aifactory-config-windows.zip) |
| Linux | [aifactory-config-linux.tar.gz](linux/aifactory-config-linux.tar.gz) |
| macOS | [aifactory-config-macos.tar.gz](macos/aifactory-config-macos.tar.gz) |

### ⚠️ Security warning on first run

The app is not yet signed with a commercial certificate. Your OS may show a warning the first time you run it — this is expected. The source code is fully open and auditable in this repository.

**Windows — "Windows protected your PC" (SmartScreen)**
1. Click **More info**
2. Click **Run anyway**

**macOS — "cannot be opened because it is from an unidentified developer"**
1. Right-click (or Control-click) the app
2. Select **Open**
3. Click **Open** in the dialog

**Linux** — no warning expected; you may need to make the file executable:
```bash
chmod +x aifactory-config
./aifactory-config
```
## Documentation

[Quickstart Documentation](https://jostrm.github.io/azure-enterprise-scale-ml/)
- Full parameter reference: [https://jostrm.github.io/azure-enterprise-scale-ml/parameters/](https://jostrm.github.io/)
- Recommended for all that wants to setup an AI Factory: Core team or project team.

[Full Documentation](../../documentation/readme.md) 
- All AI Factory concepts ( not full parameter reference)
- Recommended only for advanced core team.

# Prerequisites — AIFactory Config Wizard

The wizard is distributed as a **self-contained executable** built with PyInstaller.  
In most cases you do **not** need Python installed — just download, extract, and run.

---

## Windows

| Requirement | Details |
|-------------|---------|
| **OS** | Windows 10 (1903+) or Windows 11 |
| **Architecture** | x86-64 (64-bit). ARM devices running Windows 11 also work via x64 emulation. |
| **Visual C++ Runtime** | Usually pre-installed. If the app fails to start, install [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe). |
| **Python** | **Not required.** Python is bundled inside the `.exe`. |

### Run
1. Download [`aifactory-config-windows (3).zip`](windows/aifactory-config-windows%20%283%29.zip).
2. Extract the archive (right-click → *Extract All…*).
3. Double-click **`aifactory-config.exe`**.

> **Windows SmartScreen warning?**  The first run may show a "Windows protected your PC" prompt because the binary is unsigned. Click *More info* → *Run anyway*.

---

## macOS

| Requirement | Details |
|-------------|---------|
| **OS** | macOS 12 Monterey or later recommended (macOS 11 Big Sur minimum). |
| **Architecture** | Apple Silicon (arm64) and Intel (x86-64). The binary is built for the architecture of the GitHub Actions runner (currently Apple Silicon — `macos-latest`). |
| **Python** | **Not required.** Python is bundled inside the binary. |
| **Tkinter** | Bundled via PyInstaller. No separate install needed. |

### Run
```bash
# 1. Extract
tar -xzf macos/aifactory-config-macos.tar.gz

# 2. Allow execution
chmod +x aifactory-config

# 3. Launch
./aifactory-config
```

> **Gatekeeper warning?**  macOS may block the binary because it is not notarized.  
> Run once from Terminal:  
> ```bash
> xattr -d com.apple.quarantine ./aifactory-config
> ```  
> Then launch normally.

---

## Linux

| Requirement | Details |
|-------------|---------|
| **OS** | Any modern x86-64 Linux distribution (Ubuntu 22.04 LTS or later recommended). |
| **Architecture** | x86-64 (64-bit). |
| **Python** | **Not required.** Python is bundled inside the binary. |
| **Tkinter / Tcl/Tk system libs** | The runtime Tk shared libraries must be present on the host. Install with: |

```bash
# Debian / Ubuntu
sudo apt-get install -y python3-tk

# Fedora / RHEL / CentOS
sudo dnf install -y python3-tkinter

# Arch Linux
sudo pacman -S tk
```

### Run
```bash
# 1. Extract
tar -xzf linux/aifactory-config-linux.tar.gz

# 2. Allow execution
chmod +x aifactory-config

# 3. Launch (requires a desktop environment / display)
./aifactory-config
```

> Running on a headless server without a display? Set `DISPLAY` or use a virtual framebuffer (`Xvfb`), though the wizard is designed for interactive desktop use.

---

# HOW TO

These guides assume the following starting point:

- **Role**: Developer who has cloned the repository and activated the `azure-enterprise-scale-ml` submodule, per the [Update AI Factory](../../documentation/v2/20-29/26-update-AIFactory.md) instructions.
- **Software installed on your laptop**:
  - Bash terminal
  - Azure CLI
  - GitHub CLI
  - Python
- **Prerequisites**: see [Prerequisites — AIFactory Config Wizard](#prerequisites--aifactory-config-wizard) above.

---

## HOW TO: Set it up the first time (import settings)

This is for the **first person** in your team to configure the AI Factory. You import a ready-made `.env` file so you don't have to set ~100 parameters by hand.

**1) Download the wizard and run it**

- Download for your platform from the [Download](#download) table and run it.
- Your OS may warn you the first time you run an unsigned app — this is expected. See [Security warning on first run](#-security-warning-on-first-run) for how to allow it on Windows / macOS / Linux.

**2) Import settings (page 2 of the wizard)**

On the **2nd page** of the Configuration Wizard, you can **Import** settings from an `.env` file. This avoids manually setting the many enterprise-wide parameters that only need to be set once.

- Click **IMPORT** and select your `.env` file to load the settings.
- If the settings are already present, someone else has already done this step — you can skip to [HOW TO: Add a project](#how-to-add-a-project-2ndnth-person).

**3) Save the state and the `.env`**

- **Save State** — saves all AI Factory projects and scalesets locally and under the wizard's metadata folder in Git (so the whole team can fetch the correct state).
- **Save `.env`** (or **Save Variables.yaml** for Azure DevOps) — overwrites the actual file at the repository root that the pipeline uses as its basis.

**4) Apply the configuration (back in VS Code)**

You will see the edited `.env` file at the repository **root**. This file is used to update the GitHub Actions variables/secrets in GitHub. Run the bootstrap script at the root that starts with `10-`:

```bash
bash 10-GH-create-or-update-github-variables.sh
```

> For Azure DevOps, use the generated `variables.yaml` instead of the `.env` file.

---

## HOW TO: Add a project (2nd/Nth person)

Use this when the first-time setup has already been done by someone else (settings already imported), and you want to add a new project.

**1) Download the wizard and run it** (see [Download](#download)).

**2) Create a NEW project**

The easiest way is to clone an existing project:

1. Go to **page 9**, where you see the current project number (for example `003`).
2. Change the project number from `003` to `004`.
3. **Save State** and **Save `.env`**.

Done — you now have an identical project `004`, copied from project `003`. You can then edit project `004` to enable/disable whichever services it should have, if different from `003`.

- **Save State** saves the projects and scalesets locally and under the wizard's metadata folder in Git.
- **Save `.env`** (or **Save Variables.yaml** for Azure DevOps) overwrites the actual file used as the basis for your pipeline execution.

**3) Apply the configuration (back in VS Code)**

```bash
bash 10-GH-create-or-update-github-variables.sh
```

### Where is the project state stored? (two options)

The wizard always keeps state **locally** and in **Git**. You can choose how to organize that state in Git:

**Option 1 — One main branch (recommended for teams)**

- All AI Factory projects are saved as metadata (with their states) and checked into your Git repository on a single main branch.
- Every user fetches the correct, shared state from that branch.
- Best when the core team or a single source of truth manages all project settings centrally.

**Option 2 — One branch per project setting**

- In addition to the local and Git wizard state, you can create a **branch per project setting** that you manage on your own.
- Useful when individual teams or owners want to manage and review their own project's settings in isolation (for example via pull requests) before merging.

---

## HOW TO: Add a Scaleset

A scaleset (compute scale set) is managed as part of the wizard state, alongside projects.

**1) Download the wizard and run it** (see [Download](#download)).

**2) Add the scaleset in the wizard**

- Open the scaleset configuration in the wizard and add/edit the scaleset for the relevant project.
- **Save State** — saves the projects **and** scalesets locally and under the wizard's metadata folder in Git.
- **Save `.env`** (or **Save Variables.yaml** for Azure DevOps) — overwrites the actual file used as the basis for your pipeline execution.

**3) Apply the configuration (back in VS Code)**

```bash
bash 10-GH-create-or-update-github-variables.sh
```

> **TODO** — detailed scaleset wizard screenshots and field-by-field guidance to be added.

---


