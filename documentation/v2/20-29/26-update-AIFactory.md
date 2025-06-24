# Update existing AI Factory
There are two types of updates you can do: `Library-UPDATE` or `Feature-UPDATE`. 

## Prerequisites: An existing AI Factory
[Prerequisites - End-2-end setup](./24-end-2-end-setup.md)


# 1) Library-UPDATE: (UPDATED feature / BUG fixes)
When a feature is updated, or bug-fixes occur, e.g. if pipelines is untouched, and variables.yaml (.env) is untouched. 

You may use `VS Code` on the GIT tab, and just "Pull" the submodule `azure-enterprise-scale-ml`, or just run the below from your repo root location. Open a new terminal `Git Bash` or similar: 

```
git submodule update --init --recursive --remote
```

**Option A)** To get `stable version` (recommended), set at specific `RELEASE branch`: 
```
git submodule foreach 'git checkout "release/v1.20" && git pull origin "release/v1.20"'
```

**Option B)**
To get latest features/fixes, unstable, set at `MAIN branch`: 
``` 
git submodule foreach 'git checkout main && git pull origin main'
```


**Finished!**

# 2) Feature-UPDATE: NEW feature: such as "BYOVnet"
When a new feature is added, which impacts the varables and pipeline. Features sucha as BYOVnet, Subnets, Personas. 
If such feature is added, the below "pipelines & variables", may need to be updated. 

<details>
  <summary><b>Azure Devops: How-To</b></summary>

The below files will be updated via `bash` scripts:
- `Pipeline templates (.yaml)` located `aifactory/esml-infa/azure-devops`
- `Variables.yaml` located `aifactory/esml-infa/azure-devops/variables`
- `parameter files (.json)` (sometimes / rare cases) located `aifactory/parameters`


##  A) Azure Devops: How-To

1) UPDATE the submodule to your repo (to get the updates)

    - You may use `VS Code` on the GIT tab, and just **Pull** the submodule `azure-enterprise-scale-ml`, or just run the below from your repo root location:

    ```bash
    git submodule update --init --recursive --remote
    ```
    ```
    git submodule foreach 'git checkout "release/v1.20" && git pull origin "release/v1.20"'
    ```

2) Run the START script - to ensure you have the latest bootstrap scripts. 
    - friendly, will never overwrite anything exist .sh files at root
    ```
    bash ./azure-enterprise-scale-ml/00-start.sh
    ```

3) Run the below - It will UPDATE Azure Devops pipeline templates, under `aifactory/esml-infa/azure-devops`
    - Friendly: 
        - It will NOT overwrite your `variables.yaml`. This will create a new variable file next to your `variables.yaml` called `variables-template.yaml`. 
        - It will NOT overwrite your `parameter` folder. 
    - WARNING! If you have [extended AIFactory orchestration pipelines](./27-extend-AIF-pipelines.md), you need to backup the folders under: `aifactory/esml-infa/*`

    ```
    bash ./03-ADO-YAML-bootstrap-files-no-var-overwrite.sh
    ```

4) Do a "file compare" (using VS code or similar) with  `variables.yaml` VS  `variables-template.yaml`
    - Compare the file, to see if any new variables have been added, that you need to set, then set them
    - Example below: 
    ```yaml
    # Networking: Bring your own subnets (BYO_subnets=true) - optional (leave empty string to disable).  Otherwise, leave it empty and the pipeline will create new subnets, based on the CIDR in 12-esml-cmn-parameters.json
    BYO_subnets: "false" # false, the default subnets created by the pipeline. Azure Devops pipeline, will automatically not run Networking step, if true
    network_env_dev: "" # Example: "dev-" Default is empty string. Set to empty if  BYO_subnets: "false"
    network_env_stage: "" # Example: "stage-"
    network_env_prod: "" # # Example: "prod-"
    ```

5) `Rare cases`: Added or updated base `parameter` files, or parameters inside of files
    - Friendly: It will NOT overwrie your `aifactory` folder. It will create a new folder at root called `aifactory-templates`
    - TODO: Check the `release-notes` to see which file need to be updated. Example: Lately most changes is in 
        - `10-esml-globals-override.json`
        - `31-esgenai-default.json`
        - You may also do a file compare on each file in `aifactory-template/parameters`, with your files `aifactory/parameters`, to see if any parameters are added or removed. 

    ```bash
    bash ./01-aif-copy-aifactory-templates.sh
    ```

**Finished!**

</details>

<details>
  <summary><b>Github Actions: How-To</b></summary>

The below files will be updated via `bash` scripts:
- Github Actions Workflows: located `aifactory/esml-infa/github-actions`
- `.env` located at your root
- `parameter files (.json)` (sometimes / rare cases) located `aifactory/parameters`


##  B) Github Actions: How-To

1) UPDATE the submodule to your repo (to get the updates) 
You may use VS Code and just "Pull" the submodule `azure-enterprise-scale-ml`, or just run the below from your repo root location:

    ```bash
    git submodule update --init --recursive --remote
    ```
    ```
    git submodule foreach 'git checkout "release/v1.20" && git pull origin "release/v1.20"'
    ```

2) Run the START script - to ensure you have the latest bootstrap scripts. 
    - friendly, will never overwrite anything exist .sh files at root
    
    ```bash
    bash ./azure-enterprise-scale-ml/00-start.sh
    ```

3) Run the below - It will UPDATE Azure Devops pipeline templates, under `aifactory/esml-infa/azure-devops`
    - Friendly: 
        - It will NOT overwrite your `.env`. This will create a new variable file next to your `.env` called `.env.template`
        - It will NOT overwrite your `parameter` folder. 
    - WARNING! If you have [extended AIFactory orchestration pipelines](./27-extend-AIF-pipelines.md), you need to backup the folders under: `aifactory/esml-infa/*`

    ```
    bash ./03-GH-bootstrap-files-no-env-overwrite.sh
    ```

4) Do a "file compare" (using VS code or similar) with  `.env` VS  `.env.template`
Compare the file, to see if any new environment variables have been added, that you need to set, then set them

Example below: 

```yaml
# Networking: Bring your own subnets (BYO_subnets=true) - optional (leave empty string to disable).  Otherwise, leave it empty and the pipeline will create new subnets, based on the CIDR in 12-esml-cmn-parameters.json
BYO_subnets: "false" # false, the default subnets created by the pipeline. Azure Devops pipeline, will automatically not run Networking step, if true
network_env_dev: "" # Example: "dev-" Default is empty string. Set to empty if  BYO_subnets: "false"
network_env_stage: "" # Example: "stage-"
network_env_prod: "" # # Example: "prod-"
```

5) `Rare cases`: Added or updated base `parameter` files, or parameters inside of files
    - Friendly: It will NOT overwrie your `aifactory` folder. It will create a new folder at root called `aifactory-templates`
    - TODO: Check the `release-notes` to see which file need to be updated. Example: Lately most changes is in 
        - `10-esml-globals-override.json`
        - `31-esgenai-default.json`
    - You may also do a file compare on each file in `aifactory-template/parameters`, with your files `aifactory/parameters`, to see if any parameters are added or removed. 

    ```bash
    bash ./01-aif-copy-aifactory-templates.sh
    ```

**Finished!**
</details>