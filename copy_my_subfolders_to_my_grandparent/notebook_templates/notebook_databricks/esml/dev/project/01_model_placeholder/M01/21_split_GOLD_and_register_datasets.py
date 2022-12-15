# Databricks notebook source
# MAGIC %md
# MAGIC ## Don't forget to UPDATe the IMPORT path if you change the folderpath (01_your_model_placeholder)

# COMMAND ----------

#dbutils.widgets.removeAll()

# COMMAND ----------

esml_inference_mode = 1 # train = 1, inference=0
esml_env = "dev" # test, prod
esml_previous_step_is_databricks = 1 # 1=True, 0=False
esml_dataset_filename_ending = "*.parquet" # *.parquet | gold_dbx.parquet

esml_target_column_name = "my_col_name"
esml_split_percentage = 0.6

try:
  dbutils.widgets.text("esml_previous_step_is_databricks","1", "esml_previous_step_is_databricks")
  esml_previous_step_is_databricks = dbutils.widgets.get("esml_previous_step_is_databricks")
  esml_previous_step_is_databricks = int(getArgument("esml_previous_step_is_databricks"))
  print ("esml_previous_step_is_databricks:",esml_previous_step_is_databricks)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_mode","0", "esml_inference_mode=1, if scoring")
  esml_inference_mode = dbutils.widgets.get("esml_inference_mode")
  esml_inference_mode = getArgument("esml_inference_mode")
  print ("esml_inference_mode: ",esml_inference_mode)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_environment_dev_test_prod","dev", "esml environment dev,test,prod")
  esml_env = dbutils.widgets.get("esml_environment_dev_test_prod")
  esml_env = getArgument("esml_environment_dev_test_prod")
  print ("esml_environment_dev_test_prod:",esml_env)
except Exception as e:
  print(e)

try:
  dbutils.widgets.text("esml_dataset_filename_ending","*.parquet", "file extension")
  esml_dataset_filename_ending = dbutils.widgets.get("esml_dataset_filename_ending")
  esml_dataset_filename_ending = getArgument("esml_dataset_filename_ending")
  print ("esml_dataset_filename_ending:",esml_dataset_filename_ending)
except Exception as e:
  print(e)
  
## SPLIT SPECIFIC; Split percentage, Target_column / Label
try:
  dbutils.widgets.text("esml_target_column_name","Y", "Target column_name / label")
  esml_target_column_name = dbutils.widgets.get("esml_target_column_name")
  esml_target_column_name = getArgument("esml_target_column_name")
  print ("esml_target_column_name:",esml_target_column_name)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_split_percentage","0.6", "split_percentage str")
  esml_split_percentage = dbutils.widgets.get("esml_split_percentage")
  esml_split_percentage = float(getArgument("esml_split_percentage"))
  print ("split_percentage:",esml_split_percentage)
except Exception as e:
  print(e)
## SPLIT SPECIFIC

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

# MAGIC %md ## Use the `esml_lake` to know the datalake-design
# MAGIC - Never have to remember folder-paths again : ) 

# COMMAND ----------

print(esml_lake.gold_train)
print(esml_lake.gold_test)
print(esml_lake.gold_validate)
print(esml_lake.gold_train_dataset_name)
print(esml_lake.gold_test_dataset_name)
print(esml_lake.gold_validate_dataset_name)

# COMMAND ----------

# MAGIC %md
# MAGIC ## READ - GOLD (.parquet)

# COMMAND ----------

gold_file = esml_lake.gold
dbutils.fs.ls(gold_file) # File exists
gold_df = (spark.read.option("header","true").parquet(gold_file)) # Spark DF

# COMMAND ----------

gold_df.printSchema()

# COMMAND ----------

# MAGIC %md ## WRITE - GOLD_Train, Gold_Test, Gold_Validate

# COMMAND ----------

# MAGIC %md ### TODO 4 YOU - your split logic

# COMMAND ----------

print("This info might be handy if you want to do a STRATIFIED split, instead of a RANDOM split: ")
print("- esml_target_column_name:", esml_parameters.esml_target_column_name)
print("- esml_split_percentage:", esml_parameters.esml_split_percentage)

# COMMAND ----------

df_train= None
df_validate= None
df_test= None

train_percentage = esml_parameters.esml_split_percentage
validate_percentage = None
test_percentage = None

#### ESML implementation. But you can create a siimilar class, inherit IESMLSplitter and override this with your OWN logic here, how to split data
whats_left_for_both = round(1-train_percentage,1)  # 0.4 ...0.3 if 70%
left_per_set = round((whats_left_for_both / 2),2) # 0.2  ...0.15
validate_and_test = round((1-left_per_set),2) # 0.8 ....0.75

print(train_percentage, left_per_set, left_per_set)

dataframes = gold_df.randomSplit([train_percentage, left_per_set, left_per_set], seed=26)
df_train = dataframes[0]
df_validate = dataframes[1]
df_test = dataframes[2]

print("train", df_train.count())
print("validate", df_validate.count())
print("test", df_test.count())

# COMMAND ----------

# MAGIC %md ## // END TODO 4 YOU - your split logic

# COMMAND ----------

# MAGIC %md ### ESML Auto-Saves the splitted data to lake

# COMMAND ----------

df_train.printSchema()

# COMMAND ----------

df_train.write.mode("overwrite").parquet(esml_lake.gold_train)
df_validate.write.mode("overwrite").parquet(esml_lake.gold_validate)
df_test.write.mode("overwrite").parquet(esml_lake.gold_test)

# COMMAND ----------

# MAGIC %md ## ESML Auto-registers DATASETS: as Azure ML Datasets (needed in using AutoML in Azure ML from Databricks)

# COMMAND ----------

# MAGIC %run ../../../common/azure_functions

# COMMAND ----------

resource_group, workspace_name, in_data, out_path,physical_raw_prj01_in,physical_prj01 = getProjectEnvironment(azure_rg_project_number)
ws = getAzureMLWorkspace()
datastore = ws.get_default_datastore()
print(datastore.account_name)

# COMMAND ----------

physical_test = esml_lake.get_physical_path(physical_prj01,esml_lake.gold_test)
physical_test

# COMMAND ----------

from azureml.core.dataset import Dataset 

physical_train = esml_lake.get_physical_path(physical_prj01,esml_lake.gold_train)
physical_validate = esml_lake.get_physical_path(physical_prj01,esml_lake.gold_validate)
physical_test = esml_lake.get_physical_path(physical_prj01,esml_lake.gold_test)

dataset_train = Dataset.Tabular.from_parquet_files(path = [(datastore, physical_train)])
dataset_validate = Dataset.Tabular.from_parquet_files(path = [(datastore, physical_train)]) 
dataset_test = Dataset.Tabular.from_parquet_files(path = [(datastore, physical_train)]) 

train_dataset = dataset_train.register(workspace = ws,
                                 name = esml_lake.gold_validate_dataset_name,
                                 description = 'GOLD_VALIDATE dataset registered from Azure Databricks',
                                 create_new_version=True)

validate_dataset = dataset_validate.register(workspace = ws,
                                 name = esml_lake.gold_train_dataset_name,
                                 description = 'GOLD_TRAIN dataset registered from Azure Databricks',
                                 create_new_version=True)

test_dataset = dataset_test.register(workspace = ws,
                                 name = esml_lake.gold_test_dataset_name,
                                 description = 'GOLD_TEST dataset registered from Azure Databricks',
                                 create_new_version=True)

# COMMAND ----------

train_dataset

# COMMAND ----------

train_again = Dataset.get_by_name(ws,esml_lake.gold_train_dataset_name) # Gets v14
train_again
