# Databricks notebook source
# MAGIC %md
# MAGIC ## Don't forget to UPDATe the IMPORT path if you change the folderpath (01_your_model_placeholder)

# COMMAND ----------

#dbutils.widgets.removeAll()

# COMMAND ----------

esml_date_folder_utc = None
esml_model_version = 0
esml_inference_mode = 1 # train = 1, inference=0 (not relevant here)
esml_env = "dev" # test, prod
esml_previous_step_is_databricks = 1 # 1=True, 0=False
esml_dataset_filename_ending = "*.parquet" # *.parquet | gold_dbx.parquet

esml_aml_model_name = None
esml_target_column_name = "my_col_name"

try:
  dbutils.widgets.text("esml_previous_step_is_databricks","1", "esml_previous_step_is_databricks")
  esml_previous_step_is_databricks = dbutils.widgets.get("esml_previous_step_is_databricks")
  esml_previous_step_is_databricks = int(getArgument("esml_previous_step_is_databricks"))
  print ("esml_previous_step_is_databricks:",esml_previous_step_is_databricks)
except Exception as e:
  print(e)

try:
  dbutils.widgets.text("esml_training_folder_date","1000-01-01 10:35:01.243860", "UTC date")
  esml_date_folder_utc = dbutils.widgets.get("esml_training_folder_date")
  esml_date_folder_utc = getArgument("esml_training_folder_date")
  print ("esml_folder_date",esml_date_folder_utc) # esml_date
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_model_version","0", "Model version for promotion/compare")
  esml_model_version = dbutils.widgets.get("esml_inference_model_version")
  esml_model_version = getArgument("esml_inference_model_version")
  print ("esml_model_version",esml_model_version)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_mode","0", "esml_inference_mode=0 if training")
  esml_inference_mode = dbutils.widgets.get("esml_inference_mode")
  esml_inference_mode = getArgument("esml_inference_mode")
  print ("esml_inference_mode: ",esml_inference_mode)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_environment_dev_test_prod","dev", "esml environment dev,test,prod")
  esml_env = dbutils.widgets.get("esml_environment_dev_test_prod")
  esml_env = getArgument("esml_environment_dev_test_prod")
  print ("esml_environment_dev_test_prod",esml_env)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_dataset_filename_ending","*.parquet", "file extension")
  esml_dataset_filename_ending = dbutils.widgets.get("esml_dataset_filename_ending")
  esml_dataset_filename_ending = getArgument("esml_dataset_filename_ending")
  print ("esml_dataset_filename_ending:",esml_dataset_filename_ending)
except Exception as e:
  print(e)

# TRAIN Specific
try:
  dbutils.widgets.text("esml_target_column_name","Y", "Target column_name / label")
  esml_target_column_name = dbutils.widgets.get("esml_target_column_name")
  esml_target_column_name = getArgument("esml_target_column_name")
  print ("esml_target_column_name:",esml_target_column_name)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_aml_model_name","Automl123abc_or_11_diabetes_model_reg", "esml_aml_model_name")
  esml_aml_model_name = dbutils.widgets.get("esml_aml_model_name")
  esml_aml_model_name = getArgument("esml_aml_model_name")
  print ("esml_aml_model_name:",esml_aml_model_name)
except Exception as e:
  print(e)

# COMMAND ----------

# MAGIC %run ../00_model_settings/01_dataset_paths

# COMMAND ----------

# MAGIC %md ## Use `esml_parameters` to get auto-completion on ESML specific input parameters
# MAGIC 
# MAGIC Example: `esml_parameters.`  CTRL+SPACE
# MAGIC 
# MAGIC - esml_parameters.esml_dataset_names

# COMMAND ----------

print(esml_parameters.esml_target_column_name)

# COMMAND ----------

# MAGIC %md ## Use `ESMLStatus` to set ESML INNER / OUTER loop MLOps status (and/or MFLow stage)

# COMMAND ----------

print(ESMLStatus.esml_status_promoted_2_dev)
print(ESMLStatus.esml_status_promoted_2_dev.value)
print("")
print(ESMLStatus.mflow_stage_staging)
print(ESMLStatus.mflow_stage_staging.value)

# COMMAND ----------

# MAGIC %md ## Use the `esml_lake` to know the datalake-design
# MAGIC - Never have to remember folder-paths again : ) 

# COMMAND ----------

print(esml_lake.gold_train)
print(esml_lake.gold_validate)
print(esml_lake.gold_test)

# COMMAND ----------

# MAGIC %md
# MAGIC ## READ splitted data - GOLD_TRAIN, _VALIDATE, _TEST, (*.parquet)

# COMMAND ----------

gold_train_df = (spark.read.option("header","true").parquet(esml_lake.gold_train)) # Spark DF
gold_validate_df = (spark.read.option("header","true").parquet(esml_lake.gold_validate))
gold_test_df = (spark.read.option("header","true").parquet(esml_lake.gold_test))

# COMMAND ----------

from azureml.core import Run
import argparse
import os

# Note that this workaround is not required for job clusters, e.g. not needed if using Azure ML pipeline via ESML
def populate_environ():
    parser = argparse.ArgumentParser(description='Process arguments passed to script')

    # The AZUREML_SCRIPT_DIRECTORY_NAME argument will be filled in if the DatabricksStep
    # was run using a local source_directory and python_script_name
    parser.add_argument('--AZUREML_SCRIPT_DIRECTORY_NAME')

    # Remaining arguments are filled in for all databricks jobs and can be used to build the run context
    parser.add_argument('--AZUREML_RUN_TOKEN')
    parser.add_argument('--AZUREML_RUN_TOKEN_EXPIRY')
    parser.add_argument('--AZUREML_RUN_ID')
    parser.add_argument('--AZUREML_ARM_SUBSCRIPTION')
    parser.add_argument('--AZUREML_ARM_RESOURCEGROUP')
    parser.add_argument('--AZUREML_ARM_WORKSPACE_NAME')
    parser.add_argument('--AZUREML_ARM_PROJECT_NAME')
    parser.add_argument('--AZUREML_SERVICE_ENDPOINT')
    parser.add_argument('--AZUREML_WORKSPACE_ID')
    parser.add_argument('--AZUREML_EXPERIMENT_ID')

    (args, extra_args) = parser.parse_known_args()
    os.environ['AZUREML_RUN_TOKEN'] = args.AZUREML_RUN_TOKEN
    os.environ['AZUREML_RUN_TOKEN_EXPIRY'] = args.AZUREML_RUN_TOKEN_EXPIRY
    os.environ['AZUREML_RUN_ID'] = args.AZUREML_RUN_ID
    os.environ['AZUREML_ARM_SUBSCRIPTION'] = args.AZUREML_ARM_SUBSCRIPTION
    os.environ['AZUREML_ARM_RESOURCEGROUP'] = args.AZUREML_ARM_RESOURCEGROUP
    os.environ['AZUREML_ARM_WORKSPACE_NAME'] = args.AZUREML_ARM_WORKSPACE_NAME
    os.environ['AZUREML_ARM_PROJECT_NAME'] = args.AZUREML_ARM_PROJECT_NAME
    os.environ['AZUREML_SERVICE_ENDPOINT'] = args.AZUREML_SERVICE_ENDPOINT
    os.environ['AZUREML_WORKSPACE_ID'] = args.AZUREML_WORKSPACE_ID
    os.environ['AZUREML_EXPERIMENT_ID'] = args.AZUREML_EXPERIMENT_ID

try:
  populate_environ()
  run = Run.get_context(allow_offline=False)
  print(run.parent.id)
except Exception as e: 
  print("Warning: populate_environ() failed {}".format(e))


# COMMAND ----------

gold_train_df.printSchema()

# COMMAND ----------

# MAGIC %run ./30_train_code/your_train_code

# COMMAND ----------

# MAGIC %md ## TRAIN MODEL

# COMMAND ----------

## TODO 5 YOU - implement the method train in './30_train_code/your_train_code' notebook

train_run, aml_model,fitted_model,full_local_path = train_df(gold_train_df,gold_validate_df,esml_parameters.esml_target_column_name, False)

# COMMAND ----------

# MAGIC %md # MLOps: Inner & Outer loop

# COMMAND ----------

# MAGIC %md ### Option A & B, both will benefit of the ESML bootstrap gives you the `Azure ML Workspace`
# MAGIC - Even though you want to do the MLOps yourself (test-setscoring, promote or not..), ESML gives you "some" acceleration here - the workspace.

# COMMAND ----------

# MAGIC %run ../../../common/azure_functions

# COMMAND ----------

print("My project number, as in Azure services convention (Either 001, or 01) is:",azure_rg_project_number)
projectNumber = azure_rg_project_number
resource_group, workspace_name, in_data, out_path,physical_raw_prj01_in,physical_prj01 = getProjectEnvironment(projectNumber)
ws = getAzureMLWorkspace() # msft-weu-dev-eap-proj02_ai-amls

print("")
print("### ESML gives you the Azure ML workspace for your project and environment ### ")
print("")
print(ws)
print ("Resource group",resource_group)
print ("Workspace name", workspace_name)
#print (in_data)
#print (out_path)

# COMMAND ----------

# ESML status / stages
print(ESMLStatus.esml_status_new)  # Something to compare with the LEADING model. Registered to be able to TAGS Test_scoring = mlflow.None
print(ESMLStatus.esml_status_new.value)

print(ESMLStatus.mflow_stage_none) # Equivalent almist to esml_status_new

# COMMAND ----------

#run = Run.get_context(allow_offline=False)
#run_id = run.parent.id
run_id = 0
model_name = experiment_name

# COMMAND ----------

import tempfile
import sklearn
from azureml.core import Model
from azureml.core.resource_configuration import ResourceConfiguration

def register_aml_model(full_local_path,model_name,tags,target_ws,project_number,esml_model_experiment, description_in=""):
  full_local_path = "."
  if(full_local_path is None):
      full_local_path = get_default_localPath(project_number,esml_model_experiment)
  
  _resource_configuration = ResourceConfiguration(cpu=1, memory_in_gb=0.5)
  model = Model.register(model_path=full_local_path, # Local file to upload and register as a model.
                  model_name=model_name,
                  model_framework=Model.Framework.SCIKITLEARN,  # Framework used to create the model.
                  model_framework_version=sklearn.__version__,  # Version of scikit-learn used to create the model.
                  resource_configuration= _resource_configuration, # ESML-Default: ResourceConfiguration(cpu=1, memory_in_gb=0.5)
                  tags=tags,
                  properties=tags,
                  description=description_in,
                  workspace=target_ws)
  return model

def get_default_localPath(project_number,esml_model_experiment):
  pkl_name = "outputs" # "model.pkl"
  temp_dir = tempfile.gettempdir()
  full_local_path = os.path.join(temp_dir, "esml",project_number,esml_model_experiment)
  full_local_path = os.path.join(full_local_path, pkl_name)
  return full_local_path

# COMMAND ----------

# MAGIC %md ### Option A - ESML managed MLOps: REGISTER model, as NEW, not promoted
# MAGIC - Let ESML Azure ML pipleline take care of test_set scoring, and comparison (INNER / OUTER LOOP) MLOps
# MAGIC - ESML tags model properly (MLFlow stages, and ESML status)

# COMMAND ----------

# TODO: Only register model. Then Nothing. Next pipeline-step in the Azure ML pipeline will do all MLOps INNER / OUTER Loop logic

# COMMAND ----------

import datetime

model_path = full_local_path

# 1) Register model with 'esml_status_new'
time_stamp = str(datetime.datetime.now())
tags = {"esml_time_updated": time_stamp,"status_code": ESMLStatus.esml_status_new.value,"mflow_stage":ESMLStatus.mflow_stage_none.value, "run_id": run_id, "model_name": model_name, "trained_in_environment": esml_env, 
        "trained_in_workspace": ws.name, "experiment_name": experiment_name, "trained_with": "ManualPysparkDatabricks"}

def register_aml_model_on_run(model_name,model_path,tags):
  print("model_name at remote_run.register_model: ", model_name)
  print("model_path (will override model_name when register) at remote_run.register_model: ", model_path)
  model = None
  if(model_path is not None):
      model = remote_run.register_model(model_name=model_name,model_path=model_path, tags=tags, description="") # Works, if manual ML you need to specify path where you saved model.
  else:
      model = remote_run.register_model(model_name=model_name, tags=tags, description="") # Works. If AutoML, pass the MAIN_RUN of AutoML that has AutoMLSettings property

try:
  register_aml_model_on_run(model_name,model_path,tags)
except Exception as e:
  print("Warning ESML: Could not register_aml_model_on_run, not trying registration on Model registry instead")
  print(e)
  register_aml_model(model_path,model_name,tags,ws,"002",experiment_name)
      
  

# COMMAND ----------

# MAGIC %md ### Option B - Self-managed MLOps: REGISTER model, as NEW, not promoted
# MAGIC - You take care of test_set scoring, and comparison (INNER / OUTER LOOP) MLOps
# MAGIC - You neeed to TAG model accordingly, for it to be promoted.
# MAGIC - e.g. All below:
# MAGIC   - 1) Register model with status_code=`esml_status_new` (and mflow_stage_none)
# MAGIC   - 2) Calculate testset scoring
# MAGIC   - 3) MLOps INNER LOOP Compare: if newly trained model is better than leading model in same environment/DEV
# MAGIC     - If so, promote, by retagging to `esml_status_promoted_2_dev`(and mflow_stage_staging), register model again
# MAGIC   - 4) MLOps OUTER LOOP Compare: if newly trained model is better than leading model in next environment/TEST
# MAGIC     - If so, promote, by retagging to `esml_status_promoted_2_test`, register model again in other Azure ML Workspace

# COMMAND ----------

# MAGIC %md ### Option B) TODO 4 YOU (Note: only if B) is chosen  - this is automated in Alt A - ESML managed):
# MAGIC   - 1) Register model with status_code=`esml_status_new` (and mflow_stage_none)
# MAGIC   - 2) Calculate testset scoring
# MAGIC   - 3) MLOps INNER LOOP Compare: if newly trained model is better than leading model in same environment/DEV
# MAGIC     - If so, promote, by retagging to `esml_status_promoted_2_dev`(and mflow_stage_staging), register model again
# MAGIC   - 4) MLOps OUTER LOOP Compare: if newly trained model is better than leading model in next environment/TEST
# MAGIC     - If so, promote, by retagging to `esml_status_promoted_2_test`, register model again in other Azure ML Workspace

# COMMAND ----------

# MAGIC %md
# MAGIC import datetime
# MAGIC 
# MAGIC # 1) Register model with 'esml_status_new'
# MAGIC time_stamp = str(datetime.datetime.now())
# MAGIC tags = {"esml_time_updated": time_stamp,"status_code": ESMLStatus.esml_status_new.value,"mflow_stage":"None", "run_id": run_id, "model_name": model_name, "trained_in_environment": esml_env, 
# MAGIC         "trained_in_workspace": ws.name, "experiment_name": experiment_name, "trained_with": "ManualPysparkDatabricks"}
# MAGIC     
# MAGIC 
# MAGIC # 2) Calcluate testset scoring, needed to be able to compare/MLOps
# MAGIC  # TODO 4 YOU - Calculate the following, on the TEST_SET
# MAGIC   
# MAGIC if("test_set_ROC_AUC" in model_source.tags):
# MAGIC   tags["test_set_Accuracy"] = model_source.tags["test_set_Accuracy"]
# MAGIC   tags["test_set_ROC_AUC"] = model_source.tags["test_set_ROC_AUC"]
# MAGIC   tags["test_set_Precision"] = model_source.tags["test_set_Precision"]
# MAGIC   tags["test_set_Recall"] = model_source.tags["test_set_Recall"]
# MAGIC   tags["test_set_F1_Score"] = model_source.tags["test_set_F1_Score"]
# MAGIC   tags["test_set_Matthews_Correlation"] = model_source.tags["test_set_Matthews_Correlation"]
# MAGIC   tags["test_set_CM"] = model_source.tags["test_set_CM"]
# MAGIC if("test_set_RMSE" in model_source.tags):
# MAGIC   tags["test_set_RMSE"] = model_source.tags["test_set_RMSE"]
# MAGIC   tags["test_set_R2"] = model_source.tags["test_set_R2"]
# MAGIC   tags["test_set_MAPE"] = model_source.tags["test_set_MAPE"]
# MAGIC   tags["test_set_Spearman_Correlation"] = model_source.tags["test_set_Spearman_Correlation"]
# MAGIC if("esml_time_updated " in model_source.tags):
# MAGIC   tags["esml_time_updated"] = model_source.tags["esml_time_updated"]
# MAGIC   
# MAGIC # 3) MLOps INNER LOOP Compare
# MAGIC   # TODO 4 YOU
# MAGIC # 4) MLOps OUTER LOOP Compare
# MAGIC   # TODO 4 YOU
