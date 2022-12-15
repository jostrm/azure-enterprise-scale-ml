# Databricks notebook source
# MAGIC %md
# MAGIC ## Don't forget to UPDATe the IMPORT path if you change the folderpath (01_your_model_placeholder)

# COMMAND ----------

#dbutils.widgets.removeAll()

# COMMAND ----------

esml_date_folder_utc = None
esml_model_version = 0
esml_inference_mode = 0 # train = 1
esml_env = "dev" # test, prod
esml_dataset_names_in = None
esml_dataset_filename_ending = "*.parquet" # *.parquet | ds01_diabetes.parquet
esml_previous_step_is_databricks = 1 # 1=True, 0=False

# TBA
esml_path_gold_to_score_template_path = ""

try:
  dbutils.widgets.text("esml_previous_step_is_databricks","1", "esml_previous_step_is_databricks")
  esml_previous_step_is_databricks = dbutils.widgets.get("esml_previous_step_is_databricks")
  esml_previous_step_is_databricks = int(getArgument("esml_previous_step_is_databricks"))
  print ("esml_previous_step_is_databricks:",esml_previous_step_is_databricks)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_training_folder_date","1000-01-01 10:35:01.243860", "folder_date: UTC date")
  esml_date_folder_utc = dbutils.widgets.get("esml_training_folder_date")
  esml_date_folder_utc = getArgument("esml_training_folder_date")
  print ("esml_folder_date:",esml_date_folder_utc)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_model_version","0", "Model version if scoring")
  esml_model_version = dbutils.widgets.get("esml_inference_model_version")
  esml_model_version = getArgument("esml_inference_model_version")
  print ("esml_model_version:",esml_model_version)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_mode","0", "esml_inference_mode if scoring")
  esml_inference_mode = dbutils.widgets.get("esml_inference_mode")
  esml_inference_mode = getArgument("esml_inference_mode")
  print ("esml_inference_mode:",esml_inference_mode)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_environment_dev_test_prod","dev", "esml environment dev,test,prod")
  esml_env = dbutils.widgets.get("esml_environment_dev_test_prod")
  esml_env = getArgument("esml_environment_dev_test_prod")
  print ("esml_env:",esml_env)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_dataset_names_to_merge","ds01_diabetes, ds02_other", "ESML dataset array")
  esml_dataset_names_in = dbutils.widgets.get("esml_dataset_names_to_merge")
  esml_dataset_names_in = getArgument("esml_dataset_names_to_merge")
  print ("esml_dataset_names_to_merge:",esml_dataset_names_in)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_dataset_filename_ending","*.parquet", "file extension")
  esml_dataset_filename_ending = dbutils.widgets.get("esml_dataset_filename_ending")
  esml_dataset_filename_ending = getArgument("esml_dataset_filename_ending")
  print ("esml_dataset_filename_ending:",esml_dataset_filename_ending)
except Exception as e:
  print(e)

#if (esml_inference_mode == 1):
#  try:
#    dbutils.widgets.text("esml_path_gold_to_score_template_path","", "esml_path_gold_to_score_template_path")
#    esml_path_gold_to_score_template_path = dbutils.widgets.get("esml_path_gold_to_score_template_path")
#    esml_path_gold_to_score_template_path = getArgument("esml_path_gold_to_score_template_path")
#    print ("esml_path_gold_to_score_template_path: ",esml_path_gold_to_score_template_path)
#  except Exception as e:
#    print(e)

# COMMAND ----------

# MAGIC %run ../00_model_settings/01_dataset_paths

# COMMAND ----------

# MAGIC %md ## Use `esml_parameters` to get auto-completion on ESML specific input parameters
# MAGIC 
# MAGIC Example: `esml_parameters.`  CTRL+SPACE
# MAGIC 
# MAGIC - esml_parameters.esml_dataset_names

# COMMAND ----------

for name in esml_parameters.esml_dataset_names:
  print(name)

# COMMAND ----------

# MAGIC %md ## Use the `esml_lake` to know the datalake-design
# MAGIC - Never have to remember folder-paths again : ) 

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

print(esml_lake.gold_train)
print(esml_lake.gold_test)
print(esml_lake.gold_validate)

# COMMAND ----------

# MAGIC %md ### MERGE 2 SILVER dataframes, and save to GOLD

# COMMAND ----------

for name in esml_parameters.esml_dataset_names:
  #fix = name.replace(" ","")
  print(name)

# COMMAND ----------

ds_name_1 = esml_parameters.esml_dataset_names[0]
ds_name_2 = esml_parameters.esml_dataset_names[1]

# READ 1st SILVER dataset
df_silver_file =  esml_lake.silver[ds_name_1]
df1_silver = spark.read.parquet(df_silver_file)

# READ 2nd SILVER dataset
df_silver_file2 =  esml_lake.silver[ds_name_2]
df2_silver_other = spark.read.parquet(df_silver_file2)


# COMMAND ----------

print("Before merge", df1_silver.count())
print("Before merge", df2_silver_other.count())

# COMMAND ----------

df_all = df1_silver.unionAll(df2_silver_other)
print("After merge", df_all.count())

# COMMAND ----------

# MAGIC %md # Feature engineering on UNION of SILVER to create GOLD

# COMMAND ----------

from pyspark.sql.types import IntegerType,BooleanType,FloatType,DateType

df = df_all
# Convert String to Integer Type
df = df.withColumn("AGE",df.AGE.cast(FloatType()))
df = df.withColumn("SEX",df.SEX.cast(FloatType()))
df = df.withColumn("BMI",df.BMI.cast(FloatType()))
df = df.withColumn("BP",df.BP.cast(FloatType()))
df = df.withColumn("S1",df.S1.cast(FloatType()))
df = df.withColumn("S2",df.S2.cast(FloatType()))
df = df.withColumn("S3",df.S3.cast(FloatType()))
df = df.withColumn("S4",df.S4.cast(FloatType()))
df = df.withColumn("S5",df.S5.cast(FloatType()))
df = df.withColumn("S6",df.S6.cast(FloatType()))
df = df.withColumn("Y",df.Y.cast(FloatType()))

# COMMAND ----------

# MAGIC %md # Write 2 GOLD

# COMMAND ----------

df.printSchema()

# COMMAND ----------

gold_file = esml_lake.gold
#df_all.write.mode("overwrite").parquet(gold_file) # The real thing to do...but we dont want duplicates, hence we simulate...just read 1 dataset
df.write.mode("overwrite").parquet(gold_file)
