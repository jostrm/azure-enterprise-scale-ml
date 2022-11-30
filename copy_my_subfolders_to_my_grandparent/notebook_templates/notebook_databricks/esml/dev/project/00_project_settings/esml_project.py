# Databricks notebook source
# DBTITLE 1,Settings/Enterprise (only once for all projects - then copy to all workspaces. Who: Enterprise architect)
global esml_env
global esml_resource_group
global emsl_workspace_name
global esml_workspace_projetNumberFirst
global azure_rg_project_number

esml_env = "dev"
esml_resource_group="abc-def-esml-project{}-weu-{}-001-rg" # abc-def-esml-project001-weu-dev-001-rg  
emsl_workspace_name="aml-prj{}-eap-proj-weu-{}-001" # aml-prj001-weu-dev-001
esml_workspace_projectNumberFirst = True
esml_workspace_projectNumberXXX = True
esml_lake_projectNumberXXX = True

file_system_name = "lake3"
adl_name = "xxxyyy001{}" # Storage account name for datalake. Example: 'xxxyyy001{}' becomes 'xxxyyy001dev', xxxyyy001test, xxxyyy001prod
adl_name = adl_name.format(esml_env)
fs_url = "abfss://"+file_system_name+"@"+adl_name+".dfs.core.windows.net/"

global physical_master
global mount_master
global physical_project_template
global mount_project_template

physical_master = fs_url + 'master'
mount_master = "/mnt/master"
physical_project_template = fs_url + 'projects/project{}'  # Configure THIS due to YOUR lake-design
mount_project_template = "/mnt/prj{}"

# COMMAND ----------

# DBTITLE 1,Setttings/Project (Who: ESML core team, when onboarding a project)
azure_rg_project_number = "002"

# COMMAND ----------

global scope_name
global sp_id_sa_prj_rxe
global kv_name_amls


"""
Project specific SECURITY: Access to Azure ML Studio
All secrets in same scope: Keyvault for project, in projects resource groups
"""
kv_project_tenant_id = 'esml-tenant-id'
kv_project_aml_subscription_id = 'esml-subscription-id'

scope_name_project = 'esml-project-scope' # esml-project-scope
kv_project_azureml_sp_id = "esml-project-sp-id" 
kv_project_azureml_sp_secret = "esml-project-sp-secret"

# COMMAND ----------

# DBTITLE 1,---- END of user settings ----


# COMMAND ----------

def getWorkspaceName(projectNumber):
  workspace_name = ""
  if (len(projectNumber) == 3 and esml_workspace_projectNumberXXX == False):
    projectNumber = projectNumber[1:]

  if(esml_workspace_projectNumberFirst):
    workspace_name = emsl_workspace_name.format(projectNumber,esml_env)
  else:
    workspace_name = emsl_workspace_name.format(esml_env,projectNumber)
    
  resource_group = esml_resource_group.format(projectNumber,esml_env)
  return workspace_name, resource_group

def getMountFolders(projectNumber):
  physical_project = ""
  mount_project = ""
  if (len(projectNumber) == 3 and esml_lake_projectNumberXXX == False):
    physical_project = physical_project_template.format(projectNumber[1:]) # project01 in datalake
  elif(len(projectNumber) == 3 and esml_lake_projectNumberXXX == True):
    physical_project = physical_project_template.format(projectNumber)
  
  if (len(projectNumber) == 2): # always have XXX in mounts
    mount_project = mount_project_template.format(projectNumber.zfill(3))
  else:
    mount_project = mount_project_template.format(projectNumber)
    
  return physical_project,mount_project

# COMMAND ----------

"""
  projectNumber: 001,002, etc...or 02, 03
"""

def setProjectnumberXX(projectNumber = "001"):
  workspace_name,resource_group = getWorkspaceName(projectNumber)
  physical_project,mount_project = getMountFolders(projectNumber)
  
  return resource_group, workspace_name, mount_master, mount_project,physical_master,physical_project

# COMMAND ----------

def getProjectEnvironment(projectNumber = "001"):
  workspace_name,resource_group = getWorkspaceName(projectNumber)
  physical_project,mount_project = getMountFolders(projectNumber)
  
  return resource_group, workspace_name, mount_master, mount_project,physical_master,physical_project
