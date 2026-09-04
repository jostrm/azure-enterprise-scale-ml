# Update existing AI Factory
There are two types of updates you can do: `Library-UPDATE` or `Feature-UPDATE`.

For a `Feature-UPDATE`, you can use a **Quick Feature-update & run** script or follow the manual instructions in [2) Feature-UPDATE: NEW feature, such as "BYOVNet"](#2-feature-update-new-feature-such-as-byovnet).

## Quick Feature-update & run

After `00-start.sh` has copied the scripts to your repository root, use the script for your orchestrator:

```bash
# Azure DevOps
bash ./ADO-update-aifactory-and-run-project.sh

# GitHub Actions
bash ./GH-update-aifactory-and-run-project.sh
```

These scripts replace the manual feature-update steps below. They protect existing work, update the AI Factory submodule and templates, merge the existing configuration into the latest templates, commit and push the changes, start the project pipeline or workflow, and monitor the run until it finishes.

On the first Azure DevOps run, the ADO script prompts for your organization name or URL and project name, then saves them as Azure CLI defaults for future runs.

## Prerequisites: An existing AI Factory
[Prerequisites - End-to-end setup](./24-end-2-end-setup.md)


## 1) Library-UPDATE: Updated feature or bug fixes
Use this update type when a feature or bug fix does not change the pipelines or configuration files (`variables.yaml` or `.env`).

You can use the **Git** tab in VS Code to pull the `azure-enterprise-scale-ml` submodule, or run the following commands from your repository root in Git Bash or a similar terminal:

```
git config --system core.longpaths true
```

```
git submodule update --init --recursive --remote
```

**Option A)** To get a stable version (recommended), select a specific release branch:
```
git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
```

**Option B)**
To get the latest, potentially unstable features and fixes, select the `main` branch:
``` 
git submodule foreach 'git checkout main && git pull origin main'
```


**Finished!**

## 2) Feature-UPDATE: NEW feature, such as "BYOVNet"
Use this update type when a new feature changes variables or pipelines, such as BYOVNet, subnets, or personas.
For these features, the pipelines and variables may need to be updated.

<details>
  <summary><b>Azure DevOps: How-To</b></summary>

The following files will be updated by Bash scripts:
- Pipeline templates (`.yaml`) under `aifactory/esml-infra/azure-devops`
- `variables.yaml` under `aifactory/esml-infra/azure-devops/bicep/yaml/variables`


### A) Azure DevOps: How-To

1) Update the submodule in your repository.

    - Use the **Git** tab in VS Code to pull the `azure-enterprise-scale-ml` submodule, or run the following commands from your repository root:

    ```bash
    git submodule update --init --recursive --remote
    ```
    ```
    git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
    ```

2) Run the start script to copy the latest bootstrap scripts to your repository root.
    ```
    bash ./azure-enterprise-scale-ml/00-start.sh
    ```

3) Run the following script to update the Azure DevOps pipeline templates under `aifactory/esml-infra/azure-devops`.
    - It will not overwrite your `variables.yaml`. It creates `variables-template.yaml` next to it.
    - It will not overwrite your `parameters` folder.
    - **Warning:** If you have [extended AI Factory orchestration pipelines](./27-extend-AIF-pipelines.md), back up the folders under `aifactory/esml-infra/*`.

    ```
    bash ./03-ADO-YAML-bootstrap-files-no-var-overwrite.sh
    ```

4) Compare `variables.yaml` with `variables-template.yaml` using VS Code, GitHub Copilot, or another comparison tool.


**GitHub Copilot prompt**

`Compare aifactory/esml-infra/azure-devops/bicep/yaml/variables/variables.yaml with the newer variables-template.yaml in the same folder. Copy all values from variables.yaml into the new variables-template.yaml. If some variables are similar but not exact, try to map them since they may have been renamed. There may be additional variables in variables-template.yaml. Afterward, rename variables.yaml to variables.bak and variables-template.yaml to variables.yaml.`

**Traditional compare tool**

    - Compare the files using a tool such as VS Code or Git, then configure any newly added variables.

**Finished!**

</details>

<details>
  <summary><b>GitHub Actions: How-To</b></summary>

The following files will be updated by Bash scripts:
- GitHub Actions workflows under `aifactory/esml-infra/github-actions`
- `.env` in your repository root
- Parameter files (`.json`) under `aifactory/parameters`, when required


### B) GitHub Actions: How-To

1) Update the submodule in your repository.
Use VS Code to pull the `azure-enterprise-scale-ml` submodule, or run the following commands from your repository root:

    ```bash
    git submodule update --init --recursive --remote
    ```
    ```
    git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
    ```

2) Run the start script to copy the latest bootstrap scripts to your repository root.
    
    ```bash
    bash ./azure-enterprise-scale-ml/00-start.sh
    ```

3) Run the Bash script to copy files from the submodule to `aifactory/esml-infra/github-actions/bicep` in your repository.
    
    ```bash
    bash 01-aif-copy-aifactory-templates.sh
    ```

4) Run the Bash script to update the pipeline templates under `.github/workflows` from `aifactory/esml-infra/github-actions/bicep`.
    - It will not overwrite your `.env`. It creates `.env.template` next to it.
    - It will not overwrite your `parameters` folder.
    - **Warning:** If you have [extended AI Factory orchestration pipelines](./27-extend-AIF-pipelines.md), back up the folders under `aifactory/esml-infra/*`.

    ```
    bash ./03-GH-bootstrap-files-no-env-overwrite.sh
    ```

5) Compare `.env` with `.env.template` using VS Code, GitHub Copilot, or another comparison tool.

**GitHub Copilot prompt**

`Compare the .env file in the repository root with the newer .env.template. Copy all values from .env into the new .env.template. If some variables are similar but not exact, try to map them since they may have been renamed. There may be additional variables in .env.template. Afterward, rename .env to .env.bak and .env.template to .env.`

**Traditional compare tool**

Compare the files, then configure any newly added environment variables.

**Finished!**
</details>