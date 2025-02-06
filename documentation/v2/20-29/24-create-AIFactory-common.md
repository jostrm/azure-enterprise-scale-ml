# Configure AIFactory common
This is done by ESML Core team, before creating 1st AIFactory project.

1) Copy all configuration files, by running [this Notebook](../../../copy_my_subfolders_to_my_grandparent/01_init_templates_ALL.ipynb)
    - This will copy folders and settings from ESML AIFactory GITHUB repo, to your local root path. 
        - `aifactory` folder - local configuration for IaC
        - `mlops` folder - mlops templates
        - `settings` folder - project specific temaplates
2) Configure all files [here](../../../../aifactory/parameters/)
3) Import the Azure Devops / GHA pipelines
    - [Azure Devops - YAML](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md)
    - [Azure Devops - Classic](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/readme.md)
    - [Github Actions](../../../environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/readme.md)
4) Configure the pipelines
5) Run the pipelines


