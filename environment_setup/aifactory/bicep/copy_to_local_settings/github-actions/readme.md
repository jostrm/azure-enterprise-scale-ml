# Github orchestration (.yaml): Bicep

>[!NOTE]
> If you want to learn how to configure the AI Factory in `standalone mode` versus `Hub-connected centralized private DNS zones` with `BYOVnet`- [ setup starting page](../../../../../documentation/v2/20-29/24-end-2-end-setup.md)
>

## Note: see [prerequisites](../../../../../documentation/v2/10-19/12-prerequisites-setup.md)

### Prerequisite setup tools:  on your laptop (for both option A) Azure Devops and B) Github):
- **Git Bash**: https://git-scm.com/downloads e.g. GNU bash, version 5.2.37 or above
    - **Purpose**: The install script runs in bash terminal (Git bash)
    - **Note Mac/Linux**: It has been seen that Ubuntu bash (sames that comes with Mac OS), additional libraries will be needed to be installed
    - **Version**: 5.2.37
    ```bash
    bash --version
    ```` 
### Prerequisite setup tools: on your laptop (for Option B - Github)
- **Github CLI**: https://cli.github.com/
    - **Purpose**: The .env file will push those values as Github secretc and variables, and create Github environments Dev, Stage, Production
    - **Version**: 2.71.0 or above
    ```bash
        gh --version
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

    Then in both cases (ADD or UPDATE) choose A or B, where we recommend Option A:
    
    **Option A)** To get `stable version` (recommended), set at specific `RELEASE branch`: 
    ```
    git submodule foreach 'git checkout "release/v1.24" && git pull origin "release/v1.24"'
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
3) Run the file created at your root called: `01-aif-copy-aifactory-templates.sh`, this will create a folder at your root called `aifactory-templates` with templates for GHA workflows, and parameters.
    ```
   bash ./01-aif-copy-aifactory-templates.sh
    ```
4) Rename the newly created folder  `aifactory-templates` to  `aifactory` (protects you to overwrite your configuration if running the script again)
    - Note: Is is under the `aifactory` folder, you will configure your variables, and the possibility to leverage BYOBicep when editing the GH workflow templates.
5) Run the file created at your root called: `02-GH-bootstrap-files.sh`, this will creat an .env file at your root.
    - Note: If you want to refresh the pipeline templates, but not overwrite the .env file, you may run `03-GH-bootstrap-files-no-env-overwrite.sh`
     ```
   bash ./02-GH-bootstrap-files.sh
    ```

OUTPUT: The file structure should now look something like below (except parameters folder, that is deprecated, should not be visible): 

![](../../../../../documentation/v2/20-29/images/24-end-2-end-setup-repo-GH-byorepo.png)

## Continue with steps:6-10:

6) Authenticate to Github CLI, with a user that is Administrator (Can create Environemnts, variables, secrets, Github Action workflows)
   ```sh
    gh auth login
   ```
<!--
5) Authenticate to  Azure and Github
You need to login via `Azure CLI` and `Github CLI`, but recommendation is to also test login via `Powershell`. 
- NB! Recommendation is to use a service principal when logging in, such as `esml-commmon-bicep-sp`, see your ``. You may also use your user id (for Github this is the usual case).
- The Service Principal should have OWNER permission to all 3 subscriptions (Dev, Test, Prod), such as the `esml-common-bicep-sp` service principle.
- Test the login for all 3 subscriptions using `az cli` and `powershell` as below: 

   a) Log in to `Azure CLI with a service principal`, to a specific tenant

   ```sh
    # Define the variables
    clientId="your-client-id"
    clientSecret="your-client-secret"
    tenantId="your-tenant-id"
    subscriptionId="your-subscription-id"
    
    az login --service-principal -u $clientId -p $clientSecret --tenant $tenantId
    az account set --subscription $subscriptionId
   ```

-->

<!--7) Edit the [base parameters](../../../../aifactory/parameters/). All files 12 files such as [10-esml-globals-1.json](../../../../aifactory/parameters/10-esml-globals-1.json) -->
7) Edit the [.env] variables at your root.
    - Choose naming convention: prefix, suffixes
    - Choose which services to enable or disable
    - BYOVNet, BYOSubnet, BYOAce, enableAIGateway
    - etc
8) Run the file created at your root called: `10-GH-create-or-update-github-variables.sh`, that will copy values from .env to your Github repo as Environment variables, and secrets.
    - NB! The below will use Github CLI (gh), if the command does not work, plese see PREREQUISITES.
    ```
   bash ./10-GH-create-or-update-github-variables.sh
    ```

    - Select `y`in the prompt `Do you want to use overwrite AZURE_CREDENTIALS with dummy value?` the first time you run the script.
    - Then, set the AZURE_CREDENTIALS manually using Github web portal for each Environment. The format should be: 
        ```json
        {
            "clientId": "<AppId of service princple that is OWNER, such as esml-commonn-bicep-sp>",
            "clientSecret": "Secret of of service princple that is OWNER, such as esml-commonn-bicep-sp",
            "subscriptionId": "<subscriptionID>",
            "tenantId": "<TenantId>"
        }
        ```

    - OUTPUT: The environment in Github should now look something like below (~21 variables in each environment: Dev,Stage, Prod)
    - ![](../../../../../documentation/v2/20-29/images/24-end-2-end-setup-repo-GH-env-vars.png)

9) Run the Github action workflows for `infra-aifactory-common.yaml`
10) Set the variable in your .env file called `aifactory_salt`, and then run the script again, `10-GH-create-or-update-github-variables.sh`,  to update your GH variables. 

```code yaml
# Update with values from AI Factory COMMON Resource group.The aifactory_salt can be read from the AI Factory common resource group in names of services such as Azure Datafactory
# - Example: the 'a4c2b'in "adf-cmn-weu-dev-a4c2b-001" and in Container registry, private endpoints: "pend-kv-cmndev-a4c2b-001-to-vnt-esmlcmn"
# ...
# ...
```
Read more information in the comment section of variables.yaml

11) Run the workflow `infra-project.yml`

## Workflow: AIFactory Common 
Start with setting up a common AIFactory environment, example, the DEV environment
- [infra-aifactory-common.yaml](./esml-infra-common/infra-aifactory-common.yaml)

## Workflow: AIFactory projects
Then you can import and run the pipelines to setup 1-M projects. There are 2 AIFactory project types supported as of now: 
- [infra-project.yml](./infra-project.yml)


> [!TIP]
>  A quicker & easier way? You can use the AIFactory Github Template repository to get a bootstrappd repo quickly (as a mirror repo, or "bring your own repo"). [AIFactory Template Repo](https://github.com/jostrm/azure-enterprise-scale-ml-usage), ready to run. All files copied already. Just configure and run.
>