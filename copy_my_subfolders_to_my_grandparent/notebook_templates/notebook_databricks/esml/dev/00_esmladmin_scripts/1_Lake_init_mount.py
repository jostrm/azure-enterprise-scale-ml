# Databricks notebook source
# %pip install --upgrade --force-reinstall -r https://aka.ms/automl_linux_requirements.txt

# COMMAND ----------

# MAGIC %md
# MAGIC # 1.Init datalake, mount folders for project XX

# COMMAND ----------

# DBTITLE 1,1a Init lake - import helper function
# MAGIC %run ../common/azure_functions

# COMMAND ----------

import os,sys,json
import azureml.core
from azureml.core import Workspace, Experiment, Datastore

# Check core SDK version number
print("SDK version:", azureml.core.VERSION)

# COMMAND ----------

# DBTITLE 1,1b Init lake, once for all projects (per filesystem)
#initLake()

# COMMAND ----------

print("subscription id: ", kv_project_aml_subscription_id)
print("azure ml: " +kv_project_azureml_sp_id)

#sp_id = dbutils.secrets.get(scope = scope_name_project, key =kv_project_azureml_sp_id) # Test that we can get the PROJECTS service principle, from projects Azure Keyvault 
#sp_id2 = dbutils.secrets.get(scope = scope_name_project, key =kv_project_aml_subscription_id) # Test that we can get the PROJECTS service principle, from projects Azure Keyvault 

# COMMAND ----------

# DBTITLE 1,Any Mounted folders?
dbutils.fs.mounts()
# The ESML mounts ADMIN needs to create is that of below. Note (project002 or project02 depends on the pysical lake-design preffered choice)


# COMMAND ----------

# DBTITLE 1,Mount 2 folders
projectNumber = "001" # 002 or 02 depends on your lake design
dbutils.notebook.run("../common/azure_functions",600, {"projectNumber": projectNumber})

# COMMAND ----------

dbutils.fs.mounts()

# COMMAND ----------

# MAGIC %md
# MAGIC # Check Lake-access

# COMMAND ----------

test_file = '/mnt/prj'+projectNumber+'/11_diabetes_model_reg/train/ds01_diabetes/in/dev/1000/01/01/'
dbutils.fs.ls(test_file) # File exists
df = (spark.read.option("header","true").csv(test_file)) # Spark DF

# COMMAND ----------

# MAGIC %md ## Check Azure ML Studio access for project

# COMMAND ----------

projectNumber = projectNumber # "001"
resource_group, workspace_name, in_data, out_path,physical_raw_prj01_in,physical_prj01 = getProjectEnvironment(projectNumber)
ws = getAzureMLWorkspace() # msft-weu-dev-eap-proj02_ai-amls
print(ws)
print (resource_group)
print (workspace_name)
print (in_data)
print (out_path)

# COMMAND ----------

#dbutils.fs.unmount('/mnt/prj003_train')
#dbutils.fs.unmount('/mnt/prj003_inference')

# COMMAND ----------

# MAGIC %md
# MAGIC Lake access works! Test accesst to Azure ML Workspace for projectXX