# ESML quickstart: Existing ADO/GIT project, configured by coreteam
Hi Project team. Maybe you just cloned the ADO repo to your laptop, or your DSVM (via Bastion)
Here is how to get started.

The below is instructions if you have a DSVM, or laptop, and needs to get the SDK up and running, and accelerator templates/MLOps/DataOps/Notebooks started.


# 1a) INIT GIT submodule
- Project already has the `submodule` called `azure-enterprise-scale-ml`, if this is just an empty folder with an `S` - do the below: 
- Open GIT command prompt or VS code terminal, go to your `local root folder for the code` (you should see the folder `azure-enterprise-scale-ml` and `notebook_demos` with a `dir` in the GIT CMD)run below: 

> git submodule update --init --recursive

If you get ann errormessage about `too long paths` then you need to open the GIT CMD prompt as `Administrator` and run the below (then try again)
> git config --system core.longpaths true

3) Azure ML SDK v1 and v2 CONDA is installed, and the ESML CODE is on your computer
- You have 2 repos now, if looking at "Source control" in VS code. 
- TODO: For the repo `azure-enterprise-scale-ml`, you need to "flip" to main branch, and when running notebooks, you need to select the correct CONDA-evironment. 
See images below: 

## 1b) Select correct BRANCH on the subclassed ESML library (only need to do this once)
![](./azure-enterprise-scale-ml/esml/images/quickstart_branch_guid_1.png)
![](./azure-enterprise-scale-ml/esml/images/quickstart_branch_guid_2.png)
![](./azure-enterprise-scale-ml/esml/images/quickstart_branch_guid_3.png)

# 2) Open a ESML template notebook (note what level the folder is on) to train models
![](./azure-enterprise-scale-ml/esml/images/quickstart_notebooks_1.png)
- Note: if you cannot see any `notebook_template_...` folder, but `settings` folder at your root,  please update ESML (pull latest on "azure-enterprise-scale-ml) , and then use the  [02_update_templates_QUICK.ipynb](./azure-enterprise-scale-ml/copy_my_subfolders_to_my_grandparent/02_update_templates_QUICK.ipynb) that automatically `UPDATES` (copy templtes folders) See `4) Copy TEMPLATES ` below in this readme.
- Note: If you cannot see either `notebook_template_...` or `settings` folder in your ROOT, then you need to `INIT` all TEMPLATES, run this notebook: [01_init_templates_ALL.ipynb](./azure-enterprise-scale-ml/copy_my_subfolders_to_my_grandparent/01_init_templates_ALL.ipynb) 

## 2b ) In the Notebook: Select correct CONDA environment, when running notebooks (only need to do this once, per notebook)
Click on Kernel and select Python interpreter:  `azure_automl_esml_v155_v115`

How to install, if missing: 
- AML SDKv1+SDKv2 - CD to `azure-enterprise-scale-ml\environment_setup\user_dev_env_install\AzureML_v1_55_and_v2_1_15\`
![](./azure-enterprise-scale-ml/esml/images/quickstart_notebooks_2_select_conda.png)


# 4) Copy TEMPLATES to your GIT branch, your root, and configure ESML settings to target YOUR Azure resources, and templates
### 4a) First time only:Run the Notebook 
- [01_init_templates_ALL.ipynb](./azure-enterprise-scale-ml/copy_my_subfolders_to_my_grandparent/01_init_templates_ALL.ipynb) 
- NB If you want, you can copy & paste the TEMPLATES manyally, You should copy all (except `notebook_templates`, here you should take a subfolder) subfolders in `copy_my_subfolders_to_my_grandparent` to your root, next to the subclass`azure-enterprise-scale-ml`
### 4b) 2nd time, or when you want to UPDATE templates: Azure ML pipeline template, Notebook templates etc, run this notebook
 - [02_update_templates_QUICK.ipynb](./azure-enterprise-scale-ml/copy_my_subfolders_to_my_grandparent/02_update_templates_QUICK.ipynb)

### How will it look like?
![](./azure-enterprise-scale-ml/esml/images/folder_structure_post_copy.png)
  
### 5a) Create your new branch for `Project` and `Model`  and EDIT the SETTINGS

  - Branch-name: We recommend to include organization/bu, project, and model.
  - Ask your ESML-coreteam what project-number you have 001,...,123 and choose your model prefix M01...M34 
  - Important: projectXXX and MXX should be unique, and is a defined ESML naming convention
  - Example name: `project001_M01` or HR_Dept_project001_M01


##### SETTINGS: EDIT the setting files, you copied to your root:
- Even if you did not edit the nanming convention, you still need to check the settings in at least the top 3 files below:
  - 1) [./settings/project_specific/model/lake_settings.json](./settings/project_specific/model/lake_settings.json)   - Role: Data scientist (Here you decide `dataset names` and model prefix `M01`)
  - 2) [./settings/project_specific/model/model_settings.json](./settings/project_specific/model/model_settings.json) Role: Data scientist, to set thresholds when a Model should be promoted. Can also set weights, on what metric is most important when comparing to promote model
   - optional (override enterprise policy, to fit the use case): [./settings/project_specific/*](./settings/project_specific/*)  Role: Data scientist `computes, automl performance settings` 

## 5b) DONE - Let run some NOTEBOOKS!

### `notebook_templates_quickstart` (recommended to start here)
  - Notebook templates. Runnable. Full workflow. 
  - TIP: Copy the `notebook_templates_quickstart` FOLDER for your OWN model, and rename it like `notebooks_M20` if your model is M20

[1_R&D_phase_M10_M11.ipynb](./notebook_templates_quickstart/1_R&D_phase_M10_M11.ipynb)
- NB! 2024-03: Training will fail. Run up until TRAIN with AutoML.

[2_PRODUCTION_phase_TRAIN_Pipeline_M10_M11.ipynb](./notebook_templates_quickstart/2_PRODUCTION_phase_TRAIN_Pipeline_M10_M11.ipynb)

[3a_PRODUCTION_phase_BATCH_INFERENCE_Pipeline_M11.ipynb](./notebook_templates_quickstart/3a_PRODUCTION_phase_BATCH_INFERENCE_Pipeline_M11.ipynb)

[3b_PRODUCTION_phase_ONLINE_INFERENCE_Endpoint_M11.ipynb](./notebook_templates_quickstart/3b_PRODUCTION_phase_ONLINE_INFERENCE_Endpoint_M11.ipynb)


### `notebook_templates_v14` (advanced notebooks)
  - All notebook teamplates. Not guaranteed / maintained to work 100%, but shows concepts of ESML.

[notebook_templates_esml_v14/0_update_templates_QUICK.ipynb](./notebook_templates_esml_v14/0_update_templates_QUICK.ipynb)
 - This UPDATES some TEMPLATES, and the QUICKSTART folder,with new fresh notebooks from ESML.
 - Safe to run it will backup your lake_settings.json and model_settings.json (but only run once, and then manuallytake your lake_settings.bak.json model clause, and past to new lake_settings.json)

[notebook_templates_esml_v14/00_v143_esml_1_clean.ipynb](./notebook_templates_esml_v14/00_v143_esml_1_clean.ipynb)
- This will clean any cashed LOGIN information, and CLEAN temp files. Run this if needed. If having login problem to Azure ML Studio workspace.

[notebook_templates_esml_v14/00_v143_esml_controller_misc.ipynb](./notebook_templates_esml_v14/00_v143_esml_controller_misc.ipynb)
- This explaines INNER and OUTER loop with the ESMLController class. 

[notebook_templates_esml_v14/00_v143_esml_ml_features.ipynb](./notebook_templates_esml_v14/00_v143_esml_ml_features.ipynb)
- This explaines various ESML Features. The "Bible" notebook of ESML if you wish. If it isn't there, ping me and we'll add it.

# TROUBLE SHOOT - Tips

### Q1) I get a StreamAccessException error when running the Pipeline, it the first steps "IN_2_SILVER 
 - There is a folder path in the Error message "projects/project...1000/01/01/...
### A1) This is the most common error. It means it cannot find the data in the datalek folder structure
- Verify the path you see in the errormessage, that data exists in the datalake
- Usual cause: you probably have the wrong DATE utc, for it to point at wrong date folders such as `2010/01/01`
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
  