# Databricks notebook source
import os
import sys
import numpy as np
import pandas as pd
import argparse
import datetime
import pickle
from pathlib import Path

# COMMAND ----------

import azureml.core
from azureml.core.dataset import Dataset
from azureml.core import Workspace
from azureml.core import Experiment
from azureml.core import Datastore
from azureml.core.model import Model
from azureml.core import Run

# COMMAND ----------

from pipelines.M11.esmlrt.interfaces.iESMLController import IESMLController
from pipelines.M11.esmlrt.runtime.ESMLController import ESMLController

# COMMAND ----------

from pyspark.sql import SparkSession

# COMMAND ----------

class ESMLParameters(object):
  _esml_date_folder = None
  _esml_datetime_folder = None
  _esml_model_version = None
  _esml_inference_mode = None
  _esml_env = None
  _esml_dataset_names = None
  _esml_dataset_filename_ending = None
  # Split, Train
  _esml_split_percentage = None
  _esml_target_column_name = None
  _esml_aml_model_name = None
  _esml_model_name_pkl = None
  _esml_dbfs_model_path = None
  
  def __init__(self,esml_inference_mode,esml_env,esml_dataset_filename_ending,dbfs_model_path,
              esml_dataset_names=None, esml_date_folder=None,esml_datetime_folder=None, esml_model_version = 0, esml_split_percentage=None,esml_target_column_name=None,esml_aml_model_name=None,esml_model_name_pkl=None):
    
    self._esml_date_folder = esml_date_folder
    self._esml_datetime_folder = esml_datetime_folder
    self._esml_model_version = esml_model_version
    self._esml_inference_mode = esml_inference_mode
    self._esml_env = esml_env
    self._esml_dataset_names = esml_dataset_names
    self._esml_dataset_filename_ending = esml_dataset_filename_ending
    
    self._esml_split_percentage = esml_split_percentage
    self._esml_target_column_name = esml_target_column_name
    self._esml_aml_model_name = esml_aml_model_name
    self._esml_model_name_pkl = esml_model_name_pkl
    self._esml_dbfs_model_path = dbfs_model_path
    
  @property
  def esml_dbfs_model_path(self):
    return self._esml_dbfs_model_path
  @property
  def esml_aml_model_name(self):
    return self._esml_aml_model_name
  @property
  def esml_model_name_pkl(self):
    return self._esml_model_name_pkl
  @property
  def esml_datetime_folder(self):
    return self._esml_datetime_folder
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

class ESMLInferencer(object):
    _esml_project_no = None
    _esml_parameters = None
    _esml_output_lake_template = "projects/project{esml_project_no}/{model_folder_name}/inference/{model_version}/scored/dev/{date_folder}/{id_folder}/"
    _esml_output_lake_latest_template = "/mnt/prj{esml_project_no}/{model_folder_name}/inference/0/scored/dev/"
    #_esml_output_lake_latest_template = "projects/project{esml_project_no}/{model_folder_name}/inference/0/scored/dev/{id_folder}/"
    
    _current_aml_model = None
    _current_aml_model_train_run_id = None
    _current_model_from_pkl = None

    _path_output_scored_gold_dbx = None
    _path_output_scored_gold_dbx_runid = None
    _path_output_scored_gold_pd = None
    _path_output_scored_gold_pd_runid = None
    _path_historic_path = None
    _path_latest = None
    _remote_run_id = None

    # CONSTRUCTOR
    def __init__(self, aml_workspace, esml_project_no, esml_parameters, esml_output_lake_template=None):
        self._aml_workspace = aml_workspace
        self._esml_project_no = esml_project_no
        self._esml_parameters = esml_parameters

        if(esml_output_lake_template is not None):
            self._esml_output_lake_template = esml_output_lake_template

    def init_aml_model(self,lake_gold_scored, remote_run=None):
        if(remote_run is not None):
            self._remote_run_id = remote_run.id
        run_id = self.get_aml_model(remote_run)
        self.get_save_paths(lake_gold_scored,run_id)
        return self._current_aml_model, run_id

    @property
    def esml_parameters(self):
        return self._esml_parameters
    @property
    def aml_workspace(self):
        return self._aml_workspace
    @property
    def path_historic_scored(self):
        return self._path_historic_path
    @property
    def current_aml_model(self):
        return self._current_aml_model
    @property
    def current_aml_model_train_run_id(self):
        return self._current_aml_model_train_run_id
    @property
    def current_model_from_pkl(self):
        return self._current_model_from_pkl

    # PUBLIC Method
    def load_model(self,train_aml_model):
        model_output_folder='/tmp/model/'
        model_path_local =  model_output_folder +self.esml_parameters.esml_model_name_pkl
        num_files=train_aml_model.download(model_output_folder, exist_ok=True)
        try:
            with open(model_path_local, "rb" ) as f:   
                self._current_model_from_pkl = pickle.load(f)
        except Exception as e:
            print(e)
            print("Manual training: Cannot load Model with name {}".format(model_path_local))
        return self._current_model_from_pkl
    
    # PUBLIC Method
    def get_gold_to_score(self, gold_2_score):
        gold_to_score_df = None
        gold_to_score_df = spark.read.parquet(gold_2_score) # TODO: "1_latest" folder in lake?
        return gold_to_score_df

    def inference_model(self, pandas_df):
        data = pandas_df #.reset_index(drop=True) # Make sure index is gone
        if (isinstance(data, pd.DataFrame) == False):
          data = data.toPandas()
        data = data.reset_index(drop=True)
        
        drop_list = [self._esml_parameters.esml_target_column_name]
        thisFilter = data.filter(drop_list)
        data.drop(thisFilter, inplace=True, axis=1)

        result = model.predict(data)

        list_of_columns = data.columns

        # predict_proba START: Supports both regression and classification - hence we need to check for .predict_proba existing (classification)
        has_predict_proba = False
        if model is not None and hasattr(model, 'predict_proba') \
                and model.predict_proba is not None and data is not None:
            try: # ADD predict_proba - IF model supports this....need to handle that case
                probability_y = model.predict_proba(data)
                has_predict_proba = True
            except Exception as ex:
                raise ValueError("Model does not support predict_proba method for given dataset \
                    type, inner error: {}".format(ex.message))
        # predict_proba END

        # Format result to a dataframe, join SCORING with its FEATURES
        df_res  = pd.DataFrame(result, columns=['prediction'])
        df_out = gold_to_score_df.toPandas().join(df_res[['prediction']],how = 'left')

        if (has_predict_proba):
            if(has_iloc(probability_y)):
                df_out['predict_proba_0']  = probability_y.iloc[:,0]
                df_out['predict_proba_1']  = probability_y.iloc[:,1]
            else:
                df_out['predict_proba_0']  = probability_y[:,0]
                df_out['predict_proba_1']  = probability_y[:,1]
        return df_out

    # PUBLIC Method
    def get_aml_model(self,remote_run=None):
        experiment_name_search = self._esml_parameters.esml_aml_model_name
        run_id = None
        model = None
        train_aml_model = None

        if(remote_run is not None): # TODO: Wrap in ESML function
            run_id = remote_run.id
            ws = self._aml_workspace
            training_experimet_name = ""
            if(int(self._esml_parameters.esml_model_version) == 0): # Let ESML fetch BEST model, based on your model_settings.json definition
                print("Fetching BEST MODEL (esml_model_version == 0) that is promoted. To get its name")
                train_aml_model,train_run_id, model_name = IESMLController.get_best_model_via_modeltags_only_DevTestProd(ws,experiment_name_search)
                #print("Current_model.name", train_aml_model.name)
                #print("model_name: ", model_name)
                #print("Run ID tag: Training run: ",train_run_id)
            else: # use specific model version
                print("Fetching MODEL with specific version")
                print(self._esml_parameters.esml_model_version)
                print(type(self._esml_parameters.esml_model_version))
                train_aml_model = Model(ws, name=self._esml_parameters.esml_aml_model_name, version=self._esml_parameters.esml_model_version)
            
            train_run_id = train_aml_model.tags.get("run_id") # If DBX parent run is TAGGED

            training_experimet_name = train_aml_model.experiment_name
            training_run_id_from_model = train_aml_model.run_id
            if (training_experimet_name is None or len(training_experimet_name) < 3):
                print("train_aml_model.experiment_name is None, not fetching training experiment name from Model.tags:")
                training_experimet_name = train_aml_model.tags.get("experiment_name ") # If DBX parent run is TAGGED
            print("Run ID tag: Training run: ",train_run_id)
            print("Run ID from Model.run_id ",training_run_id_from_model)
            print("Run Experiment_name: Training runs experiment name: ",training_experimet_name) # 11_diabetes_model_reg_pipe_IN_2_GOLD_TRAIN_DBX | run.id = 6fd86ddc-beb4-4ef6-94ad-dc71875c386f
            
            if(train_run_id is not None):
                print("Load Model: train_run_id from Model is: {}".format(train_run_id))
                safe_run_id = IESMLController.get_safe_automl_parent_run_id(train_run_id)
                print("Load Model: safe_run_id from Model is: {}".format(safe_run_id))

                
                print("Load Model - Training experiment: remote_run.experiment.name is: {}".format(training_experimet_name))
                print("Load Model: train_aml_model.name is: {} and version {}".format(train_aml_model.name, train_aml_model.version))
                print("Load Model: esml_model_version IN is: {}".format(self._esml_parameters.esml_model_version))

                train_run,best_run,fitted_model = IESMLController.init_run(ws,training_experimet_name, safe_run_id,train_aml_model)
                model = fitted_model
                #print("Fitted Model loading success. Model: {} version {}".format(train_aml_model.name,train_aml_model.version))
            else:
                print("Warning! train_run_id from Model is None")
                
        else:
            train_aml_model = Model(self._aml_workspace, name=self._esml_parameters.esml_aml_model_name, version=self._esml_parameters.esml_model_version)
            train_run_id = train_aml_model.tags.get("run_id") # If DBX parent run is TAGGED
            print("Run ID tag: Training run: ",train_run_id)
        
        self._current_aml_model = train_aml_model
        self._current_aml_model_train_run_id = train_run_id
        self._current_model_from_pkl = model
        return run_id

    # PRIVATE method - GENERATE PATHS
    def get_save_paths(self,esml_lake_gold_scored_path, run_id = None):

        esml_output_lake_template_internal = self._esml_output_lake_template
        output_scored_gold_pd = esml_lake_gold_scored_path
        output_scored_gold_dbx = None

        output_scored_gold_dbx_runid = None
        output_scored_gold_pd_runid = None
        if(run_id is not None):
            output_scored_gold_dbx_runid = esml_lake_gold_scored_path.replace("gold_scored.parquet", run_id+"/gold_scored_dbx.parquet")
            output_scored_gold_pd_runid = esml_lake_gold_scored_path.replace("gold_scored.parquet", run_id+"/gold_scored.parquet")
            run_id_str_dbx = run_id+"/gold_scored_dbx.parquet"
            run_id_str = run_id+"/gold_scored.parquet"
        else:
            output_scored_gold_dbx = esml_lake_gold_scored_path.replace(".parquet", "_dbx.parquet")
            run_id_str_dbx = "gold_scored_dbx.parquet"
            run_id_str = "gold_scored.parquet"

        historic_path = esml_output_lake_template_internal.format(
            esml_project_no = self._esml_project_no,
            model_folder_name = esml_parameters.esml_aml_model_name, # model_folder_name
            model_version = esml_parameters.esml_model_version,
            esml_env = esml_parameters.esml_env,
            date_folder = esml_parameters.esml_date_folder,
            id_folder= run_id_str)

        self._path_latest = self._esml_output_lake_latest_template.format(
            esml_project_no = self._esml_project_no,
            model_folder_name = esml_parameters.esml_aml_model_name, # model_folder_name
            model_version = "0",
            esml_env = esml_parameters.esml_env)

        self._path_output_scored_gold_dbx = output_scored_gold_dbx
        self._path_output_scored_gold_dbx_runid = output_scored_gold_dbx_runid
        self._path_output_scored_gold_pd = output_scored_gold_pd
        self._path_output_scored_gold_pd_runid = output_scored_gold_pd_runid
        self._path_historic_path = historic_path
        
        return output_scored_gold_dbx,output_scored_gold_dbx_runid,output_scored_gold_pd,output_scored_gold_pd_runid,historic_path

    def create_folder_if_not_exist(self,path):
        output_file = Path(path)
        output_dir = output_file.parent
        output_dir.mkdir(parents=True, exist_ok=True)

    # PRIVATE method
    def save_as_pd_parquet(self,pandas_df):
        if not (self._path_output_scored_gold_pd is None):
            p1 = '/dbfs'+self._path_output_scored_gold_pd
            print("p1:{}".format(p1))
            self.create_folder_if_not_exist(p1)
            written_df = pandas_df.to_parquet(p1,engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            print("Saved prediction to GOLD_SCORED dataset (from PANDAS - LOCAL)")

        if(self._path_output_scored_gold_pd_runid is not None):
            p1 = '/dbfs'+self._path_output_scored_gold_pd_runid
            self.create_folder_if_not_exist(p1)
            written_df = pandas_df.to_parquet(p1,engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            print("Saved prediction to GOLD_SCORED dataset (from PANDAS - HISTORIC)")

        # LATEST
        run_id_str = "gold_scored.parquet"
        p2 = '/dbfs'+self._path_latest + run_id_str
        print("p2:{}".format(p2))
        self.create_folder_if_not_exist(p2)
        written_df = pandas_df.to_parquet(p2,engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
        print("Saved prediction to GOLD_SCORED dataset (from PANDAS - LATEST)")

    # PRIVATE method
    def save_as_pyspark_parquet(self,pandas_df):
        spark = SparkSession.builder.appName("pandas to spark").getOrCreate()
        df_dbx = spark.createDataFrame(pandas_df)

        if not (self._path_output_scored_gold_dbx is None):
            print("Saving prediction to GOLD_SCORED dataset (from PYSPARK DF - LOCAL)")
            self.create_folder_if_not_exist(self._path_output_scored_gold_dbx)
            df_dbx.write.mode("overwrite").parquet(self._path_output_scored_gold_dbx)

        if not (self._path_output_scored_gold_dbx_runid is None):
            print("Saving prediction to GOLD_SCORED dataset (from PYSPARK DF - HISTORIC)")
            self.create_folder_if_not_exist(self._path_output_scored_gold_dbx_runid)
            df_dbx.write.mode("overwrite").parquet(self._path_output_scored_gold_dbx_runid)

        run_id_str_dbx = "gold_scored_dbx.parquet"
        print("Saving prediction to GOLD_SCORED dataset (from PYSPARK DF - LATEST)")
        path1 = self._path_latest + run_id_str_dbx
        self.create_folder_if_not_exist(path1)
        df_dbx.write.mode("overwrite").parquet(path1)

    # PUBLIC method
    def save_results(self,pandas_df,res_as_pandas_df=True,res_as_pyspark_df=False, run_id=None):
        if((res_as_pandas_df == False) and (res_as_pyspark_df == False)):
            raise Exception("No save will be done, since both result dataframe formates are False. (pandas_df == False and pyspark_df == False)")

        if (res_as_pandas_df):
            self.save_as_pd_parquet(pandas_df)
        if (res_as_pyspark_df):
            self.save_as_pyspark_parquet(pandas_df)

        self.save_meta_data(run_id)
        #if(self._remote_run_id is not None):
        #    self.save_meta_data(self._remote_run_id)
        #elif(run_id is not None):
        #    self.save_meta_data(run_id)
        #else:
        #    self.save_meta_data(None)

    # PRIVATE method
    def save_meta_data(self,run_id=None):
        last_gold_run_filename = "last_gold_run.csv"
        last_gold_run_physical_template = "projects/project{esml_project_no}/{model_folder_name}/inference/active/gold_scored_runinfo"

        last_gold_run1 = "/dbfs/mnt/prj{esml_project_no}/{model_folder_name}/inference/active"
        last_gold_run2 = "/dbfs/mnt/prj{esml_project_no}/{model_folder_name}/inference/active/gold_scored_runinfo"
        last_gold_run1full = last_gold_run1.format(esml_project_no=self._esml_project_no,model_folder_name=self.esml_parameters.esml_aml_model_name) + "/"+last_gold_run_filename
        last_gold_run2full = last_gold_run2.format(esml_project_no=self._esml_project_no,model_folder_name=self.esml_parameters.esml_aml_model_name) + "/"+last_gold_run_filename
        last_gold_run_physical = last_gold_run_physical_template.format(esml_project_no=self._esml_project_no,model_folder_name=self.esml_parameters.esml_aml_model_name) + "/"+last_gold_run_filename

        # create the pandasd dataframe with meta, save to .csv for "Azure datafactory WriteBack pipeline/step" to use
        date_now_str = str(datetime.datetime.now())

        used_model_version_str = self.esml_parameters.esml_model_version
        run_id_a = "local_run_dbx"
        if(run_id is not None):
            run_id_a = run_id

        last_gold_run_data = [[run_id_a, self._path_historic_path,self.esml_parameters.esml_datetime_folder,date_now_str,self.esml_parameters.esml_model_version, used_model_version_str, self._current_aml_model.name]]
        df2 = pd.DataFrame(last_gold_run_data, columns = ['pipeline_run_id', 'scored_gold_path', 'date_in_parameter', 'date_at_pipeline_run','model_version','used_model_version','used_model_name'])

        print("Saving last_gold_run.csv at: {}".format(last_gold_run1full))
        written_df2 = df2.to_csv(last_gold_run1full, encoding='utf-8',index=False)
        #df2.coalesce(1).write.mode("overwrite").option("mapreduce.fileoutputcommitter.marksuccessfuljobs","false").option("header","true").option("quote","\u0000").csv(last_gold_run1full)

        print("Saving last_gold_run.csv at: {}".format(last_gold_run2full))
        written_df3 = df2.to_csv(last_gold_run2full, encoding='utf-8',index=False)
        #df5.coalesce(1).write.mode("overwrite").option("mapreduce.fileoutputcommitter.marksuccessfuljobs","false").option("header","true").option("quote","\u0000").csv(last_gold_run2full)
        print("Pipeline ID (Steps runcontext.parent.id) {}".format(run_id))
        
        self.register_meta_as_aml_dataset(last_gold_run_physical)

    # PRIVATE method
    def register_meta_as_aml_dataset(self,last_gold_run_physical):
        try:
            datastore = self._aml_workspace.get_default_datastore()
            dataset_meta = Dataset.Tabular.from_delimited_files(path = [(datastore, last_gold_run_physical)])
            
            train_dataset = dataset_meta.register(workspace = self._aml_workspace,
                name = esml_lake.gold_scored_runinfo_dataset_name,
                description = 'GOLD_SCORED_RUNINFO dataset registered from Azure Databricks',
                create_new_version=True)
        except Exception as e:
            print("Warning: Could not register new version of GOLD_SCORED_RUNINFO, but data is written to latest version anyways.")
        

