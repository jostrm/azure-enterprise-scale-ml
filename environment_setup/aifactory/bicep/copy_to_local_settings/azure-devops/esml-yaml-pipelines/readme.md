# Azure Devops orchestration (.yaml): Bicep
Edit the [Variables](./variables/variables.yaml) file, and import Build pipeline in Azure Devops.

## See [prerequisites](../../../../../../documentation/v2/10-19/12-prerequisites-setup.md)

[prerequisites](../../../../../documentation/v2/10-19/12-prerequisites-setup.md)

### Prerequisite setup tools:  on your laptop (for both option A) Azure Devops and B) Github):
- **Git Bash**: https://git-scm.com/downloads e.g. GNU bash, version 5.2.37 or above
    - **Purpose:** The install script runs in bash terminal (Git bash)
    - **Note Mac/Linux**: It has been seen that Ubuntu bash (sames that comes with Mac OS), additional libraries will be needed to be installed
    - **Version:** 5.2.37
    ```bash
    bash --version
    ```` 

### Prerequisite: GIT enable long paths

```
git config --system core.longpaths true
```

## START

1) Add or Update the submodule to your repo (to get the bootstrap files)

    ADD, if you are the first developer to checkin the code. Run from your repo root location:
    ```
    git submodule add https://github.com/jostrm/azure-enterprise-scale-ml
    ```
    UPDATE, if you are not the 1st developer to checkin the code to your repo, e.g. if you cloned the repo.
    ```bash
    git submodule update --init --recursive --remote
    ```

    Then in both caess, choose A or B, where we recommend Option A
    
    **Option A)** To get `stable version` (recommended), set at specific `RELEASE branch`: 
    ```
    git submodule foreach 'git checkout "release/v1.20" && git pull origin "release/v1.20"'
    ```

    **Option B)**
    To get latest features/fixes, unstable, set at `MAIN branch`: 
    ``` 
    git submodule foreach 'git checkout main && git pull origin main'
    ```

    This will add a folder in your repo at root (a GIT submodule) called `azure-enterprise-scale-ml` that contains accelerator code (boostrap scripts, templates)

2) Run the start script `./azure-enterprise-scale-ml/00-start.sh`,  this will create some bootstrap-scripts at your repo root.

    ```
   bash ./azure-enterprise-scale-ml/00-start.sh
    ```
3) Run the file created at your root called: `01-aif-copy-aifactory-templates.sh`, this will create a folder at your root called `aifactory-templates` with templates for Azure Devops Build pipelines, variables and a `parameter`folder.
    ```
   bash ./01-aif-copy-aifactory-templates.sh
    ```
4) Rename the newly created folder  `aifactory-templates` to  `aifactory` (protects you to overwrite your configuration if running the script again)
    - Note: Is is under the `aifactory` folder, you will configure your [base parameters](../../../../aifactory/parameters/) and other variables.

>[!TIP]
> If you want to update the pipeline templates? Witout overwriting previous configuration. Then run the bash file created at your root called: `03-ADO-YAML-bootstrap-files-no-var-overwrite.sh`. This will ensure updated pipeline templates, and will not overwrite base parameters, or variables

The file structure should now look something like below. The underlined folder is the AI Factory `submodule`.

![](../../../../../../documentation/v2/20-29/images/24-end-2-end-setup-repo-ADO-byorepo.png)

## Steps 5-8

>[!NOTE]
> If you want to learn how to configure the AI Factory in `standalone mode` versus `Hub-connected centralized private DNS zones` with `BYOVnet`- [ setup starting page](../../../../../../documentation/v2/20-29/24-end-2-end-setup.md)
>

5) Configure the 12 [base parameters](../../../../aifactory/parameters/) 
6) Configure the [variables.yaml](./variables/variables.yaml), that will overwrite some of the base parameters.
7) Run pipeline: AIFactory Common
- Start with setting up a common AIFactory environment, example, the DEV environment. Go to Pipelines Import the .yaml file
    - [infra-aifactory-common.yaml](./esml-infra-common/infra-aifactory-common.yaml)

8) Run pipeline for an AIFactory project: 
- Then you can import and run the pipelines to setup 1-M projects. There are 2 AIFactory project types supported as of now: 
    - [infra-project-genai.yaml](./esml-infra-project/infra-project-genai.yaml)
    - [infra-project-esml.yaml](./esml-infra-project/infra-project-esml.yaml)

> [!TIP]
>  Do you want to use Github instead of Azure Devops? Then you can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage).
>