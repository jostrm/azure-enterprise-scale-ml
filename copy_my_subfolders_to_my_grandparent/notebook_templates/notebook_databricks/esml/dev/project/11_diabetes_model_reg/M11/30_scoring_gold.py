# Databricks notebook source
# MAGIC %md # IMPORTS

# COMMAND ----------

import azureml.core
import pandas as pd
from azureml.core import Run
from pipelines.M11.esmlrt.interfaces.iESMLController import IESMLController

print(azureml.core.VERSION)

# COMMAND ----------

# MAGIC %md ### How to add own Python code to be references
# MAGIC
# MAGIC
# MAGIC Docs: https://docs.databricks.com/_extras/notebooks/source/files-in-repos.html
# MAGIC - 1) Current repo: The current working directory (/Workspace/Repos/<username>/<repo_name>) 
# MAGIC     - is automatically included in the Python path. You can import any module in the current directory or subdirectories.
# MAGIC - 2) Other REPOS: In the command below, replace <username> with your Databricks user name.
# MAGIC   - sys.path.append(os.path.abspath('/Workspace/Repos/<username>/supplemental_files'))

# COMMAND ----------

# MAGIC %md # ESML config 
# MAGIC - notebook_user_interactive_mode: Set to true if interactive, false if running notebook as pipelinestep

# COMMAND ----------

notebook_user_interactive_mode = False

# COMMAND ----------

# MAGIC %md ## IGNORE - Reads input parameters (boilerplate)

# COMMAND ----------

esml_date_folder_utc = None
esml_model_version = 0
esml_inference_mode = 1 # train = 0, inference=1 
esml_env = "dev" # test, prod
esml_previous_step_is_databricks = 0 # 1=True, 0=False
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
  dbutils.widgets.text("esml_date_folder_utc","1000-01-01 10:35:01.243860", "esml_date_folder_utc")
  esml_date_folder_utc = dbutils.widgets.get("esml_date_folder_utc")
  esml_date_folder_utc = getArgument("esml_date_folder_utc")
  print ("esml_date_folder_utc",esml_date_folder_utc) # esml_date
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_model_version","0", "Model version to score with, 0 and ESML will fetch leading model")
  esml_model_version = dbutils.widgets.get("esml_inference_model_version")
  esml_model_version = getArgument("esml_inference_model_version")
  print ("esml_model_version",esml_model_version)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_mode","0", "esml_inference_mode=0 training")
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
  dbutils.widgets.text("esml_aml_model_name","11_diabetes_model_reg", "esml_aml_model_name")
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
                       
try:
  dbutils.widgets.text("esml_output_lake_template","esml_output_lake_template", "esml_output_lake_template")
  esml_output_lake_template = dbutils.widgets.get("esml_output_lake_template")
  esml_output_lake_template = getArgument("esml_output_lake_template")
  print ("esml_output_lake_template:",esml_output_lake_template)
except Exception as e:
  print(e)

# COMMAND ----------

# MAGIC %md ### IGNORE - This is boilerplate - to fetch Azure ML Run

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
remote_run_id = None

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
        remote_run_id = remote_run.id
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

# MAGIC %md ### IGNORE END

# COMMAND ----------

# MAGIC %run ../00_model_settings/01_dataset_paths

# COMMAND ----------

print("In")

for ds in esml_lake.datasets:
  print (esml_lake.in_data[ds])
  
print("Bronze")
  
for ds in esml_lake.datasets:
  print (esml_lake.bronze[ds])
  
print("Silver")
  
for ds in esml_lake.datasets:
  print (esml_lake.silver[ds])

print("Gold (merge all silver)")
print(esml_lake.gold)

# COMMAND ----------

esml_parameters.esml_aml_model_name

# COMMAND ----------

# MAGIC %run ../../../common/azure_functions

# COMMAND ----------

# MAGIC %md # Init and fetched the ESML Project: Azure ML Workspace, Datalake access, etc

# COMMAND ----------

projectNumber = azure_rg_project_number # "001"
resource_group, workspace_name, in_data, out_path,physical_raw_prj01_in,physical_prj01 = getProjectEnvironment(projectNumber)
ws = getAzureMLWorkspace()
print(ws)
print (resource_group)
print (workspace_name)
print (in_data)
print (out_path)

# COMMAND ----------

# MAGIC %md # Init the ESML Databricks Controller: ESMLInferencer
# MAGIC - Helps to load correct model version / leading model
# MAGIC - Helps to load data to inference, and saves the results in correct lake location

# COMMAND ----------

# MAGIC %run ../../../common/ESMLDatabricksController

# COMMAND ----------

esmli = ESMLInferencer(
    aml_workspace = ws,
    esml_project_no = azure_rg_project_number,
    esml_parameters = esml_parameters,
    esml_output_lake_template = None
    )

print("Test print model version: {} and workspace name: {}".format(
    esmli.esml_parameters.esml_model_version,
    esmli.aml_workspace.name))

# COMMAND ----------

# MAGIC %md # GET MODEL and Historic path (where to save scored data)

# COMMAND ----------

aml_model, training_run_id = esmli.init_aml_model(esml_lake.gold_scored, remote_run)

print("Azure ML Model name: {} and Training run id_ {}".format(aml_model.name, training_run_id))
print("Historic path where scored data is saved:  {}".format(esmli.path_historic_scored))
#print("Historic template static from Pipeline parameter: {}".format("projects/project001/11_diabetes_model_reg/inference/{model_version}/scored/dev/{date_folder}/{id_folder}/gold_scored.parquet/"))

print("Current model to inference with: {} and its training RunId {}".format(esmli.current_aml_model.name, esmli.current_aml_model_train_run_id))


# COMMAND ----------

# MAGIC %md # Load data, SCORE DATA with MODEL, save results, save meta

# COMMAND ----------

model = esmli.load_model(esmli.current_aml_model)

gold_to_score_df = esmli.get_gold_to_score(esml_lake.gold_2_score)
pd_gold_to_score_df = gold_to_score_df.toPandas()
result = esmli.inference_model(pd_gold_to_score_df)
esmli.save_results(pandas_df=result, res_as_pandas_df=True,res_as_pyspark_df=True, run_id=remote_run_id) # SAVE RESULT: Historic path + Latest

# COMMAND ----------

# MAGIC %md # View the results predictions:

# COMMAND ----------

result.head()

# COMMAND ----------

last_gold_run_filename = "last_gold_run.csv"
last_gold_run_physical_template = "projects/project{esml_project_no}/{model_folder_name}/inference/active/gold_scored_runinfo"
last_gold_run_physical = last_gold_run_physical_template.format(esml_project_no=esmli._esml_project_no,model_folder_name=esml_parameters.esml_aml_model_name) + "/"+last_gold_run_filename
print(last_gold_run_physical)
