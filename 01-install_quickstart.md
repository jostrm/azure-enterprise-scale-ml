## Tip: Use the Azure Data science Virtual Machine, to install the ESML SDK on, "jump host & client - all at once" 
- You have an easy way of "governance" for onboarding consultants easy - all is preinstalled (comes with ESML bicep)
  - You can have AAD login (Virtual Machine Administrator Login or Virtual Machine User Login)
  - VM inside of vNet already (no point-2-site gateway setup needed, no personal laptops to join to AAD)
  - Bastion host avaialble in the `ESML bicep provisioining`, including native RDP.
# 1) Install ESML Python SDK that includes Azure ML with AutoML
- Install MiniConda (>v 4.7), and open the MiniConda command prompt on your computer
  - Windows computer:  [environment_setup/user_dev_env_install/automl_setup.cmd](./environment_setup/user_dev_env_install/automl_setup.cmd)
  - Mac computer:  [environment_setup/user_dev_env_install/automl_setup_mac.sh](./environment_setup/user_dev_env_install/automl_setup.cmd)

# 2 (Alt A) NEW Azure Devops project - "link" ESML (GIT subclassing)

-  Add ESML as a GIT Submodule "linked" to your GIT repo
- Creat a "project001" folder on local machine, open GIT command prompt there, then run:
> git config --system core.longpaths true

> git submodule add https://github.com/jostrm/azure-enterprise-scale-ml

- Use the PIPELINE mlops-templates, to quickly get your project working as the ESML template project
Located here:  [./esml/azure_provisioning/azure_devops_pipelines/](./esml/azure_provisioning/azure_devops_pipelines/)
# 2 (Alt B) EXISTING Azure Devops project - Import the Azure Devops project (template project)
- Project already hashas the `ESML as submodule`, and MLops template ready to run, but you need to run the following command to see the files (not just an empty folder)
- Open GIT command prompt, go to your `local root folder for the code` (you should see the folder `azure-enterprise-scale-ml` and `notebook_demos` with a `dir` in the GIT CMD)run below: 

> git submodule update --init --recursive

If you get ann errormessage about `too long paths` then you need to open the GIT CMD prompt as `Administrator` and run the below (then try again)
> git config --system core.longpaths true

# 3) Create the Azure Resources needed (ESML Bicep)
The button below will deploy Azure Machine Learning and its related resources, BUT you may want to tailor to YOUR `naming convention` 
- **Q: How to edit the DEFAULT naming convention, to adher `to our enterprise policy naming convention`?**
- A: You can tailor your own Bicep version. Use the ESML tool, and config-file `../settings/enterprise_specific/naming_convention.json`.
    - The `ESML naming convention template` is good to get a baseline start - then edit the .json file for YOUR convention.
  
HOWTO: 
 - 1) Go here to EDIT the suggested naming convention to fit YOUR company specific convention, a config file:
    - [../settings/enterprise_specific/naming_convention.json](../settings/enterprise_specific/naming_convention.json)
 - 2) View the result of your edits, and all resources, per environment (DEV, TEST, PROD), you need to create:
    - [./esml/azure_provisioning/01-azure-resources.ipyndb](./esml/azure_provisioning/01-azure-resources.ipynb)
    - Example: instead of `msft` maybe `acme` - then send the "prescription" to your IT/infra department, to provision via preconfigured Azure blueprint.
 - 3) Run the BICEP script (or create the resources manually for now - the button is IN progress right now, don't use.) 

<a href="https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fmicrosoft%2Fsolution-accelerator-many-models%2Fmaster%2Fazuredeploy.json" target="_blank">
    <img src="http://azuredeploy.net/deploybutton.png" alt="Work in progress!"/>
</a> 

  - Note: This should be done by a `ESML core team member`, supporting the projects. Not by projects themselves.
  - Note **Azure roles (IAM)**: 
    - Most part you only need to be have CONTRIBUTOR role on 2 resource groups, these 2 resource groups, you can ask you Security admin to create for you, and get OWNER or CONTRIBUTOR access on.
    - But, to create the service principle, you need to have the Azure role  to be able to create service principles (ask your IT department/subscription administrator) 
      - 1) Subscription level: You or your IT-admin needs to have the role to `register applications` (create service principles) for reasons A and B:   
          - Reason A): In Azure to create the SERVICE PRINCIPLES to be used in the 2 resource groups.
          - Reason B): Azure Devops needs a SERVICE PRINCIPLE to run the pipline Auzure CLI, as CONTRIBUTOR on Subscription level.
      - 2) Resource group level: You or your IT-admin needs to have `Owner role` or `User Access Administrator` role, to assigne the service principles in the 2 resource groups resources.
    - [Read more - howto create service principles](https://docs.microsoft.com/en-us/azure/active-directory/develop/howto-create-service-principal-portal#permissions-required-for-registering-an-app)

# 4) Configure ESML settings, to target YOUR Azure resources
1) You should copy all subfolders in `copy_my_subfolders_to_my_grandparent` to your root, next to the subclass `azure-enterprise-scale-ml`.
    - `Example:`: See here, for how these folders are use together with EMSL:  https://github.com/jostrm/azure-enterprise-scale-ml-usage
    - `adf`: Here is the Azur Data factory templates for `Scoring&Writeback`
    - `mlops`: This is a template, a working `MLOps pipeline, using the ESML SDK, that can deploy a model `across environments where DEV, TEST, PROD` can be in different workspaces/different Azure subscriptions.
    - `settings`: This is a template settings folder, for `dev,test,prod` to override
    - `demo_notebooks`: Notebooks redy to run - perfect for quick R&D mode.
- 2) Create your new branch for `Project` and `Model` 
    -  **Branch-name:** We recommend to include `organization/bu, project, and model`.
    - Ask your ESML-coreteam what project-number you have `001,...,123` and choose your model prefix `M01`,...`M34` 
    - > Important: `projectXXX` and `MXX` should be unique, and is a defined `ESML naming convention`
    - Example name: `microsoft_hr_project001_M01` or `hr_project001_M01`
- 3) EDIT the setting files, you copied to your rott: 
- Even if you did not edit the nanming convention, you still need to check the settings in at least the top 3 files below:
  - 1) [../settings/enterprise_specific/dev_test_prod_settings](../settings/enterprise_specific/dev_test_prod_settings.json) - Role: ESML coreteam/IT admin (`configure once`)
  - 2) [../settings/project_specific/security_config.json](../settings/project_specific/security_config.json)  - Role: ESML coreteam/IT admin (`configure once, per project`)
  - 3) [../settings/project_specific/model/lake_settings.json](../settings/project_specific/model/lake_settings.json)   - Role: Data scientist (Here you decide `dataset names` and model prefix `M01`)
  - 4) [../settings/active_dev_test_prod.json](../settings/active_dev_test_prod.json) Role: Data scientist, to set what environment to debug `dev,test,prod`
  - optional (adjust according to your policy): [../settings/enterprise_specific/*](../settings/enterprise_specific/*) - Role: ESML Coreteam - `defaults for all projects to start with`
  - optional (override enterprise policy, to fit the use case): [../settings/project_specific/*](../settings/project_specific/*)  Role: Data scientist `computes, automl performance settings` 

And - Clean these 3 files: [../settings/project_specific/model/dev_test_prod/automl/out/automl_active_model_dev.json](../settings/project_specific/model/dev_test_prod/train/automl/out/automl_active_model_dev.json)  
 > {
 >   "experiment_name": "",
 >   "model_name_automl": "",
 >   "run_id": -1,
 >   "dev_test_prod": "test",
 >   "registered_model_version": ""
 > }

# DONE! It should look something like this
- ESML Usage example: https://github.com/jostrm/azure-enterprise-scale-ml-usage

# TROUBLE SHOOT - Tips
## If manual security setup: SP - Keyvault IAM and Azure ML Studio
- A)AML Studio You need to have your project SP (esml-project005-sp-id) be CONTRIBUTOR on the DEV, TEST, PROD workspaces, or else you will seee this: 
  - > ERROR:azureml._project._commands:get_workspace error using subscription_id...
    
    > You have no (or access to) Azure ML Studio Workspace in environment 'dev'
    > You need the below created/access: ....
- B) Keyvault: You need let your SP (esml-project005-sp-id) have READ Secret accesss on external Keyvault, and READ/WRITE secret on the Azure ML Workspace defauly keyvault
  - or else you will receive this rudint .init(ws): 

  > *HttpResponseError: (Forbidden) The user, group or application 'appid=sdfdsf;oid=8sdf;iss=https://sts.windows.net/5dfgg9f/' does not have secrets get permission on key vault 'my-external-keyvault;location=westeurope'.*

## Q: "AKS error - cannot create cluster"
- A: Ask your IT admin to create the cluster for you (this is also recommended to get private link support). 
- Why the error? 
  - Sometimes enterprises has Azure POLICY's not allowing you to create AKS cluster of certain VM SKU type for its nodes (e.g.Standard DS3 v2),
    - If so, change this setting:  "aks_vm_size": "Standard_DS3_v2"
  - Or there is a POLICY/RBAC that you are not allowed to create resource gruops. The resource group AKS will create automatically will give this error
> "ReconcileResourceGroupError","message": "Resource request failed due to RequestDisallowedByPolicy. Please see https://aka.ms/aks-requestdisallowedbypolicy for more details
  