# Databricks notebook source
# MAGIC %md
# MAGIC ## Don't forget to UPDATe the IMPORT path if you change the folderpath (01_your_model_placeholder)

# COMMAND ----------

#%pip install --upgrade --force-reinstall -r https://aka.ms/automl_linux_requirements.txt

# COMMAND ----------

#dbutils.widgets.removeAll()

# COMMAND ----------

notebook_user_interactive_mode = False

# COMMAND ----------

import azureml.core
print(azureml.core.VERSION)

# COMMAND ----------

esml_date_folder_utc = None
esml_model_version = 0
esml_inference_mode = 1 # train = 1, inference=0 (not relevant here)
esml_env = "dev" # test, prod
esml_previous_step_is_databricks = 1 # 1=True, 0=False
esml_dataset_filename_ending = "*.parquet" # *.parquet | gold_dbx.parquet

esml_aml_model_name = None
esml_model_name_pkl = 'model.pkl'
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

try:
  dbutils.widgets.text("esml_model_name_pkl","model.pkl", "esml_model_name_pkl")
  esml_model_name_pkl = dbutils.widgets.get("esml_model_name_pkl")
  esml_model_name_pkl = getArgument("esml_model_name_pkl")
  print ("esml_model_name_pkl:",esml_model_name_pkl)
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

print("esml_aml_model_name: ".format(esml_parameters.esml_aml_model_name))
print("esml_model_name_pkl: ".format(esml_parameters.esml_model_name_pkl))
print("esml_target_column_name: ".format(esml_parameters.esml_target_column_name))

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

# MAGIC %run ../../../common/azure_functions

# COMMAND ----------

# MAGIC %md # READ splitted data - as Azure ML Datasets (points at same GOLD_TRAIN, ...)
# MAGIC - You can get the data via your Azure ML workspace also - verisoned Azure ML Datasets

# COMMAND ----------

from azureml.core import Dataset
resource_group, workspace_name, in_data, out_path,physical_raw_prj01_in,physical_prj01 = getProjectEnvironment(azure_rg_project_number)
ws = getAzureMLWorkspace()

train_aml_dataset = Dataset.get_by_name(ws,esml_lake.gold_train_dataset_name)
validate_aml_dataset = Dataset.get_by_name(ws,esml_lake.gold_validate_dataset_name)
test_aml_dataset = Dataset.get_by_name(ws,esml_lake.gold_test_dataset_name)

# COMMAND ----------

# MAGIC %md ## You can convert an Azure ML Dataset -  to Spark dataframe, or other

# COMMAND ----------

train_aml_dataset

# COMMAND ----------

try: # Only works if Databricks notebook '21_split_GOLD_and_register', did register the Datasets 
   pandas_df = train_aml_dataset.to_pandas_dataframe()
   spark_df = train_aml_dataset.to_spark_dataframe()  
except Exception as e:
    pass
    # 'FileDataset' object has no attribute 'to_pandas_dataframe'  azureml/1eb25ff4-7789-4b9f-9897-01a197928be2/M11_GOLD_TRAIN
    # If pipeline is registering the Dataset - the path will be similar to: 'azureml/1eb25ff4-7789-4b9f-9897-01a197928be2/M11_GOLD_TRAIN'

# COMMAND ----------

# MAGIC %md ## REMOTE Azure ML RUN - we are going to rehydrate THIS
# MAGIC - If this notebook is called from an Azure ML Pipeline, as a DatabricksStep - we want to hydrate this (to register Model, Metrics & keep lineage)

# COMMAND ----------

remote_run = None # This is going to be initiated from Azure ML parameters

# COMMAND ----------

# MAGIC %md # IGNORE - This is boilerplate - to fetch Azure ML Run

# COMMAND ----------

from azureml.core import Run
import os

try:
  dbutils.widgets.text("--AZUREML_RUN_TOKEN","ignore this", "AZUREML_RUN_TOKEN")
  AZUREML_RUN_TOKEN_w = dbutils.widgets.get("--AZUREML_RUN_TOKEN")
  AZUREML_RUN_TOKEN = getArgument("--AZUREML_RUN_TOKEN")
  #print ("--AZUREML_RUN_TOKEN:",AZUREML_RUN_TOKEN)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_RUN_TOKEN_EXPIRY","ignore this", "AZUREML_RUN_TOKEN_EXPIRY")
  AZUREML_RUN_TOKEN_EXPIRY_w = dbutils.widgets.get("--AZUREML_RUN_TOKEN_EXPIRY")
  AZUREML_RUN_TOKEN_EXPIRY = getArgument("--AZUREML_RUN_TOKEN_EXPIRY")
  print ("--AZUREML_RUN_TOKEN_EXPIRY:",AZUREML_RUN_TOKEN_EXPIRY)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_RUN_ID","ignore this", "AZUREML_RUN_ID")
  AZUREML_RUN_ID_w = dbutils.widgets.get("--AZUREML_RUN_ID")
  AZUREML_RUN_ID = getArgument("--AZUREML_RUN_ID")
  print ("--AZUREML_RUN_ID:",AZUREML_RUN_ID)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_ARM_SUBSCRIPTION","ignore this", "AZUREML_ARM_SUBSCRIPTION")
  AZUREML_ARM_SUBSCRIPTION_w = dbutils.widgets.get("--AZUREML_ARM_SUBSCRIPTION")
  AZUREML_ARM_SUBSCRIPTION = getArgument("--AZUREML_ARM_SUBSCRIPTION")
  print ("--AZUREML_ARM_SUBSCRIPTION:",AZUREML_ARM_SUBSCRIPTION)
  print("Verride with sub_id_not_redacted")
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_ARM_RESOURCEGROUP","ignore this", "AZUREML_ARM_RESOURCEGROUP")
  AZUREML_ARM_RESOURCEGROUP_w = dbutils.widgets.get("--AZUREML_ARM_RESOURCEGROUP")
  AZUREML_ARM_RESOURCEGROUP = getArgument("--AZUREML_ARM_RESOURCEGROUP")
  print ("--AZUREML_ARM_RESOURCEGROUP:",AZUREML_ARM_RESOURCEGROUP)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_ARM_WORKSPACE_NAME","ignore this", "AZUREML_ARM_WORKSPACE_NAME")
  AZUREML_ARM_WORKSPACE_NAME_w = dbutils.widgets.get("--AZUREML_ARM_WORKSPACE_NAME")
  AZUREML_ARM_WORKSPACE_NAME = getArgument("--AZUREML_ARM_WORKSPACE_NAME")
  print ("--AZUREML_ARM_WORKSPACE_NAME:",AZUREML_ARM_WORKSPACE_NAME)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_ARM_PROJECT_NAME","ignore this", "AZUREML_ARM_PROJECT_NAME")
  AZUREML_ARM_PROJECT_NAME_w = dbutils.widgets.get("--AZUREML_ARM_PROJECT_NAME")
  AZUREML_ARM_PROJECT_NAME = getArgument("--AZUREML_ARM_PROJECT_NAME")
  print ("--AZUREML_ARM_PROJECT_NAME:",AZUREML_ARM_PROJECT_NAME)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_SERVICE_ENDPOINT","ignore this", "AZUREML_SERVICE_ENDPOINT")
  AZUREML_SERVICE_ENDPOINT_w = dbutils.widgets.get("--AZUREML_SERVICE_ENDPOINT")
  AZUREML_SERVICE_ENDPOINT = getArgument("--AZUREML_SERVICE_ENDPOINT")
  print ("--AZUREML_SERVICE_ENDPOINT:",AZUREML_SERVICE_ENDPOINT)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_WORKSPACE_ID","ignore this", "AZUREML_WORKSPACE_ID")
  AZUREML_WORKSPACE_ID_w = dbutils.widgets.get("--AZUREML_WORKSPACE_ID")
  AZUREML_WORKSPACE_ID = getArgument("--AZUREML_WORKSPACE_ID")
  print ("--AZUREML_WORKSPACE_ID:",AZUREML_WORKSPACE_ID)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("--AZUREML_EXPERIMENT_ID","ignore this", "AZUREML_EXPERIMENT_ID")
  AZUREML_EXPERIMENT_ID_w = dbutils.widgets.get("--AZUREML_EXPERIMENT_ID")
  AZUREML_EXPERIMENT_ID = getArgument("--AZUREML_EXPERIMENT_ID")
  print ("--AZUREML_EXPERIMENT_ID:",AZUREML_EXPERIMENT_ID)
except Exception as e:
  print(e)
  
 # The AZUREML_SCRIPT_DIRECTORY_NAME argument will be filled in if the DatabricksStep was run using a local source_directory and python_script_name
try:
  dbutils.widgets.text("--AZUREML_SCRIPT_DIRECTORY_NAME","ignore this", "AZUREML_SCRIPT_DIRECTORY_NAME")
  AZUREML_SCRIPT_DIRECTORY_NAME_w = dbutils.widgets.get("--AZUREML_SCRIPT_DIRECTORY_NAME")
  AZUREML_SCRIPT_DIRECTORY_NAME = getArgument("--AZUREML_SCRIPT_DIRECTORY_NAME")
  print ("--AZUREML_SCRIPT_DIRECTORY_NAME:",AZUREML_SCRIPT_DIRECTORY_NAME)
except Exception as e:
  print(e)
  
remote_run = None

# Note that this workaround is not required for job clusters, e.g. not needed if using Azure ML pipeline via ESML
def rehydrate_azureml_run():
    print("populate_environ: AZUREML_RUN_ID {}".format(AZUREML_RUN_ID))
    os.environ['AZUREML_RUN_TOKEN'] = AZUREML_RUN_TOKEN
    os.environ['AZUREML_RUN_TOKEN_EXPIRY'] = AZUREML_RUN_TOKEN_EXPIRY
    os.environ['AZUREML_RUN_ID'] = AZUREML_RUN_ID
    os.environ['AZUREML_ARM_SUBSCRIPTION'] = AZUREML_ARM_SUBSCRIPTION # REDACTED
    os.environ['AZUREML_ARM_RESOURCEGROUP'] = AZUREML_ARM_RESOURCEGROUP
    os.environ['AZUREML_ARM_WORKSPACE_NAME'] =AZUREML_ARM_WORKSPACE_NAME
    os.environ['AZUREML_ARM_PROJECT_NAME'] = AZUREML_ARM_PROJECT_NAME
    os.environ['AZUREML_WORKSPACE_ID'] = AZUREML_WORKSPACE_ID
    os.environ['AZUREML_EXPERIMENT_ID'] = AZUREML_EXPERIMENT_ID
    
    if(notebook_user_interactive_mode == False):
        os.environ['AZUREML_SERVICE_ENDPOINT'] = AZUREML_SERVICE_ENDPOINT

try:
    rehydrate_azureml_run()
    remote_run = Run.get_context(allow_offline=False)
    if(remote_run is not None):
      print("1) populate_environ() - Get Run Success(online): remote_run.id: {}".format(remote_run.id))
      print("1) populate_environ() - Get Run Success(online): remote_run.parent.id: {}".format(remote_run.parent.id))
except Exception as e: 
    print("Warning 1: populate_environ() failed {}".format(e))
    try:
        remote_run = Run.get_context(allow_offline=False)
        if(remote_run is not None):
          print("2) Get Run Success(online): remote_run.id: {}".format(remote_run.id))
          print("2) Get Run Success(online): remote_run.parent.id: {}".format(remote_run.parent.id))
    except Exception as e2:
        print("Warning 2: Run.get_context(allow_offline=False) failed: {}".format(e2))
        try:
            remote_run = Run.get_context() # Run.get_context(allow_offline=False)
            if(remote_run is not None):
              print("3) Get Run (offline) Success: remote_run.id: {}".format(remote_run.id))
        except Exception as e3:
            print("Warning 3: Run.get_context() failed: {}".format(e3))


# COMMAND ----------

train_aml_dataset = Dataset.get_by_name(ws,esml_lake.gold_train_dataset_name)
gold_train_df.printSchema()

# COMMAND ----------

# MAGIC %md ## TRAIN MODEL - TODO 4 YOU
# MAGIC - TODO 5 YOU: implement the method `train_df` in <a href="$./30_train_code/your_train_code"> ./30_train_code/your_train_code</a> notebook
# MAGIC - `train_df(..) is called below from this notebook, referencing `your_train_code` in <a href="$./30_train_code/your_train_code"> ./30_train_code/your_train_code</a>

# COMMAND ----------

# MAGIC %run ./30_train_code/your_train_code

# COMMAND ----------

## TODO 5 YOU - implement the method train in './30_train_code/your_train_code' notebook
train_run = None
aml_model = None
fitted_model = None
full_local_path = None

model_name = experiment_name # The NAME in MODEL registry (Not that model_name TAG - may be different - you choose)
model_name_tag = experiment_name # A) If you want to keep Model comparison separate considering AutoML runs VS Manual runs
model_name_tag = esml_parameters.esml_aml_model_name # B) If you want to compare all Models - never mind if AutoML was used or Manual ML
dbfs_model_out_path = esml_parameters.esml_dbfs_model_path # '/dbfs/mnt/prj002/11_diabetes_model_reg/train/model/'

if(remote_run is None):
  train_run, aml_model,fitted_model,full_local_path,new_model_scoring_tags = train_df(gold_train_df,gold_validate_df,esml_parameters.esml_target_column_name,dbfs_model_out_path, False,remote_run)
else:
  train_run, aml_model,fitted_model,full_local_path,new_model_scoring_tags = train_df(gold_train_df,gold_validate_df,esml_parameters.esml_target_column_name,dbfs_model_out_path, True,remote_run)

# COMMAND ----------

# MAGIC %md ## Upload Fitted model to KNOWN location (to automate scoring pipeline later on)

# COMMAND ----------

model_output_folder='./outputs/'
model_full_dbfs_path =  esml_parameters.esml_dbfs_model_path + 'outputs/'
model_full_dbfs_file_path =  model_full_dbfs_path + esml_parameters.esml_model_name_pkl

if(train_run is not None):
  train_run.upload_file(name = model_output_folder+esml_parameters.esml_model_name_pkl, path_or_stream = full_local_path)
  #train_run.upload_file(name = esml_parameters.esml_model_name_pkl, path_or_stream = full_local_path)
else:
   try:
     os.makedirs(os.path.dirname(model_full_dbfs_file_path), exist_ok=True)
     pickle.dump(fitted_model, open(model_full_dbfs_file_path, 'wb'))
     print("Copy model to known location and name: {}{}".format(model_full_dbfs_path,esml_parameters.esml_model_name_pkl))
   except Exception as e:
     print("Error - could not Copy model to known location {}{}".format(model_full_dbfs_path,esml_parameters.esml_model_name_pkl))

# COMMAND ----------

# MAGIC %md # MLOps: Inner & Outer loop

# COMMAND ----------

# MAGIC %md ### Option A & B, both will benefit of the ESML bootstrap gives you the `Azure ML Workspace`
# MAGIC - Even though you want to do the MLOps yourself (test-setscoring, promote or not..), ESML gives you "some" acceleration here - the workspace.

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

# MAGIC %md ## Get Run.id

# COMMAND ----------

run_id = 0
if(remote_run is not None):
  try:
    run_id = remote_run.parent.id
  except Exception as e:
    print(e)
    print("Warning 6: Could not fetch Run.parent.id (online) from Run (not None) - Now trying remote_run.id instead of remote_run.parent.id")
    run_id = remote_run.id

# COMMAND ----------

# MAGIC %md # Define REGISTRATION of MODEL
# MAGIC - Docs / trouble shooting
# MAGIC   - https://learn.microsoft.com/en-us/answers/questions/162055/register-azure-ml-model-from-databricksstep.html
# MAGIC   - https://github.com/MicrosoftDocs/azure-docs/issues/45773

# COMMAND ----------

import tempfile
import sklearn
from azureml.core import Model
from azureml.core.resource_configuration import ResourceConfiguration

def register_aml_model(full_local_path_in,model_name,tags,target_ws,project_number,esml_model_experiment, description_in=""):
  if(full_local_path_in is None):
      full_local_path_in = get_default_localPath(project_number,esml_model_experiment)
  
  _resource_configuration = ResourceConfiguration(cpu=1, memory_in_gb=0.5)
  model = None
  try:
    model = Model.register(model_path=full_local_path_in, # Local file to upload and register as a model.
                    model_name=model_name,
                    model_framework=Model.Framework.SCIKITLEARN,  # Framework used to create the model.
                    model_framework_version=sklearn.__version__,  # Version of scikit-learn used to create the model.
                    resource_configuration= _resource_configuration, # ESML-Default: ResourceConfiguration(cpu=1, memory_in_gb=0.5)
                    tags=tags,
                    properties=tags,
                    description=description_in,
                    workspace=target_ws)
  except Exception as e:
    raise e
  return model

def get_default_localPath(project_number,esml_model_experiment):
  pkl_name = "outputs" # "model.pkl"
  temp_dir = tempfile.gettempdir()
  full_local_path = os.path.join(temp_dir, "esml",project_number,esml_model_experiment)
  full_local_path = os.path.join(full_local_path, pkl_name)
  print("ESML 32 - get_default_localPath = {}".format(full_local_path))
  return full_local_path

# COMMAND ----------

# MAGIC %md ### Option A - ESML managed MLOps: REGISTER model, as NEW, not promoted
# MAGIC - Let ESML Azure ML pipleline take care of test_set scoring, and comparison (INNER / OUTER LOOP) MLOps
# MAGIC - ESML tags model properly (MLFlow stages, and ESML status)

# COMMAND ----------

# MAGIC %md # REGISTER MODEL
# MAGIC - Trying to register on RUN & Model registry first, as fallback - only in Model registry
# MAGIC - TODO 4 YOU: Only register model. Then Nothing. Next pipeline-step in the Azure ML pipeline will do all MLOps INNER / OUTER Loop logic

# COMMAND ----------

print("AML Model name (for search and compare): " + model_name)
print("User location" + full_local_path)
print("Known location:" + model_full_dbfs_path + esml_parameters.esml_model_name_pkl)


# COMMAND ----------

# MAGIC %md ## CREATE TAGS - Testset SCORING etc

# COMMAND ----------

# 1) Register model with 'esml_status_new'
from datetime import datetime
time_stamp = str(datetime.now())
tags = {"esml_time_updated": time_stamp,"status_code": ESMLStatus.esml_status_new.value,"mflow_stage":ESMLStatus.mflow_stage_none.value, "run_id": run_id, "model_name": model_name, "trained_in_environment": esml_env, 
        "trained_in_workspace": ws.name, "experiment_name": experiment_name, "trained_with": "ManualPysparkDatabricks"}

# CLEAR scoring & Add potentially new manually calculated TEST_SET SCORING from tags
if("test_set_ROC_AUC" in new_model_scoring_tags):
    tags["test_set_Accuracy"] = new_model_scoring_tags.get("test_set_Accuracy")
    tags["test_set_ROC_AUC"] = new_model_scoring_tags.get("test_set_ROC_AUC")
    tags["test_set_Precision"] = new_model_scoring_tags.get("test_set_Precision")
    tags["test_set_Recall"] = new_model_scoring_tags.get("test_set_Recall")
    tags["test_set_F1_Score"] = new_model_scoring_tags.get("test_set_F1_Score")
    tags["test_set_Matthews_Correlation"] = new_model_scoring_tags.get("test_set_Matthews_Correlation")
    tags["test_set_CM"] = new_model_scoring_tags.get("test_set_CM")
if("test_set_RMSE" in new_model_scoring_tags):
    tags["test_set_RMSE"] = new_model_scoring_tags.get("test_set_RMSE")
    tags["test_set_R2"] = new_model_scoring_tags.get("test_set_R2")
    tags["test_set_MAPE"] = new_model_scoring_tags.get("test_set_MAPE")
    tags["test_set_Spearman_Correlation"] = new_model_scoring_tags.get("test_set_Spearman_Correlation")
    
tags

# COMMAND ----------

model_path = full_local_path

def register_aml_model_on_run(model_name,model_path,tags):
  print("model_name at remote_run.register_model: ", model_name)
  print("model_path (will override model_name when register) at remote_run.register_model: ", model_path)
  model = None
  if(model_path is not None):
      model = remote_run.register_model(model_name=model_name,model_path=model_path, tags=tags, description="") # Works, if manual ML you need to specify path where you saved model.
  else:
      model = remote_run.register_model(model_name=model_name, tags=tags, description="") # Works. If AutoML, pass the MAIN_RUN of AutoML that has AutoMLSettings property

try:
  #register_aml_model_on_run(model_name,model_path,tags)
  print("ESML 20 - REGISTER MODEL on RUN - without folder_path")
  register_aml_model_on_run(model_name,None,tags)
  print("ESML 20 - REGISTER MODEL on RUN - SUCCESS!")
except Exception as e:
  print("ESML 20 - WARNING: Could not register_aml_model_on_run, not trying registration on Model registry instead")
  print(" - Tried register on RUN without azure_run_path - did not work. Now trying register on RUN with AZURE_RUN_PATH / outputs / esml_parameters.esml_model_name_pkl \n")
  try:
    print("ESML 21 - REGISTER MODEL on RUN - with folder_path")
    azure_run_path = './outputs/'+esml_parameters.esml_model_name_pkl
    register_aml_model_on_run(model_name,azure_run_path,tags)
    print("ESML 21 - REGISTER MODEL on RUN - SUCCESS! \n")
  except Exception as e2:
    print("ESML 21 - WARNING: Tried register on RUN with azure_run_path - did not work. Now trying register direcly in MODEL REGISTRY")
    print(" - Fallback: Now register MODEL in MODEL registry directly (since registering via RUN was not possible) - register_aml_model, with model_path = / outputs / \n")
    
    dbfs_file_path_full =  model_full_dbfs_path + esml_parameters.esml_model_name_pkl
    print("ESML 22 - REGISTER MODEL on MODEL - path: {}".format(dbfs_file_path_full))
    try:
      register_aml_model(dbfs_file_path_full,model_name,tags,ws,projectNumber,experiment_name)
      print("ESML 22 - SUCCESS! \n")
    except Exception as e3:
      #print(e3)
      print("ESML 23 - REGISTER MODEL on MODEL - with local DBX path")
      print(" - Path: {}".format(full_local_path))
      register_aml_model(full_local_path,model_name,tags,ws,projectNumber,experiment_name)
      print("ESML 23 - SUCCESS! \n")
      


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
