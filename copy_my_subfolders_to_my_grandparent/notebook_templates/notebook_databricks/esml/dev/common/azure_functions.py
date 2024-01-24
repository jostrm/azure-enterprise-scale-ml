# Databricks notebook source
# DBTITLE 1,1st time (not per project)
projectNumber = None
try:
  dbutils.widgets.text("projectNumber","XX", "Project number in Azure resourcegroup")
  projectNumber = dbutils.widgets.get("projectNumber")
  print (projectNumber)
except Exception as e:
  e

# COMMAND ----------

# DBTITLE 1,Import project specific paths 
# MAGIC %run ../project/00_project_settings/esml_project

# COMMAND ----------

# MAGIC %md ## TODO 4 you: Retrieve credentials (to Mount storage)
# MAGIC ### WHO: Administrator. Not project member
# MAGIC 1) Perequsites: Add Azure keuvault backed secret scope
# MAGIC   - https://learn.microsoft.com/en-us/azure/databricks/security/secrets/secret-scopes
# MAGIC   - Suggestion: Use the project specific scope, and use the secrect scope name 'esml-project-scope'
# MAGIC     - Why? If chosing that name, then you have correct config in [notebook_databricks/esml/dev/project/00_project_settings/esml_project](notebook_databricks/esml/dev/project/00_project_settings/esml_project) notebook
# MAGIC 2) Add the storage account access key as a secret in the keyvault, with name `esml-lake-storageaccount-key`
# MAGIC 3) Below cell: Point at the secrect scope, and what secret name to fetch, `esml-lake-storageaccount-key`, to get access key to the datalake (the esml-common storage account) when mounting
# MAGIC 4) Run the notebook: `1_Lake_init_mount` 
# MAGIC   - [notebook_databricks/esml/dev/00_esmladmin_scripts/1_Lake_init_mount](notebook_databricks/esml/dev/00_esmladmin_scripts/1_Lake_init_mount)
# MAGIC     
# MAGIC 5) Admin Remove the secret in the keyvault, with name `esml-lake-storageaccount-key`, since not needed anymore.

# COMMAND ----------

#TODO4you: Mount lake. Do this once only. Before 1st ESML project is onboarded.  ADMIN will use and know this, to mount project folders.

# Alt 1) Mount with Service principle - that has Storage Blob Data Contributor
# Alt 1a) Having credentials in the ADMIN keuvaylt: 'kv-cmnadmdev-..'
# Alt 1b) Having credentials in the 1st PROJECT keuvaylt: 'kv-p001-weu-dev', since this is needed to be added as secrect-scope anyhow. Then remove secret.
#Note:  Best is to use an ADMIN keuvault and service principle, but an ADMIN can use the project service principle, that temporary have "Storage Blob Cosntributor" on lake, while mounting.

# Alt 2) Use Storage account access key - from Project keyvault
scope_admin = scope_name_project # Points at a Azure keyvault
kv_tenant_id= kv_project_tenant_id
kv_acc_key_lake='kv-secret-cmnai-saKey' # 'esml-lake-storageaccount-key'

# COMMAND ----------

# MAGIC %md ## TODO 4 you: END

# COMMAND ----------

from azureml.core.workspace import Workspace
from azureml.core.authentication import ServicePrincipalAuthentication


def getAzureMLWorkspace(): 
  sp_id = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_id)
  sp_secret = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_secret)
  subscription_id = dbutils.secrets.get(scope = scope_name_project, key =kv_project_aml_subscription_id)
  
  tenant = dbutils.secrets.get(scope = scope_name_project, key = kv_project_tenant_id)
  
  svc_pr = ServicePrincipalAuthentication(
    tenant_id=tenant, 
    service_principal_id=sp_id, 
    service_principal_password=sp_secret)
  
  #print("resource_group: ",resource_group)
  #print("workspace_name: ",workspace_name)
  ws = Workspace(subscription_id=subscription_id,
                 resource_group=resource_group,
                 workspace_name=workspace_name,
                 auth=svc_pr)
  return ws

# COMMAND ----------

"""
Initializing File System
Only need to executed once per file system
"""
def initLake():
  #ADMIN sa key for mounting - admin/creatpr only that can access this scope
  #return "Lake alreay initiated"
  sa_key =  dbutils.secrets.get(scope = scope_admin, key = kv_acc_key_lake)  # Managed Principal = Creator
  
  spark.conf.set("fs.azure.account.key."+adl_name+".dfs.core.windows.net", sa_key)
  spark.conf.set("fs.azure.createRemoteFileSystemDuringInitialization", "true")
  dbutils.fs.ls(fs_url)
  spark.conf.set("fs.azure.createRemoteFileSystemDuringInitialization", "false")
  dbutils.fs.mounts()


# COMMAND ----------

from azureml.core import Datastore
def getDatastore(ws):
  sp_id = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_id)
  sp_secret = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_secret)
  tenant = dbutils.secrets.get(scope = scope_name_project, key = kv_project_tenant_id)
    
  datastore = Datastore.register_azure_data_lake_gen2(workspace=ws, 
                                                    datastore_name=adl_name, 
                                                    filesystem=file_system_name,
                                                    account_name=adl_name, 
                                                    tenant_id=tenant,
                                                    client_id=sp_id, # Storage blob contributor, or ACL on folder
                                                    client_secret=sp_secret)
  return datastore  

# COMMAND ----------

from azureml.core import Datastore
def registerLakeAsDatastore(ws):
  sp_id = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_id)
  sp_secret = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_secret)
  tenant = dbutils.secrets.get(scope = scope_name_project, key = kv_project_tenant_id)
  
  datastore = Datastore.register_azure_data_lake_gen2(workspace=ws, 
                                                    datastore_name=adl_name, 
                                                    filesystem=file_system_name,
                                                    account_name=adl_name, 
                                                    tenant_id=tenant,
                                                    client_id=sp_id,
                                                    client_secret=sp_secret)
  return datastore  

# COMMAND ----------

def getMountConfig(): 
  sp_id = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_id)
  sp_secret = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_secret)
  tenant = dbutils.secrets.get(scope = scope_name_project, key = kv_project_tenant_id)

  # SERVICE PRINCIPLE Information
  configs = {"fs.azure.account.auth.type": "OAuth",
             "fs.azure.account.oauth.provider.type": "org.apache.hadoop.fs.azurebfs.oauth2.ClientCredsTokenProvider",
             "fs.azure.account.oauth2.client.id": sp_id,  # Client ID is the ApplicationID/Service Principal ID that have "Blob Storage Contributor" role on LAKE (hence use an ADMIN sp, or just temporary have that role)
             "fs.azure.account.oauth2.client.secret": sp_secret,  # Secret for the SERVICE PRINCIPAL, in a secret scope in Databricks OR in Azure keuvault.
             "fs.azure.account.oauth2.client.endpoint": "https://login.microsoftonline.com/"+tenant+"/oauth2/token"}  #tenant
  
  return configs

# COMMAND ----------

# DBTITLE 1,Mount folders for projectXX
def mountFolders():
    print("physical_master:")
    print(physical_master)
    print("mount_master:")
    print(mount_master)
    print("")
    print("physical_project:")
    print(physical_project)
    print("mount_project:")
    print(mount_project)
    
    c = getMountConfig()
  
    dbutils.fs.mount(source = physical_master,  # Immutable read only DATA (if not using the shareback function from Data factory)
                 mount_point = mount_master,
                 extra_configs = c)
    
    dbutils.fs.mount(source = physical_project, # Project folder train/inference, in (read) and out folders (write)
                 mount_point = mount_project,
                 extra_configs = c)
    


# COMMAND ----------

if(projectNumber != "XX"):
  resource_group, workspace_name, mount_master, mount_project,physical_master,physical_project = getProjectEnvironment(projectNumber)
  mountFolders()
  print("folder mounted")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Imported... Azure util functions
