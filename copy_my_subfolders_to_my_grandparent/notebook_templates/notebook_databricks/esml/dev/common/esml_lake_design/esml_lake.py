# Databricks notebook source
model_folder_name = '/11_diabetes_model_reg'
datasets = {"ds01_diabetes","ds02_other"}

active_in_train = "2021/01/01"
active_in_scoring = "2021/01/01"
active_model_version = "1"

# COMMAND ----------

class ESMLLake(object):
  esml_train = None
  esml_inference = None
  mount_project = None
  _esml_inference_mode = False
  
  lake_version = "1.3"
  bronze_filename = "bronze_dbx.parquet"
  silver_filename = "silver_dbx.parquet"
  
  _datasets = None
  _train_in = dict()
  _train_out_bronze = dict()
  _train_out_silver = dict()
  _train_gold = None
  
  _train_gold_test = None
  _train_gold_validate = None
  _train_gold_test = None
  
  @property
  def inference_mode(self):
    return self._esml_inference_mode
  @inference_mode.setter
  def inference_mode(self, esml_inference_mode_bool):
    self._esml_inference_mode = esml_inference_mode_bool
  
  @property
  def datasets(self):
    return self._datasets
  
  @property
  def in_data(self):
    if(self._esml_inference_mode == False):
      return self._train_in
    
  @property
  def bronze(self):
    if(self._esml_inference_mode == False):
      return self._train_out_bronze
    
  @property
  def silver(self):
    if(self._esml_inference_mode == False):
      return self._train_out_silver
    
  @property
  def gold(self):
    if(self._esml_inference_mode == False):
      return self._train_gold
  
  @property
  def gold_train(self):
      return self._train_gold_train
  @property
  def gold_validate(self):
      return self._train_gold_validate
  @property
  def gold_test(self):
      return self._train_gold_test
    
  def __init__(self, lake_version="1.3"):
    resource_group, workspace_name, mount_master, mount_project,physical_master,physical_project = getProjectEnvironment(azure_rg_project_number)
    self.mount_project = mount_project
    self.lake_version = lake_version
      
  def init_esml_lake_design(self,azure_rg_project_number="02",model_folder_name='/11_diabetes_model_reg'):

    self.esml_train = self.mount_project+model_folder_name+ "/train"
    self.esml_inference = self.mount_project+model_folder_name+ "/inference"


    self._train_gold = self.esml_train +"/gold/" +esml_env+ "/" + "gold_dbx.parquet"
    self._train_gold_train = self.esml_train +"/gold/" +esml_env+ "/Train/" + "gold_train_dbx.parquet"
    self._train_gold_validate = self.esml_train +"/gold/" +esml_env+ "/Validate/" + "gold_validate_dbx.parquet"
    self._train_gold_test = self.esml_train +"/gold/" +esml_env+ "/Test/" + "gold_test_dbx.parquet"

    active_in_folder = self.esml_train +"/active/active_in_folder.json" # datefolder
    active_scoring_in_folder =  self.esml_inference +"/active/active_scoring_in_folder.json" # modelversion, datafolder

  def esml_generate_dataset_arrays(self,datasets,active_in_train="2021/01/01",active_in_scoring="2021/01/01",active_model_version="1"):
    # TRAIN
    self._datasets = datasets
    self._train_in = dict()
    self._train_out_bronze = dict()
    self._train_out_silver = dict()

    #print("In")

    for ds in self._datasets:
      self._train_in[ds] = self.esml_train + "/"+ds+"/in/"+esml_env+ "/"+active_in_train+"/"
      #print (train_in[ds])

    #print("Bronze")

    for ds in self._datasets:
      self._train_out_bronze[ds] = self.esml_train + "/"+ds+"/out/bronze/"+esml_env+ "/" + self.bronze_filename
      #print (train_out_bronze[ds])

    #print("Silver")

    for ds in self._datasets:
      self._train_out_silver[ds] = self.esml_train + "/"+ds+"/out/silver/"+esml_env+ "/" + self.silver_filename
      #print (train_out_silver[ds])

    #print("Gold (merge all silver)")
    #print(self.gold)

    # INFERENCE
    #inference_in = dict()
    #inference_out_bronze = dict()
    #inference_out_silver = dict()
