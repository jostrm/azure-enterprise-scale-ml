# Databricks notebook source
# MAGIC %run ../../00_project_settings/esml_project

# COMMAND ----------

# MAGIC %run ../../../common/esml_lake_design/esml_lake

# COMMAND ----------

# MAGIC %run ../../../common/ESMLDatabricksController

# COMMAND ----------

import datetime
#date_folder = None
esml_model_version_set = None
datetime_infolder = None
print("ESML INPUT PARAMETERS - for PIPELINE")
print("")
    
if('esml_date_folder_utc' in vars() or 'esml_date_folder_utc' in globals() and esml_date_folder_utc is not None):
  print("esml_date_folder_utc:", esml_date_folder_utc)
  datetime_infolder = datetime.datetime.strptime(esml_date_folder_utc, '%Y-%m-%d %H:%M:%S.%f')
  esml_date_folder = datetime_infolder.strftime('%Y/%m/%d')

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
  print("esml_model_version:::",esml_model_version)
  esml_model_version_set = esml_model_version
else:
  esml_model_version = 0
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
  
if('esml_aml_model_name' in vars() or 'esml_aml_model_name' in globals() and esml_aml_model_name is not None):
  print("esml_aml_model_name:",esml_aml_model_name)
else:
  esml_aml_model_name = None

if('esml_model_name_pkl' in vars() or 'esml_model_name_pkl' in globals() and esml_model_name_pkl is not None):
  print("esml_model_name_pkl:",esml_model_name_pkl)
else:
  esml_model_name_pkl = 'model.pkl'
  
print("")
print("ESML INPUT PARAMETERS - for PIPELINE, END") 


# COMMAND ----------

# MAGIC %md # TODO 4 YOU

# COMMAND ----------

# DBTITLE 1,Settings/User - Configure per model (Who: data scientist/data engineer)
experiment_name = '11_diabetes_model_reg'
model_folder_name = '/'+experiment_name
model_alias = 'M11'
experiment_name_train = experiment_name+'_pipe_IN_2_GOLD_TRAIN'

datasets = {"ds01_diabetes","ds02_other"}

active_in_train = None
active_in_scoring = None
active_model_version = None

if (esml_date_folder is not None):
  active_in_train = esml_date_folder # override with parameter
  active_in_scoring = esml_date_folder # override with parameter
else:
  active_in_train = "1000/01/01" # defaults
  active_in_scoring = "1000/01/01" # defaults

if(esml_model_version_set is not None):
  active_model_version = esml_model_version_set
else:
  active_model_version = 0

# COMMAND ----------

# MAGIC %md # TODO 4 YOU - END

# COMMAND ----------

dbfs_model_path = '/dbfs' + mount_project_template.format(azure_rg_project_number) +'/'+ experiment_name + '/train/model/'

esml_parameters = ESMLParameters(esml_inference_mode,esml_env,esml_dataset_filename_ending,dbfs_model_path,
                                 esml_dataset_names, esml_date_folder,datetime_infolder,esml_model_version, esml_split_percentage, esml_target_column_name, esml_aml_model_name,esml_model_name_pkl)

# COMMAND ----------

# DBTITLE 1,---- END user setting ----
esml_lake = ESMLLake()
esml_lake.inference_mode=esml_parameters.esml_inference_mode

esml_lake.init_esml_lake_design(azure_rg_project_number,model_folder_name, model_alias, esml_parameters.esml_model_version, esml_parameters.esml_date_folder,None) # run_id = None)
esml_lake.esml_generate_dataset_arrays(datasets,active_in_train,active_in_scoring,active_model_version)


# COMMAND ----------

#dbutils.notebook.exit(esml_lake)
