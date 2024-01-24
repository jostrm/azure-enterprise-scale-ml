# Databricks notebook source
import pathlib

# COMMAND ----------

#model_folder_name = '/11_diabetes_model_reg'
#datasets = {"ds01_diabetes","ds02_other"}

#active_in_train = "2021/01/01"
#active_in_scoring = "2021/01/01"
#active_model_version = "1"

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
  
  _train_gold_train = None
  _train_gold_validate = None
  _train_gold_test = None
  _model_alias = None
  
  _gold_2_score = None
  _gold_scored = None
  _gold_scored_runinfo = None
      
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
    else:
      return self._inf_in
    
  @property
  def bronze(self):
    if(self._esml_inference_mode == False):
      return self._train_out_bronze
    else:
      return self._inf_out_bronze
    
  @property
  def silver(self):
    if(self._esml_inference_mode == False):
      return self._train_out_silver
    else:
      return self._inf_out_silver
    
  @property
  def gold(self):
    if(self._esml_inference_mode == False):
      return self._train_gold
    else:
      return self._gold_2_score
  
  #TRAINING
  @property
  def gold_train(self):
      return self._train_gold_train
  @property
  def gold_validate(self):
      return self._train_gold_validate
  @property
  def gold_test(self):
      return self._train_gold_test
  @property
  def gold_train_dataset_name(self):
      return self._model_alias + '_GOLD_TRAIN'
  @property
  def gold_test_dataset_name(self):
      return self._model_alias + '_GOLD_TEST'
  @property
  def gold_validate_dataset_name(self):
      return self._model_alias + '_GOLD_VALIDATE'
  
  #SCORING
  @property
  def gold_2_score(self):
      return self._gold_2_score
  @property
  def gold_2_score_dataset_name(self):
      return self._model_alias + '_GOLD_TO_SCORE'

  @property
  def gold_scored(self):
      return self._gold_scored
  @property
  def gold_scored_dataset_name(self):
      return self._model_alias + '_GOLD_SCORED'

  @property
  def gold_scored_runinfo(self):
      return self._gold_scored_runinfo
  @property
  def gold_scored_runinfo_dataset_name(self):
      return self._model_alias + '_GOLD_SCORED_RUNINFO'
    
  def __init__(self, lake_version="1.3"):
    resource_group, workspace_name, mount_master, mount_project,physical_master,physical_project = getProjectEnvironment(azure_rg_project_number)
    self.mount_project = mount_project
    self.lake_version = lake_version
      
  def init_esml_lake_design(self,azure_rg_project_number="02",model_folder_name='/11_diabetes_model_reg', model_alias='M01', model_version=0, date_folder=None, run_id = None):
    self.esml_train = self.mount_project+model_folder_name+ "/train"
    self.esml_inference = self.mount_project+model_folder_name+ "/inference"

    self._train_gold = self.esml_train +"/gold/" +esml_env+ "/" + "gold_dbx.parquet"
    self._train_gold_train = self.esml_train +"/gold/" +esml_env+ "/Train/" + "gold_train_dbx.parquet"
    self._train_gold_validate = self.esml_train +"/gold/" +esml_env+ "/Validate/" + "gold_validate_dbx.parquet"
    self._train_gold_test = self.esml_train +"/gold/" +esml_env+ "/Test/" + "gold_test_dbx.parquet"
    self._model_alias = model_alias
    model_version_str = str(model_version)
    
    if(run_id is not None):
        self._gold_scored = self.esml_inference +"/"+model_version_str +"/scored/" +esml_env+ "/" +run_id+"/" + "gold_scored_dbx.parquet" # TRAIN
        if(date_folder is not None):
            self._gold_2_score = self.esml_inference +"/"+model_version_str +"/gold/" +esml_env+ "/"+date_folder+"/"+run_id+ "/gold_to_score_dbx.parquet"  # TODO: silver_merged_2_gold "if inference"
    else: # Latest folder
        self._gold_2_score = self.esml_inference +"/"+model_version_str+ "/gold/" +esml_env+ "/1_latest/" + "gold_to_score_dbx.parquet"  # TODO: silver_merged_2_gold "if inference"
    
    if(date_folder is not None):
        self._gold_scored = self.esml_inference +"/"+model_version_str +"/scored/" +esml_env+ "/" +date_folder+"/" + "gold_scored.parquet"
    
    self._gold_scored_runinfo = self.esml_inference +"/active/gold_scored_runinfo"

    active_in_folder = self.esml_train +"/active/active_in_folder.json" # datefolder
    active_scoring_in_folder =  self.esml_inference +"/active/active_scoring_in_folder.json" # modelversion, datafolder

  def esml_generate_dataset_arrays(self,datasets,active_in_train="2021/01/01",active_in_scoring="2021/01/01",active_model_version="1"):
    # TRAIN
    self._datasets = datasets
    self._train_in = dict()
    self._train_out_bronze = dict()
    self._train_out_silver = dict()

    for ds in self._datasets:
      self._train_in[ds] = self.esml_train + "/"+ds+"/in/"+esml_env+ "/"+active_in_train+"/"
    for ds in self._datasets:
      self._train_out_bronze[ds] = self.esml_train + "/"+ds+"/out/bronze/"+esml_env+ "/" + self.bronze_filename
    for ds in self._datasets:
      self._train_out_silver[ds] = self.esml_train + "/"+ds+"/out/silver/"+esml_env+ "/" + self.silver_filename

    # INFERENCE
    self._inf_in = dict()
    self._inf_out_bronze = dict()
    self._inf_out_silver = dict()
    
    for ds in self._datasets:
      self._inf_in[ds] = self.esml_inference +"/"+active_model_version+"/"+ds+"/in/"+esml_env+ "/"+active_in_train+"/"
    for ds in self._datasets:
      self._inf_out_bronze[ds] = self.esml_inference +"/"+active_model_version+ "/"+ds+"/out/bronze/"+esml_env+ "/" + self.bronze_filename
    for ds in self._datasets:
      self._inf_out_silver[ds] = self.esml_inference +"/"+active_model_version+ "/"+ds+"/out/silver/"+esml_env+ "/" + self.silver_filename
    
  def get_physical_path(self,physical_project_path,mount_dataset_path, file_suffix='*.parquet'):
    p = pathlib.Path(mount_dataset_path)
    p.parts[3:]
    physical_p = physical_project_path + '/' + str(pathlib.Path(*p.parts[3:]))
    physical_rel = physical_p[physical_p.index('.net')+4:] +'/'
    physical_rel_full = physical_rel + file_suffix
    return physical_rel_full

  def get_physical_start(self,physical_project_path):
    physical_p = physical_project_path
    physical_rel = physical_p[physical_p.index('.net')+4:] +'/'
    return physical_rel
