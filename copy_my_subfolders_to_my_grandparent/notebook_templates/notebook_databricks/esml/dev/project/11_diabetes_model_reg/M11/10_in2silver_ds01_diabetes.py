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
esml_dataset_filename_ending = "*.csv" # *.parquet | *.csv | *.delta | ds01_diabetes.parquet

try:
  dbutils.widgets.text("esml_training_folder_date","1000-01-01 10:35:01.243860", "UTC date")
  esml_date_folder_utc = dbutils.widgets.get("esml_training_folder_date")
  esml_date_folder_utc = getArgument("esml_training_folder_date")
  print ("esml_folder_date",esml_date_folder_utc)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_model_version","0", "Model version: 0=best model-auto")
  esml_model_version = dbutils.widgets.get("esml_inference_model_version")
  esml_model_version = getArgument("esml_inference_model_version")
  print ("esml_model_version",esml_model_version)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_inference_mode","0", "esml_inference_mode:[0,1] 0 if training")
  esml_inference_mode = dbutils.widgets.get("esml_inference_mode")
  esml_inference_mode = getArgument("esml_inference_mode")
  print ("esml_inference_mode:",esml_inference_mode)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_environment_dev_test_prod","dev", "esml environment:dev,test,prod")
  esml_env = dbutils.widgets.get("esml_environment_dev_test_prod")
  esml_env = getArgument("esml_environment_dev_test_prod")
  print ("esml_environment_dev_test_prod:",esml_env)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_dataset_name","ds01_diabetes", "ESML dataset")
  esml_dataset_names_in = dbutils.widgets.get("esml_dataset_name")
  esml_dataset_names_in = getArgument("esml_dataset_name")
  print ("esml_dataset_name:",esml_dataset_names_in)
except Exception as e:
  print(e)
  
try:
  dbutils.widgets.text("esml_dataset_filename_ending","*.parquet", "file extension")
  esml_dataset_filename_ending = dbutils.widgets.get("esml_dataset_filename_ending")
  esml_dataset_filename_ending = getArgument("esml_dataset_filename_ending")
  print ("esml_dataset_filename_ending:",esml_dataset_filename_ending)
except Exception as e:
  print(e)

# COMMAND ----------

#projectNumber = "002" # 002 or 02 depends on your lake design
#esml_lake = dbutils.notebook.run("/esml/dev/project/11_diabetes_model_reg/00_model_settings/01_dataset_paths",600, {"date_folder": date_folder})

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
  
print(esml_parameters.esml_date_folder)

# COMMAND ----------

if(len(esml_parameters.esml_dataset_names)>1):
  raise Exception("IN_2_SILVER notebooks should only work with 1 dataset at the time. use SILVER_MERGED_2_GOLD notebook to join/union stuff.")

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

# MAGIC %md
# MAGIC ## READ - IN-folder (.csv)

# COMMAND ----------

ds_name = esml_parameters.esml_dataset_names[0] # It should only be 1 dataset name passed..but it is possible to pass many.
print("ds_name:",ds_name)

# COMMAND ----------

try:
  ending = esml_parameters.esml_dataset_filename_ending.replace("*","diabetes")
  test_file =  esml_lake.in_data[ds_name] + ending # dataset_filename_ending
  dbutils.fs.ls(test_file) # File exists
except:
  print("Not that important to do this file check..only for demo")
finally:
  test_file =  esml_lake.in_data[ds_name]
  df = (spark.read.option("header","true").csv(test_file)) # Spark DF

# COMMAND ----------

# MAGIC %md ### WRITE - OUT/BRONZE -> Feature engineering -> Write OUT/SILVER

# COMMAND ----------

from pyspark.sql.types import IntegerType,BooleanType,FloatType,DateType

# In -> Bronze
bronze_file = esml_lake.bronze[ds_name]
silver_file = esml_lake.silver[ds_name]
df.write.mode("overwrite").parquet(bronze_file) 

# Bronze -> Silver

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

df.write.mode("overwrite").parquet(silver_file)

# COMMAND ----------

# READ 1st SILVER dataset
df_silver_file =  esml_lake.silver[ds_name]
df2_silver = spark.read.parquet(df_silver_file)

# COMMAND ----------

df2_silver.printSchema()
