# Databricks notebook source
# MAGIC %run ../../00_project_settings/esml_project

# COMMAND ----------

# MAGIC %run ../../../common/esml_lake_design/esml_lake

# COMMAND ----------

import datetime
date_folder = None
print("ESML INPUT PARAMETERS - for PIPELINE")
print("")
    
if('esml_date_folder_utc' in vars() or 'esml_date_folder_utc' in globals() and esml_date_folder_utc is not None):
  print("esml_date_folder_utc:", esml_date_folder_utc)
  date_infolder = datetime.datetime.strptime(esml_date_folder_utc, '%Y-%m-%d %H:%M:%S.%f')
  esml_date_folder = date_infolder.strftime('%Y/%m/%d')

def get_dataset_names(dataset_names_in = None):
  #dataset_names_in = "ds01_diabetes,ds02_other"
  dataset_names = esml_dataset_names_in.split(",")
  names_clean = []
  for name in dataset_names:
    names_clean.append(name.replace(" ",""))
  return names_clean

if('esml_date_folder' in vars() or 'esml_date_folder' in globals() and esml_date_folder is not None):
  print("esml_date_folder:",str(esml_date_folder))
else:
  esml_date_folder = None

if('esml_model_version' in vars() or 'esml_model_version' in globals() and esml_model_version is not None):
  print("esml_model_version:",esml_model_version)
else:
  esml_model_version = None
if('esml_inference_mode' in vars() or 'esml_inference_mode' in globals() and esml_inference_mode is not None):
  print("esml_inference_mode:", esml_inference_mode)
else:
  esml_inference_mode = None
if('esml_env' in vars() or 'esml_env' in globals() and esml_env is not None):
  print("esml_env:",esml_env)

if('esml_dataset_names_in' in vars() or 'esml_dataset_names_in' in globals() and esml_dataset_names_in is not None):
  esml_dataset_names = get_dataset_names(esml_dataset_names_in)
  if(len(esml_dataset_names) >0):
    for name in esml_dataset_names:
      print("esml_dataset_names:",name)
else:
  esml_dataset_names = None

if('esml_dataset_filename_ending' in vars() or 'esml_dataset_filename_ending' in globals() and esml_dataset_filename_ending is not None):
  if(esml_dataset_filename_ending is not None):
    print("esml_dataset_filename_ending:",esml_dataset_filename_ending)
else:
  esml_dataset_filename_ending = None
  
# SPLIT and TRAIN specific
if('esml_split_percentage' in vars() or 'esml_split_percentage' in globals() and esml_split_percentage is not None):
  print("esml_split_percentage:",esml_split_percentage)
else:
  esml_split_percentage = None
  
if('esml_target_column_name' in vars() or 'esml_target_column_name' in globals() and esml_target_column_name is not None):
  print("esml_target_column_name:",esml_target_column_name)
else:
  esml_target_column_name = None
  
print("")
print("ESML INPUT PARAMETERS - for PIPELINE, END") 


# COMMAND ----------

class ESMLParameters(object):
  _esml_date_folder = None
  _esml_model_version = None
  _esml_inference_mode = None
  _esml_env = None
  _esml_dataset_names = None
  _esml_dataset_filename_ending = None
  # Split, Train
  _esml_split_percentage = None
  _esml_target_column_name = None
  
  def __init__(self,esml_model_version,esml_inference_mode,esml_env,esml_dataset_filename_ending,
              esml_dataset_names=None, esml_date_folder=None,esml_split_percentage=None,esml_target_column_name=None):
    
    self._esml_date_folder = esml_date_folder
    self._esml_model_version = esml_dataset_filename_ending
    self._esml_inference_mode = esml_inference_mode
    self._esml_env = esml_env
    self._esml_dataset_names = esml_dataset_names
    self._esml_dataset_filename_ending = esml_dataset_filename_ending
    
    self._esml_split_percentage = esml_split_percentage
    self._esml_target_column_name = esml_target_column_name
    
  @property
  def esml_date_folder(self):
    return self._esml_date_folder
  @property
  def esml_model_version(self):
    return self._esml_model_version
  @property
  def esml_inference_mode(self):
    return self._esml_inference_mode
  @property
  def esml_env(self):
    return self._esml_env
  @property
  def esml_dataset_names(self):
    return self._esml_dataset_names
  @property
  def esml_dataset_filename_ending(self):
    return self._esml_dataset_filename_ending
  @property
  def esml_split_percentage(self):
    return self._esml_split_percentage
  @property
  def esml_target_column_name(self):
    return self._esml_target_column_name
  
esml_parameters = ESMLParameters(esml_model_version,esml_inference_mode,esml_env,esml_dataset_filename_ending
                                 ,esml_dataset_names, esml_date_folder,esml_split_percentage,esml_target_column_name)

# COMMAND ----------

from enum import Enum
class ESMLStatus(str, Enum):
  # ESML status / stages
  esml_status_new = "esml_newly_trained" # Something to compare with the LEADING model. Registered to be able to TAGS Test_scoring = mlflow.None
  esml_status_demoted_or_archive = "demoted_or_archive" # Filter out during comparision ~ To demote a model. E.g. model already lost to LEADING model, already compared mlflow.? maybe mlflow.Archived is equivalent?
  esml_status_promoted_2_dev = "esml_promoted_2_dev" # INNER LOOP: A model that WON at some point in time in DEV-stage. The latest registered promoted model is the LEADING model.
  esml_status_promoted_2_test = "esml_promoted_2_test" # OUTER LOOP: A model that WON at some point in time in TEST-stage.
  esml_status_promoted_2_prod = "esml_promoted_2_prod" # OUTER LOOP: A model that WON at some point in time in PROD-stage.

  # MLFlow states: ESML supports MFFlow (and suggestion to AML v2 central registry) uses MLFlow stating: Staging|Archived|Production|None) as below, mapped to ESML
  mflow_stage_none = "None" # esml_status_new = newly trained model in Dev environment, e.g. R&D phase.
  mflow_stage_staging = "Staging" # esml_status_promoted_in_dev esml_status_promoted_2_test  = (Promoted in "Dev" or to "Test" environmet. MLFlow model registry does not have this granularity)
  mflow_stage_production = "Production" # esml_status_promoted_2_prod
  mflow_stage_archive = "Archive" # esml_status_not_new = To demote a model.

# COMMAND ----------

# DBTITLE 1,Settings/User - Configure per model (Who: data scientist/data engineer)
experiment_name = '11_diabetes_model_reg'
model_folder_name = '/'+experiment_name
experiment_name_train = experiment_name+'_pipe_IN_2_GOLD_TRAIN'

datasets = {"ds01_diabetes","ds02_other"}

if (date_folder is not None):
  active_in_train = "1000/01/01" # date_folder defaults
  active_in_scoring = "1000/01/01" # date_folder defaults
else:
  active_in_train = "1000/01/01" # defaults
  active_in_scoring = "1000/01/01" # defaults

active_model_version = "0"

# COMMAND ----------

# DBTITLE 1,---- END user setting ----
esml_lake = ESMLLake()
esml_lake.init_esml_lake_design(azure_rg_project_number,model_folder_name)
esml_lake.esml_generate_dataset_arrays(datasets,active_in_train,active_in_scoring,active_model_version)

# COMMAND ----------

#dbutils.notebook.exit(esml_lake)
