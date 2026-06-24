# Update existing AI Factory
There are two types of updates you can do: `Library-UPDATE` or `Feature-UPDATE`. 

## Prerequisites: An existing AI Factory
[Prerequisites - End-2-end setup](./24-end-2-end-setup.md)


# 1) Library-UPDATE: (UPDATED feature / BUG fixes)
When a feature is updated, or bug-fixes occur, e.g. if pipelines is untouched, and variables.yaml (.env) is untouched. 

You may use `VS Code` on the GIT tab, and just "Pull" the submodule `azure-enterprise-scale-ml`, or just run the below from your repo root location. Open a new terminal `Git Bash` or similar: 

```
git config --system core.longpaths true
```

```
git submodule update --init --recursive --remote
```

**Option A)** To get `stable version` (recommended), set at specific `RELEASE branch`: 
```
git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
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


##  A) Azure Devops: How-To

1) UPDATE the submodule to your repo (to get the updates)

    - You may use `VS Code` on the GIT tab, and just **Pull** the submodule `azure-enterprise-scale-ml`, or just run the below from your repo root location:

    ```bash
    git submodule update --init --recursive --remote
    ```
    ```
    git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
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

4) Do a "file compare" (using VS code or similar) or Github copilot. Compare your `variables.yaml` VS `variables-template.yaml`


**Github copilot prompt**

`Compare the variables.yaml under my folder aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml with the newer variables-template.yaml in same folder. Copy all values from variables.yaml into the new template variables-template.yaml. If some variables are similar but not excat, try to map these simce they may be renamed. There may possible be more variables in variables-template.yaml. After this then rename variables.yaml to variables.bak and variables-template.yaml to variables.yaml`

**Traditioanl compare tool**

    - Compare the file with a file comparing tool such as VS Code, or Git, to see if any new variables have been added, that you need to set, then set them. 

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
    git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
    ```

2) Run the START script - to ensure you have the latest bootstrap bash scripts at your root.
    - friendly, will never overwrite anything exist .sh files at root
    
    ```bash
    bash ./azure-enterprise-scale-ml/00-start.sh
    ```

3) Run BASH script - to copy files to your repo `aifactory/esml-infa/github-actions/bicep` from the submodule
    - friendly, will never overwrite anything exist .sh files at root
    
    ```bash
    bash 01-aif-copy-aifactory-templates.sh
    ```

4) Run BASH script, to UPDATE pipeline templates, under `.github\workflows` in your repo, from your repos  `aifactory/esml-infa/github-actions/bicep`
    - Friendly: 
        - It will NOT overwrite your `.env`. This will create a new variable file next to your `.env` called `.env.template`
        - It will NOT overwrite your `parameter` folder. 
    - WARNING! If you have [extended AIFactory orchestration pipelines](./27-extend-AIF-pipelines.md), you need to backup the folders under: `aifactory/esml-infa/*`

    ```
    bash ./03-GH-bootstrap-files-no-env-overwrite.sh
    ```

4) Do a "file compare" (using VS code or similar) or with Github Copilot with  `.env` VS  `.env.template`

**Github copilot prompt**

`Compare the .env file at root, with the newer .env.template. Copy all values from .env into the new template .env.template. If some variables are similar but not excat, try to map these simce they may be renamed. There may possible be more variables in .env.template. After this , then rename .env to .env.bak and env.template to .env`

**Traditioanl compare tool**

Compare the file, to see if any new environment variables have been added, that you need to set, then set them

**Finished!**
</details>