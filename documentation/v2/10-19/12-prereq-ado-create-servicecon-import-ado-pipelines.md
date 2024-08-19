# Azure Devops: Create service connection + Import IaC pipelines + Set service connection to pipeline steps
- **Purpose:** Since only an Azure Devops admin have permission to create service connection and select that on a pipeline. 
    - E.g. the `AIFactory setup mentor` will not have permission with role: Stakeholder
- **Role needed:**: Azure Devops admin
- **Mandatory:** Yes
- **TODO**:
    - 1) Azure Devops: Create a service connection, based on the service principal  `esml-common-bicep-sp` [created in the Prerequsite, step 5](./12-prerequisites-setup.md#step-5-create-3-service-principals-and-store-infoappid-objectid-secret-in-the-seeding-keyvault-see-step-3)
        - [How-to](https://learn.microsoft.com/en-us/azure/devops/pipelines/library/service-endpoints?view=azure-devops&tabs=yaml#create-a-service-connection): create a service connection
    - 2) Import Azure Devops pipelines, [from the templates of the AIFactory](../../../), and set the service connection to each step in the pipeline
        - Step 1) Download templates from this ESML AIFactory GITHUB repo to your computer. There are 4 templates to download
            - Option A) Azure Devops (classic) - 5 templates: 
                - [esml-infra-common.json](../../../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/esml-ado-pipelines/esml-infra-common-bicep.json)
                - [esml-infra-project.json](../../../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/esml-ado-pipelines/esml-infra-project-bicep-adv.json)
                - [esml-infra-project.json](../../../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/esml-ado-pipelines/esml-infra-project-bicep-adv.json)
                - [esml-add-coreteam-member.json](../../../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/esml-ado-pipelines/esml-add-coreteam-member.json)
                - [esml-add-project-member.json](../../../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/copy_to_local_settings/esml-ado-pipelines/esml-add-project-member.json)
            - Option B) Github Actions
                - TODO: soafara
        - Step 2) Import pipelines (all 5, but do it one by one)
            - Option A) Azure Devops
                - 2A) Create a dummy RELEASE pipeline. [How-to](https://learn.microsoft.com/en-us/azure/devops/pipelines/release/define-multistage-release-process?view=azure-devops): create clasic RELEASE pipeline
                    - Purpose: The IMPORT button will not show otherwise in the UI
                - 2B) Import pipeline 
                    - [See IMAGE](#image---how-to-import-pipeline)
                    - Browse for the files: Select one the the pipeline files to import, such as the `esml-infra-common.json`
            - Option B) Github Actions
                - TODO: soafara
        - Step 3) Select the service connection for each step in pipeline, and SAVE
            - 3A) Click the EDIT button, on the release pipeline
            - 3B) Click TASKS  [See IMAGE 2B](#image---2b---import-pipeline) - we need to fix the red markings.
            - 3C) Click Agent job [See IMAGE 2C](#image---2c---select-agent), and select Azure Pipelines, and windows-2019
            - 3D) Click the first step in the pipeline. This would be an Azure CLI type step called `11-Common RG and RBAC`, if you selected the `esml-infra-common.json`
            - 3E) Select the Azure Resource Manager Connection (ARM Connection) you created earlier [See IMAGE](#image---2d---select-arm-connection-on-a-step)
            - **Repeat this for all the steps in the pipeline**
        - **Repeat step 2-3** for all .json files from step 1

### IMAGE - 2A - IMPORT PIPELINE

![](./images/12-prerequisites-ado-import-release-pipeline.png)

### IMAGE - 2B - IMPORT PIPELINE

![](./images/12-prerequisites-ado-import-tasks.png)

### IMAGE - 2C - Select Agent

![](./images/12-prerequisites-ado-import-tasks.png)

![](./images/12-prerequisites-ado-agent-win2019.png)