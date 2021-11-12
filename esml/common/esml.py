"""
Copyright (C) Microsoft Corporation. All rights reserved.​
 ​
Microsoft Corporation (“Microsoft”) grants you a nonexclusive, perpetual,
royalty-free right to use, copy, and modify the software code provided by us
("Software Code"). You may not sublicense the Software Code or any use of it
(except to your affiliates and to vendors to perform work on your behalf)
through distribution, network access, service agreement, lease, rental, or
otherwise. This license does not purport to express any claim of ownership over
data you may have shared with Microsoft in the creation of the Software Code.
Unless applicable law gives you more rights, Microsoft reserves all other
rights not expressly granted herein, whether by implication, estoppel or
otherwise. ​
 ​
THE SOFTWARE CODE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
MICROSOFT OR ITS LICENSORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THE SOFTWARE CODE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""
from ctypes import ArgumentError
import json
import sys
import os
import math
from azureml.core.dataset import Dataset 
from azureml.core import Workspace
from azureml.core.model import Model
from azureml.exceptions import UserErrorException
from azureml.exceptions import ProjectSystemException
from storage_factory import LakeAccess
from baselayer_ml import split_stratified
from baselayer_azure_ml import ComputeFactory
from baselayer_azure_ml import AutoMLFactory
import pandas as pd
import numpy as np
import uuid
import datetime
import shutil
from collections import defaultdict
from azureml.core.authentication import ServicePrincipalAuthentication
import argparse
from azureml.train.automl.exceptions import NotFoundException
from azureml.core import Experiment
from azureml.train.automl.run import AutoMLRun
from pathlib import Path


class ESMLProject():
    ws = None
    datastore = None
    lake_config = None
    env_config = None
    _inference_mode = False
    _best_model = None
    
    _gold_dataset = None
    _gold_train = None
    _gold_validate = None
    _gold_test = None
    _gold_scored = None
    _gold_to_score = None
    dataset_inference_suffix = "_TO_SCORE"
        
    project_folder_name = "project"
    model_folder_name = "kalle"
    dataset_folder_names = None
    dataset_list = []
    models_array = []
    active_model_config = None
    _proj_start_path = "projects" # = v4  (v3= master/1_projects )
    _project_train_path = _proj_start_path+"/{}/{}/train/"
    _project_inference_path = _proj_start_path+"/{}/{}/inference/"

    _train_gold_path = _proj_start_path+"/{}/{}/train/gold/{}/"
    _inference_gold_path = _proj_start_path+"/{}/{}/inference/{}/gold/{}/"
    _inference_scored_path = _proj_start_path+"/{}/{}/inference/{}/scored/{}/" # TODO: Scoring after batch
    _projectNoXXX="000"
    _projectNoXX="00"
    _project_number_XX_or_XXX = 3
    projectNumber=0
    _modelNumber=0
    _modelNrString = "00"
    _projectNoString ="00"
    inferenceModelVersion = 0
    _in_folder_date = "2020/01/01"
    _in_scoring_folder_date = "2020/01/01"
    date_scoring_folder = None # Datetime
    _rndPhase = False
    _dev_test_prod = "dev"
    _suppress_logging = True
    _verbose_logging = False
    #_in_folder_date_string='2000-01-01 15:35:01.243860'

    tenant = ""
    dev_subscription = ""
    test_subscription = ""
    prod_subscription = ""
    _subscriptionId = "" # Active
    lake_name = ""
    lake_design_version = 3
    common_rg_name = ""
    common_vnet_name = ""
    common_subnet_name = ""
    active_common_subnet_name = ""
    use_aml_cluster_to_build_images = False
    resource_group = ""
    workspace_name = ""
    location = ""
    security_config = None
    lake_access = None # Singelton
    _recreate_datastore = False
    override_enterprise_settings_with_model_specific = False
    _compute_factory = None
    automl_factory = None
    demo_mode = True
    multi_output = None
    inference_use_top_version = True
    _cpu_gpu_databricks = "cpu" # gpu, databricks
    
    # , param_inference_model_version=None, param_scoring_folder_date=None,param_train_in_folder_date=None
    def __init__(self, dev_test_prod=None, param_inference_model_version=None, param_scoring_folder_date=None,param_train_in_folder_date=None):
        self.demo_mode = False # dont change this
        
        if(dev_test_prod is not None and ((param_train_in_folder_date is not None) or (param_scoring_folder_date is not None))): # Scenario 01: SCORING or RETRAINING pipeline
            if (dev_test_prod in ["dev","test","prod"]):
                self.ReloadConfiguration() # from config (config from LAKE -> JSONLINES)

                #1) Override JSONLINES & update date_time_folders
                self.update_json_files(dev_test_prod,param_inference_model_version,param_scoring_folder_date,param_train_in_folder_date) # A only update/override .jsonlines
                
                #3) set ENV and init Datasets
                self.initDatasets(self.inferenceModelVersion, self.project_folder_name,self.model_folder_name,self.dataset_folder_names) 
            else:
                raise Exception("dev_test_prod parameter, must be either [dev,test,prod]")    
        elif(dev_test_prod is not None): # Scenario 02: MLOps from Azure Devops "GIT checkin" scenario -> retrain with same "data" (same "date_folders" as datalake config.
            if (dev_test_prod in ["dev","test","prod"]):
                self.ReloadConfiguration() # from config
                self.dev_test_prod = dev_test_prod # overrides config
                self.initDatasets(self.inferenceModelVersion, self.project_folder_name,self.model_folder_name,self.dataset_folder_names)
            else:
                raise Exception("dev_test_prod parameter, must be either [dev,test,prod]")
        else: # Scenario 03: Manual - just load "as-is" in configuration
            self.ReloadConfiguration()
            self.initDatasets(self.inferenceModelVersion, self.project_folder_name,self.model_folder_name,self.dataset_folder_names)

        self.set_inference_mode_and_version(self.inferenceModelVersion) # Mode: Inference  (model_version>0) VS Training (model_version<0)

    # Mode: Inference  (model_version>0) VS Training (model_version<0) 
    def set_inference_mode_and_version(self,param_inference_model_version):
        if(param_inference_model_version is None):
            self.inference_mode = False
        else:
            self.inferenceModelVersion = int(param_inference_model_version)
            if (self.inferenceModelVersion <0):
                self.inference_mode = False
            elif(self.inferenceModelVersion == 0): # Use highest model_version
                self.inference_mode = True
                self.inference_use_top_version = True
            else: 
                self.inference_mode = True

    def project_int_to_string(self):
        self._projectNoXXX= '{0:03}'.format(self.projectNumber)
        self._projectNoXX= '{0:02}'.format(self.projectNumber)
        if (self._project_number_XX_or_XXX == 2):
            return self._projectNoXX
        else:
            return self._projectNoXXX

    def model_int_to_string(self):
        return '{0:02}'.format(self._modelNumber)

    def projectNumberToFoldername(self,projectNumber):
        if(projectNumber is not None):
            self.projectNumber = projectNumber
            self._projectNoXXX= '{0:03}'.format(self.projectNumber)
            self._projectNoXX= '{0:02}'.format(projectNumber)
            self.project_folder_name = "project"+self._projectNoXXX

    def describe(self):
        if(self.inferenceModelVersion>0):
            print("Inference version: {}".format(self.inferenceModelVersion))
        else:
            print("Training")

        for d in self.Datasets:
            print("\n - " +d.Name)
            print(d.InPath)
            print(d.BronzePath)
            print(d.SilverPath)
            #print(d.InPath_Scoring)

        print(" \n")
        print("Training GOLD (p.GoldPath)")
        print(self.GoldPath)
        print(" \n")
        
        to_score_folder, scored_folder, date_folder = self.get_gold_scored_unique_path()
        print("[A) USAGE]: to_score_folder, scored_folder, date_folder = p.get_gold_scored_unique_path()")

        print("A)INFERENCE ONLINE: GOLD to score (example if realtime - today)")
        print(to_score_folder)
        print(" \n")
        print("A)INFERENCE ONLINE: GOLD scored (example if realtime today)")
        print(scored_folder)
        print(" \n")

        print("[B) USAGE]: to_score_folder_batch, scored_folder, date_folder = p.get_gold_scored_unique_path(p.date_scoring_folder)")
        to_score_folder_batch, scored_folder, date_folder = self.get_gold_scored_unique_path(self.date_scoring_folder)

        print("B)INFERENCE BATCH: GOLD to score (example batch, datetime from config)")
        print(to_score_folder_batch) # + self.date_scoring_folder.strftime('%Y_%m_%d') + '/')
        print(" \n")
        print("B)INFERENCE BATCH: GOLD scored (example batch, datetime from config)")
        print(scored_folder) 
        print(" \n")

        print("C) INFERENCE BATCH (SCENARIO 2): TODAY I scored data from X days AGO  (second datefolder from config - X days ago)")
        print(to_score_folder_batch + self.date_scoring_folder.strftime('%Y_%m_%d') + '/')
        print(scored_folder + self.date_scoring_folder.strftime('%Y_%m_%d') + '/')
         
        print(" \n") 
 
        print("ENVIRONMENT - DEV, TEST, or PROD?  [USAGE: p.dev_test_prod]")
        print("ACTIVE ENVIRONMENT = {}".format(self.dev_test_prod))
        print("ACTIVE subscription = {}".format(self.subscription_id))
        print("-",self.resource_group)
        print("-",self.workspace_name)
        
        print("-",self.location)
        print("-", self.common_rg_name)

        rg_name, vnet_name, subnet_name = self.vNetForActiveEnvironment()
        print("Active vNet:", vnet_name)
        print("Active SubNet:",subnet_name)
        print ("[USAGE] for the above: p.vNetForActiveEnvironment()")

        sa_name, rg_name, sub_id = self.getLakeForActiveEnvironment()
        print("Active Lake (storage account) ",sa_name)
        print ("[USAGE] for the above: p.getLakeForActiveEnvironment()")

        print("AML for docker:",self.use_aml_cluster_to_build_images)
        
    #Register - at Initiation, and when saving
    def create_dataset_names(self, datasetName):
        if(self.inference_mode):
            self._in_name_azure = self.ModelAlias +"_"+datasetName+"_inference_IN"
            self._bronze_name_azure = self.ModelAlias +"_"+datasetName+"_inference_BRONZE"
            self._silver_name_azure = self.ModelAlias +"_"+datasetName+"_inference_SILVER"
        else:
            self._in_name_azure = self.ModelAlias +"_"+datasetName+"_train_IN"
            self._bronze_name_azure = self.ModelAlias +"_"+datasetName+"_train_BRONZE"
            self._silver_name_azure = self.ModelAlias +"_"+datasetName+"_train_SILVER"

        return self._in_name_azure, self._bronze_name_azure, self._silver_name_azure
    
    def initDatasets(self, inferenceModelVersion,project_folder_name,model_folder_name, DatasetFolderNamesIn):  # **datasetNameKey_PathValue
        
        self.dataset_list = []
        for d in DatasetFolderNamesIn:
            ds = ESMLDataset(self,inferenceModelVersion,project_folder_name,model_folder_name,d)
            self.dataset_list.append(ds)
    
    def ReloadConfiguration(self):
        try:
            if(self._suppress_logging==False):
                print (os.getcwd()) # c:\Users\jostrm\OneDrive - Microsoft\0_GIT\2_My\MLOpsOldTemplate\DevOps-for-AI\esml

            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))

            user_settings = "../../"
            lake_settings_path = "{}../settings/project_specific/model/lake_settings.json".format(user_settings)

            with open(lake_settings_path) as f: # Project number:  "project002", Model prefix "M03", "03"
                self.parseConfig(json.load(f))
            with open("{}../settings/active_dev_test_prod.json".format(user_settings)) as f2: # Enterprise: MSFT-WEU-EAP_PROJECT{}_AI-{}-RG
                active_env =  json.load(f2)
            with open("{}../settings/enterprise_specific/dev_test_prod_settings.json".format(user_settings)) as f2: # Enterprise: MSFT-WEU-EAP_PROJECT{}_AI-{}-RG
                all_env = json.load(f2)
                all_env["active_dev_test_prod"] = active_env["active_dev_test_prod".format(user_settings)]
                self.parseEnvConfig(all_env)
            with open("{}../settings/project_specific/security_config.json".format(user_settings)) as f2: # Project service principles, etc
                self.security_config = json.load(f2)
                self.lake_name = self.security_config["lake_fs"]

            with open("{}../settings/project_specific/model/active/active_in_folder.json".format(user_settings)) as f2: # where to read data to train on
                json_date_in_folder = json.load(f2)
            with open("{}../settings/project_specific/model/active/active_scoring_in_folder.json".format(user_settings)) as f2: # where to read data to score
                json_date_scoring_folder = json.load(f2)

            self.parseDateFolderConfig(json_date_in_folder,json_date_scoring_folder)
             
        except Exception as e:
            raise Exception("ESML ReloadConfiguration - could not load SETTINGS from {} ".format(lake_settings_path)) from e
        finally:
            os.chdir(old_loc) # Switch back to callers "working dir"
            if(self._suppress_logging==False):
                print (os.getcwd())
    
    def save_active_env(self):
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            data = {
                "active_dev_test_prod": self.dev_test_prod
            }
            with open("../../../settings/active_dev_test_prod.json", "w") as f:
                json.dump(data, f)
        except Exception as e:
            raise ValueError("ESMLProject.save_active_env - could not write active_dev_test_prod.json") from e
        finally: 
            os.chdir(old_loc) # Change back working location...

    @property
    def active_model(self):
        return self.active_model_config

    @active_model.setter
    def active_model(self, active_model_id):
        self.set_active_model_config(active_model_id)
        self.initDatasets(self.inferenceModelVersion, self.project_folder_name,self.model_folder_name,self.dataset_folder_names)

    def set_active_model_config(self, active_model_id):
        if(type(active_model_id) is not int):
            print("Input error for method 'set_active_model_config'. Parameter 'active_model_id' must be an integer")

        hit = False
        for model in self.models_array:
            if (model["model_number"] == active_model_id):
                hit = True
                self.active_model_config = model
        
        if(hit == False):
            print("No model configuration in lake_settings.json with model integer ID {}".format(active_model_id))

        self._modelNumber = self.active_model_config['model_number']
        self._modelNrString = self.model_int_to_string()
        self.model_folder_name = self.active_model_config['model_folder_name'] #2_prod/1_projects/project005/00_titanic_model/train/ds01_titanic/out/bronze/
        self.dataset_folder_names = self.active_model_config['dataset_folder_names'] 
        self._model_short_alias = self.active_model_config['model_short_alias']

    def parseConfig(self, lake_config):
        self.lake_config = lake_config

        try: # new setup/format, with arrray
            print("Using lake_settings.json with ESML version 1.4 - Models array support including LABEL")
            self.models_array = []
            self.projectNumber = self.lake_config['project_number']
            self.project_folder_name = self.lake_config['project_folder_name']
            active_model_id = self.lake_config['active_model']
            self.active_model_config = None

            for item in lake_config["models"]:
                model_details = {"model_number":None, "model_folder_name":None,"model_short_alias":None,"dataset_folder_names":None, "label":None}
                model_details['model_number'] = int(item['model_number'])
                model_details['model_folder_name'] = item['model_folder_name']
                model_details['model_short_alias'] = item['model_short_alias']
                model_details['dataset_folder_names'] = item['dataset_folder_names']
                model_details['label'] = item['label']

                self.models_array.append(model_details)

            self.set_active_model_config(active_model_id) # ACTIVATE from config...which can be over-ridden by notebooks/pipelines/mlops

        except Exception as e: # old setup, no array
            print("ESML deprecated error. Using old lake_settings as fallback. Error: {}".format(e))
            print("Using lake_settings.json with ESML version 1.3")
            self.lake_config = lake_config
            self.projectNumber = self.lake_config['project_number']
            self.project_folder_name = self.lake_config['project_folder_name']
            
            self._modelNumber = self.lake_config['model_number']
            self._modelNrString = self.model_int_to_string()
            self.model_folder_name = self.lake_config['model_folder_name'] #2_prod/1_projects/project005/00_titanic_model/train/ds01_titanic/out/bronze/
            self.dataset_folder_names = self.lake_config['dataset_folder_names'] 
            self._model_short_alias = self.lake_config['model_short_alias']

            # add at least 1 NEW model info, programmatically
            model_1 = {"model_number":11, "model_folder_name":"11_diabetes_model_reg","model_short_alias":"M11","dataset_folder_names":["ds01_diabetes","ds02_other"], "label":"Y"}
            model_2 = {"model_number":10, "model_folder_name":"10_titanic_model_clas","model_short_alias":"M10","dataset_folder_names": ["ds01_titanic","ds02_haircolor","ds03_housing","ds04_lightsaber"], "label":"Survived"}
            model_3 = {"model_number":12, "model_folder_name":"12_car_price_regression","model_short_alias":"M12","dataset_folder_names":["ds01_vw","ds02_audi","ds03_bmw"], "label":"price"}
            self.models_array.append(model_1)
            self.models_array.append(model_2)
            self.models_array.append(model_3)

            self.set_active_model_config(10)

    def parseDateFolderConfig(self, date_in_folder, scoring):
        date_string = date_in_folder["{}_in_folder_date".format(self.dev_test_prod)] # String in DateTime format
        date_infolder = datetime.datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S.%f') # DateTime
        self._in_folder_date = date_infolder.strftime('%Y/%m/%d') #  String 2020/01/01

        date_str = scoring["{}_scoring_folder_date".format(self.dev_test_prod)] # String in DateTime format
        self.date_scoring_folder = datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S.%f') # DateTime
        self._in_scoring_folder_date = self.date_scoring_folder.strftime('%Y/%m/%d') #  String 2020/01/01
        self.inferenceModelVersion = int(scoring['{}_inference_model_version'.format(self.dev_test_prod)])

    def checkLakeCompatability(self):
        try:
            lake_paths = [(self.Lakestore, "active")]
            ds_train_json = Dataset.Tabular.from_json_lines_files(lake_paths, validate=False, include_path=False, set_column_types=None, partition_format=None, invalid_lines='error', encoding='utf8')
            
            try:
                df = ds_train_json.to_pandas_dataframe()
            except Exception as e1:
                print("Error: checkLakeCompatability, lake_paths: " + lake_paths)
                print("Error: checkLakeCompatability, to_pandas_dataframe() failed, from JSON: " + ds_train_json)
                raise e1

            df_version = df.iloc[0]["lake_design_version"]
            df_name = df.iloc[0]["lake_name"]

            if (df_version!= self.lake_design_version): 
                print("ESML WARNING - Possible incompatible datalake design:"\
                    "lake_design_version={} in ESML SDK, but lake_design_version={} in storage account, at 'container/active/esml_lake_version.json'".format(self.lake_design_version,df_version))
            if (df_name!= self.lake_name): 
                print("ESML WARNING - Possible incompatible datalake desgin:"\
                    "lake_name={} in ESML SDK, but lake_name={} in storage account, at 'container/active/esml_lake_version.json'".format(self.lake_name,df_name))
        except Exception as e:
            raise UserErrorException("Could not Check ESML DataLake Compatability") from e

    #import jsonlines
    def update_json_files(self, param_esml_env,param_inference_model_version,param_scoring_folder_date,param_train_in_folder_date):
        save_train = "../../../settings/project_specific/model/active" # /active_in_folder.json"
        save_inf = "../../../settings/project_specific/model/active" # /active_scoring_in_folder.json"
        local_path_train = save_train + '/active_in_folder.json'
        local_path_scoring = save_inf+ '/active_scoring_in_folder.json'

        key_train_date = "{}_in_folder_date".format(param_esml_env)
        key_inf_date = "{}_scoring_folder_date".format(param_esml_env)
        key_inf_scoring = "{}_inference_model_version".format(param_esml_env)

        try:
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))

            # 1 Load from files

            with open(local_path_train) as f2: # where to read data to train on
                json_train = json.load(f2)
            with open(local_path_scoring) as f2: # where to read data to score
                json_inf = json.load(f2)

            # 2 UPDATE values
            json_inf[key_inf_scoring] = str(param_inference_model_version)
            json_inf[key_inf_date] = param_scoring_folder_date
            json_train[key_train_date] = param_train_in_folder_date

            # 3a - WRITE JSONLINES - Train (Overwrite local json files)
            with open(local_path_train, 'w') as outfile:
                json.dump(json_train, outfile, indent=2)

            # 3b - WRITE JSONLINES - Inference
            with open(local_path_scoring, 'w') as outfile:
                json.dump(json_inf, outfile, indent=2)

            # 4) Load from FILE again 
            with open(local_path_train) as f2: # where to read data to train on
                json_date_in_folder = json.load(f2)
            with open(local_path_scoring) as f2: # where to read data to score
                json_date_scoring_folder = json.load(f2)

            # 5) Update "in memory" to be consistent
            self.parseDateFolderConfig(json_date_in_folder,json_date_scoring_folder)
            self.inferenceModelVersion = int(param_inference_model_version)
            self.dev_test_prod = param_esml_env # overrides config
           
        except Exception as e:
            print("ESML Write from ArgParse to local .jsonlines files failed [active_in_folder.json,active_scoring_in_folder.json]  \n - Using [active_in_folder.json,active_scoring_in_folder.json] from DataLake.")
            print(e)
        finally:
            os.chdir(old_loc) # Switch back to callers "working dir"
        
    def readActiveDatesFromLake(self):
        train_conf = self._project_train_path.format(self.project_folder_name,self.model_folder_name) + "active" # = _proj_start_path+"/{}/{}/train/"
        inf_conf = self._project_inference_path.format(self.project_folder_name,self.model_folder_name) + "active"  # = _proj_start_path+"/{}/{}/inference/"
        train_paths = [(self.Lakestore, train_conf)]
        inf_paths = [(self.Lakestore, inf_conf)]

        try:
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))

            # JSON directly? Naae..jsonlines is not JSON
            #ds_train_json = Dataset.Tabular.from_json_lines_files(train_paths, validate=False, include_path=False, set_column_types=None, partition_format=None, invalid_lines='error', encoding='utf8')
            #df = ds_train_json.to_pandas_dataframe()
            #print(df.head())

            print("Searching for setting in ESML datalake...")
            # 1 - Train (Overwrite local json files)
            save_train = "../../../settings/project_specific/model/active" # active_in_folder.json"
            ds1 = Dataset.File.from_files(path=train_paths,validate=False)
            train_file = ds1.download(target_path=save_train, overwrite=True)

            # 2 - Inference (ovverwrite local json)
            save_inf = "../../../settings/project_specific/model/active" #active_scoring_in_folder.json"
            ds2 = Dataset.File.from_files(path=inf_paths,validate=False)
            inf_file = ds2.download(target_path=save_inf, overwrite=True)

            # Load from FILE again 
            print("ESML in-folder settings override = TRUE \n - Found settings in the ESML AutoLake  [active_in_folder.json,active_scoring_in_folder.json], to override ArgParse/GIT config with.")
            with open("../../../settings/project_specific/model/active/active_in_folder.json") as f2: # where to read data to train on
                json_date_in_folder = json.load(f2)
            with open("../../../settings/project_specific/model/active/active_scoring_in_folder.json") as f2: # where to read data to score
                json_date_scoring_folder = json.load(f2)

            self.parseDateFolderConfig(json_date_in_folder,json_date_scoring_folder)
            print (" - TRAIN in date: ", self._in_folder_date)
            print (" - INFERENCE in date: {} and ModelVersion to score with: {}{}".format(self._in_scoring_folder_date,self.inferenceModelVersion, " (0=latest)"))
           
        except Exception as e:
            print("ESML in-folder settings override = FALSE. [active_in_folder.json,active_scoring_in_folder.json] not found in LAKE. \n - Using [active_in_folder.json,active_scoring_in_folder.json] from ArgParse or GIT. No override from datalake settings")
            if("train/active'. Please make sure the path you've specified is correct, files exist and can be accessed" not in e.message):
                lake_path = ""
                start = "'"
                end = "'"
                try:
                    s = e.message
                    path_active = s[s.find(start)+len(start):s.rfind(end)]
                    print("Path for active folder (where no files exists):")
                    print(path_active)
                except Exception as e4:
                    print(e4)
        finally:
            os.chdir(old_loc) # Switch back to callers "working dir"

    def parseEnvConfig(self, env_config):
        self.overrideEnvConfig(env_config['active_dev_test_prod'],env_config) # Sets ACTIVE subscription also

    def vNetForActiveEnvironment(self):
        rg_name,vnet_name, subnet_name = None,None,None
        self.set_active_common_subnet_name()

        if(self.lake_storage_accounts == 1): # 1 lake for all -> ignore dev_test_prod. 
            vnet_name = self.env_config['common_vnet_name'].format("dev")
            rg_name = self.env_config['common_rg_name'].format("dev")
            subnet_name = self.active_common_subnet_name
        elif (self.lake_storage_accounts > 1): # (dev + test_prod) or (dev,test,prod)
            vnet_name = self.common_vnet_name
            rg_name = self.common_rg_name
            subnet_name = self.active_common_subnet_name

        return rg_name, vnet_name, subnet_name
        
    def getLakeForActiveEnvironment(self):
        sa_name, rg_name, sub_id = None,None,None

        if(self.lake_storage_accounts == 1): # 1 lake for all -> ignore dev_test_prod
            sa_name = self.dev_sa
            rg_name = self.env_config['common_rg_name'].format("DEV")
            sub_id = self.dev_subscription
        elif (self.lake_storage_accounts > 1): # (dev + test_prod) or (dev,test,prod)
            sa_name = self.active_sa
            rg_name = self.common_rg_name
            sub_id = self._subscriptionId

        return sa_name, rg_name, sub_id

    def set_active_common_subnet_name(self):
        if((len(self.common_subnet_name) > 0)): # At least DEV is set.
            if ("{}" in self.common_subnet_name): # by convention
                self.active_common_subnet_name = self.common_subnet_name.format(self.dev_test_prod)
            else:
                if (self.dev_test_prod == "dev"):
                    self.active_common_subnet_name = self.env_config['dev_common_subnet_name'] 
                elif (self.dev_test_prod == "test"):
                    self.active_common_subnet_name = self.env_config['test_common_subnet_name'] 
                elif (self.dev_test_prod == "prod"):
                    self.active_common_subnet_name = self.env_config['prod_common_subnet_name'] 

    def overrideEnvConfig(self, dev_test_prod_to_activate,env_config): 
        self._dev_test_prod = dev_test_prod_to_activate
       
        self.env_config = env_config
        self.override_enterprise_settings_with_model_specific = self.env_config['override_enterprise_settings_with_model_specific']
        self.tenant = self.env_config['tenant']
        self.dev_subscription = self.env_config['dev_subscription']
        self.test_subscription = self.env_config['test_subscription'] 
        self.prod_subscription = self.env_config['prod_subscription'] 

        if(self._dev_test_prod == "dev"):
            self._subscriptionId = self.dev_subscription
        elif(self._dev_test_prod == "test"):
            self._subscriptionId = self.test_subscription
        elif(self._dev_test_prod == "prod"):
            self._subscriptionId = self.prod_subscription

        self.lake_design_version = self.env_config['lake_design_version']

        self.common_rg_name = self.env_config['common_rg_name'].format(self.dev_test_prod.upper())
        self.common_vnet_name = self.env_config['common_vnet_name'].format(self.dev_test_prod)
        self.common_subnet_name = self.env_config['dev_common_subnet_name']

        self.set_active_common_subnet_name()
        
        self.use_aml_cluster_to_build_images = self.env_config['use_aml_cluster_to_build_images']

        self._project_number_XX_or_XXX = self.env_config["project_number_XX_or_XXX"]
        self._projectNoString = self.project_int_to_string()

        convention_order_env_first_rg = self.env_config['convention_project_resource_group_env_first']
        convention_order_env_first_ws = self.env_config['convention_project_workspace_name_env_first']
        
        self.lake_storage_accounts = int(self.env_config['lake_storage_accounts'])
        self.dev_sa = self.env_config['dev_sa']
        self.test_sa = self.env_config['test_sa']
        self.prod_sa = self.env_config['prod_sa']

        if(self._dev_test_prod == "dev"):
            self.active_sa = self.dev_sa
        elif(self._dev_test_prod == "test"):
            self.active_sa = self.test_sa
        elif(self._dev_test_prod == "prod"):
            self.active_sa = self.prod_sa

#NAMING CONVENTION - ORDER (prj vs ENV)
        if(convention_order_env_first_rg == True):
            self.resource_group = self.env_config['project_resource_group'].format(self.dev_test_prod.upper(),self._projectNoString)
        else:
            self.resource_group = self.env_config['project_resource_group'].format(self._projectNoString, self.dev_test_prod.upper())

        if(convention_order_env_first_ws == True):
            self.workspace_name = self.env_config['project_workspace_name'].format(self.dev_test_prod.upper(), self._projectNoString)
        else:
            self.workspace_name = self.env_config['project_workspace_name'].format(self._projectNoString,self.dev_test_prod.upper())

        self.location = self.env_config['project_location'].format(self.dev_test_prod)

    def is_json(self, data): 
        if isinstance(data, dict):
            return True
        else:
            return False
    def set_lake_as_datastore(self,ws):
        self.ws = ws
        storage_type_blob = self.security_config["storage_type_blob"] # BLOB vs GEN2
        
        if(storage_type_blob):
            print("Using BLOB as Datastore")
        else:
            print("Using GEN2 as Datastore")

        self.lake_access = LakeAccess(ws,self)

        if(storage_type_blob):
            self.datastore = self.lake_access.GetBlobAsDatastore()
        else:
           self.datastore = self.lake_access.GetLakeAsDatastore()
           #self.datastore.set_as_default()
           self.lakestore = self.datastore
        return self.datastore
    
    def get_run_and_task_type(self, run_id=None):
        self.initAutoMLFactory()
        return self.automl_factory.get_run_and_task_type(run_id)

    def get_best_model(self, ws,pipeline_run=False):
        self.initAutoMLFactory()
        return self.automl_factory.get_best_model(self,pipeline_run)

    def get_best_model_and_run_via_experiment_name_and_ws(self, ws, filter_on_version = None):
        model = self.get_best_model_via_experiment_name(ws,filter_on_version) # 2021-09
        if(model is None): # guard
            #print("No best model found in this Azure ML Studio, for this ESMLProject and ESMLModel. 1st time")
            return None,None,None,None,None
        else:
            model_name = model.tags["model_name"]
            run_id = model.tags["run_id"]
            experiment = Experiment(self.ws, self.experiment_name)
            main_run = AutoMLRun(experiment=experiment, run_id=run_id) 
            #main_run = Run(experiment=experiment, run_id=run_id) # Why not this? 
            best_automl_run, fitted_model = main_run.get_output() # TODO-AutoML specific really? to get "best_automl_run, fitted_model"...should be 1 run returned either way?
        return experiment, model,main_run, best_automl_run,fitted_model

    def get_best_model_and_run_via_experiment_name(self,filter_on_version = None):
        return self.get_best_model_and_run_via_experiment_name_and_ws(self.ws,filter_on_version)

    def get_best_model_via_experiment_name(self,workspace=None,filter_on_version = None):
        latest_model = None
        active_workspace = None
        if(workspace is None):
            active_workspace = self.ws
        else:
            active_workspace = workspace
        if(active_workspace is None):
            raise ArgumentError("Azure ML workspace is null. You need to connect to a workspace and set ESMProject.ws property, or pass an external workspace as first parameter")

        ex1 = Experiment(active_workspace, self.experiment_name) # Can be other workspace (dev,test,prod), but same experiment name
        tag_model_name = None
        tag_model_version = None
        if (ex1.tags is not None and "best_model_version" in ex1.tags and "model_name" in ex1.tags):
            tag_model_name = ex1.tags["model_name"]
            tag_model_version = ex1.tags["best_model_version"]
        
            if (filter_on_version is not None):
                latest_model = Model(active_workspace, name=tag_model_name, version=filter_on_version)
                print ("found model via REMOTE FILTER + VersionFilter as input.Tags: mode_name, model_version")
            else:
                latest_model = Model(active_workspace, name=tag_model_name, version=tag_model_version)
                print ("found model via REMOTE FILTER: Experiment TAGS: model_name")
        else:
            print ("Searching model - LOOPING the experiment to match name (1st time thing, since no tags)")
            for m in Model.list(active_workspace):
                if(m.experiment_name == self.experiment_name):
                    
                    if(filter_on_version is not None):
                        if(filter_on_version == m.version):
                            latest_model = m
                            print ("found model matching experiment_name, also matching on model_version")
                            break
                    else:
                        latest_model = m
                        print ("found model matching experiment_name, selecting latest registered.")
                    break
                    
            if (latest_model is not None): # Update Experiment tag
                ex = Experiment(active_workspace, self.experiment_name)
                tags = {'model_name':latest_model.name, 'best_model_version':m.version}
                ex.set_tags(tags)

        return latest_model

    def get_training_aml_compute(self,ws, use_non_model_specific_cluster=False, create_cluster_with_suffix_char=None):
        self.initComputeFactory(ws)
        
        if(use_non_model_specific_cluster==True):
            print("Using a non model specific cluster (enterprice policy cluster), yet environment specific")
            compute,name = self._compute_factory.get_training_aml_compute(self.dev_test_prod, self.override_enterprise_settings_with_model_specific,self._projectNoString,self._modelNrString,create_cluster_with_suffix_char)
            self.use_compute_cluster_to_build_images(ws, name)
            return compute

        else:
            print("Using a model specific cluster, per configuration in project specific settings, (the integer of 'model_number' is the base for the name)")
            compute,name = self._compute_factory.get_training_aml_compute(self.dev_test_prod, self.override_enterprise_settings_with_model_specific,self._projectNoString,self._modelNrString,create_cluster_with_suffix_char)
            self.use_compute_cluster_to_build_images(ws, name)
            return compute

    '''
    def get_latest_model(self, ws):
        if(self.automl_factory is None):
             self.automl_factory = AutoMLFactory(self)
        return self.automl_factory.get_latest_model(ws)
    '''

    @property
    def compute_factory(self):
        if(self._compute_factory is None):
            self.initComputeFactory(self.ws)
        return self._compute_factory 

    def connect_to_lake(self):
        self.lakestore = self.set_lake_as_datastore(self.ws) # only needed if NOT p.init() is done
        self.readActiveDatesFromLake()
        self.checkLakeCompatability()
        return self.lakestore
    def initComputeFactory(self,ws,reload_config=False):

        if(reload_config==True): # Force recreate, reload config
            self._compute_factory = ComputeFactory(self,ws,self.dev_test_prod,self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)

        if (self._compute_factory is not None): #Only switch to a new FACTORY is existing, and if ws changed.
           if (self.ws is not None and self.ws != ws): # If WORKSPACE switches, "create a new ComputeFactory"
                self._compute_factory = ComputeFactory(self,ws,self.dev_test_prod,self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)
        else: # Just create a factory
            self._compute_factory = ComputeFactory(self,ws,self.dev_test_prod,self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)

    @staticmethod
    def call_webservice_own_url(pandas_X_test, api_uri,api_key,firstRowOnly=True):
        return ComputeFactory.call_webservice_static(pandas_X_test, api_uri,api_key,firstRowOnly)

    '''
    ESML - This will also cache the scored results to DATALAKE,   IF `inference_model_version=1` in `settings/project_specific/lake_settings.json`
    '''
    def call_webservice(self,ws, pandas_X_test,user_id=None, firstRowOnly=False,inference_model_version=None, reload_config=True):
        self.initComputeFactory(ws,reload_config)

        df_result,model_version = self._compute_factory.call_webservice(pandas_X_test,firstRowOnly) # TODO: Use inference_model_version to pick webservice/model version, other than the "single one & latest"
        
        if(inference_model_version is not None): # user override, not reading from keyvault
            model_version = inference_model_version 
        scored_result = self.save_scored_result(model_version,pandas_X_test,df_result, user_id)
        return scored_result
    
    #TODO batch score
    def batch_score(self,ws, date_folder, unique_folder,specific_file_guid=None,use_spark_compute=False,firstRowOnly=False,inference_model_version=None, reload_config=True ):
        self.initComputeFactory(ws,reload_config)
       
        if(inference_model_version is not None): # user override, not reading from keyvault
            model_version = inference_model_version 
        scored_result = self._batch_score_aml_pipeline(model_version,date_folder,unique_folder,specific_file_guid,firstRowOnly)
        return scored_result

    def use_compute_cluster_to_build_images(self,ws,name):
        if(self.use_aml_cluster_to_build_images):
            print("image_build_compute = {}".format(name))
            ws.update(image_build_compute = name)
        else: # To switch back to using ACR to build (if ACR is not in the VNet):
            ws.update(image_build_compute = '')
            print("image_build_compute = ACR")

    def get_deploy_config_aks(self):
        self.initComputeFactory(self.get_other_workspace(self.dev_test_prod))
        deploy_config = self._compute_factory.get_deploy_config(self, self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)
        return deploy_config
    # Returns [service,api_uri, self.kv_aks_api_secret] - the api_secret is stored in your keyvault
    def deploy_automl_model_to_aks(self, model,inference_config, overwrite_endpoint=True,deployment_config=None):

        if(model is None):
            print("Model is none - nothing to deploy")
            return None
        else:
            print("Deploying model: {} with verison: {} to environment: {} with overwrite_endpoint={}".format(model.name, model.version, self.dev_test_prod,overwrite_endpoint))
        target_workspace = self.get_other_workspace(self.dev_test_prod)
        self.initComputeFactory(target_workspace)

        self.use_compute_cluster_to_build_images(target_workspace,self._compute_factory.aml_cluster_name)
        if(overwrite_endpoint):
            self._compute_factory.delete_aks_endpoint(target_workspace)
        return self._compute_factory.deploy_online_on_aks(self,model,inference_config, self.dev_test_prod,deployment_config, self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)

    def initAutoMLFactory(self):
        if(self.automl_factory is None):
            self.automl_factory = AutoMLFactory(self)

    def get_active_model_inference_config(self, ws_in = None):
        ws = None
        if (ws_in is None):
            ws = self.ws # use its own default WS
        else:
            ws = ws_in

        self.initAutoMLFactory()
        if(self._compute_factory is None):
            self.initComputeFactory(ws)

        target_workspace = self.get_other_workspace(self.dev_test_prod)
        return self.automl_factory.get_active_model_inference_config(target_workspace,self.dev_test_prod,self.override_enterprise_settings_with_model_specific)

    def get_active_model_run_and_experiment(self):
        self.initAutoMLFactory()
        target_workspace = self.get_other_workspace(self.dev_test_prod)
        return self.automl_factory.get_active_model_run_and_experiment(target_workspace,self.dev_test_prod,self.override_enterprise_settings_with_model_specific)

    def register_active_model(self):
        self.initAutoMLFactory()
        return self.automl_factory.register_active_model(self, self.dev_test_prod)

    def get_automl_performance_config(self,use_dev_test_prod_settings=None, use_black_or_allow_list_from_config=True):
        self.initAutoMLFactory()
        d_t_p = self.dev_test_prod
        conf = None
        try: 
            old_state = self.dev_test_prod
            if(use_dev_test_prod_settings is not None):
                d_t_p = use_dev_test_prod_settings

            conf = self.automl_factory.get_automl_performance_config(d_t_p,use_black_or_allow_list_from_config, self.override_enterprise_settings_with_model_specific)
        except Exception as e:
            raise e
        finally:
            self.dev_test_prod = old_state # switch back
        return conf

    def get_authenticaion_header_sp(self):
        kv = self.ws.get_default_keyvault() # Get "current" workspace, either CLI Authenticated if MLOps, or in DEMO/DEBUG Interactive
        sp = ServicePrincipalAuthentication(tenant_id=kv.get_secret(name=self.security_config["tenant"]), # tenantID
                                                service_principal_id=kv.get_secret(self.security_config["kv-secret-esml-projectXXX-sp-id"]), # clientId
                                                service_principal_password=kv.get_secret(self.security_config["kv-secret-esml-projectXXX-sp-secret"])) # clientSecret
        return sp

    def get_other_workspace(self, dev_test_prod):
        kv = self.ws.get_default_keyvault() # Get "current" workspace, either CLI Authenticated if MLOps, or in DEMO/DEBUG Interactive
        other_ws = None
        current_env = self.dev_test_prod

        try:
            self.dev_test_prod = dev_test_prod # Reloads config from TARGET
            sp = ServicePrincipalAuthentication(tenant_id=kv.get_secret(name=self.security_config["tenant"]), # tenantID
                                                service_principal_id=kv.get_secret(self.security_config["kv-secret-esml-projectXXX-sp-id"]), # clientId
                                                service_principal_password=kv.get_secret(self.security_config["kv-secret-esml-projectXXX-sp-secret"])) # clientSecret

            other_ws = Workspace.get(name = self.workspace_name,subscription_id = self.subscription_id,resource_group = self.resource_group,auth=sp)
        except ProjectSystemException as e:
            print("")
            print("INFO")
            print("You have no (or access to) Azure ML Studio Workspace in environment '{}'".format(dev_test_prod))
            print("You need the below created/access: ")
            print("")
            print("Subscription ID: ", self.subscription_id)
            print("Resource group", self.resource_group)
            print("Workspace name", self.workspace_name)
            print("")
        finally:
            self.dev_test_prod = current_env

        return other_ws

    @property
    def cpu_gpu_databricks(self):
        return self._cpu_gpu_databricks
    
    @cpu_gpu_databricks.setter
    def cpu_gpu_databricks(self, cpu_gpu_databricks):
        self._cpu_gpu_databricks = cpu_gpu_databricks

    @property
    def inference_mode(self):
        return self._inference_mode

    @inference_mode.setter
    def inference_mode(self, inference_mode):
        self._inference_mode = inference_mode

    @property
    def verbose_logging(self):
        return self._verbose_logging

    @verbose_logging.setter
    def verbose_logging(self, enable_verbose_logging):
        self._verbose_logging = enable_verbose_logging

    @property
    def ComputeFactory(self):
        self.initComputeFactory(self.ws, reload_config=True)
        return self._compute_factory
    @property
    def experiment_name(self):
        return self.model_folder_name
    @property
    def RecreateDatastore(self):
        return self._recreate_datastore
    @property
    def LakeAccess(self):
        return self.lake_access
    @property
    def subscription_id(self):
        return self._subscriptionId

    @subscription_id.setter
    def subscription_id(self, subId):
        self._subscriptionId = subId

    @property
    def dev_test_prod(self):
        return self._dev_test_prod

    @dev_test_prod.setter
    def dev_test_prod(self, dev_test_prod):

        self._dev_test_prod = dev_test_prod
        self.save_active_env()
        self.overrideEnvConfig(self._dev_test_prod, self.env_config)
        #self.initDatasets(self.inferenceModelVersion, self.project_folder_name,self.model_folder_name,self.dataset_folder_names)

    @property
    def ModelAlias(self):
        return self._model_short_alias
    @property
    def dataset_gold_name_azure(self):
        return self.ModelAlias+"_GOLD"
    @property
    def dataset_gold_train_name_azure(self):
        return self.ModelAlias+"_GOLD_TRAIN"
    @property
    def dataset_gold_validate_name_azure(self):
        return self.ModelAlias+"_GOLD_VALIDATE"
    @property
    def dataset_gold_test_name_azure(self):
        return self.ModelAlias+"_GOLD_TEST"

    @property
    def dataset_gold_scored_name_azure(self):
        return self.ModelAlias+"_GOLD_SCORED"

    @property
    def dataset_gold_scored_runinfo_name_azure(self):
        return self.ModelAlias+"_GOLD_SCORED_RUNINFO"
    @property
    def dataset_active_name_azure(self):
        return self.ModelAlias+"_ACTIVE_FOLDER"

    @property
    def dataset_gold_to_score_name_azure(self):
        return self.ModelAlias+"_GOLD" + self.dataset_inference_suffix
    @property
    def rnd(self):
        return self._rndPhase
    @rnd.setter
    def rnd(self, RnDBool):
        self._rndPhase = RnDBool
    @property
    def InDateFolder(self):
        return self._in_folder_date
    @property
    def Datasets(self):
        return self.dataset_list
    @property
    def ProjectXXX(self):
        return self._projectNoXXX
    @property
    def ProjectXX(self):
        return self._projectNoXX
    @property
    def Lakestore(self):
        return self.datastore

    '''
        self._gold_scored = ds
        dataset_gold_scored_name_azure
    '''

    def path_gold_to_score_template(self, date_folder=False,id_folder=False,inference_mode = True):
        to_score_template = ""

        if(inference_mode == True):
            baseline = self._inference_gold_path.format(self.project_folder_name,self.model_folder_name,"{model_version}", self.dev_test_prod)
        else:
            baseline = self.GoldPath

        if(date_folder):
            to_score_template = baseline+ "{date_folder}" + "/"
        else:
            to_score_template = baseline

        if (id_folder):
            to_score_template = to_score_template + "{id_folder}" + "/"
        
        return to_score_template
    
    def path_gold_scored_template(self, date_folder=False,id_folder=False, inference_mode = True):
        to_score_template = "" 
        if(inference_mode == True):
            baseline = self._inference_scored_path.format(self.project_folder_name,self.model_folder_name,"{model_version}", self.dev_test_prod)
        else:
            baseline = self.GoldPath

        if(date_folder):
            to_score_template = baseline+ "{date_folder}" + "/"
        else:
            to_score_template = baseline

        if (id_folder):
            to_score_template = to_score_template + "{id_folder}" + "/"

        return to_score_template

    @property
    def path_inference_active(self):
        inference_active_meta = self._project_inference_path.format(self.project_folder_name,self.model_folder_name) + "active"
        return inference_active_meta
    @property
    def path_inference_gold_scored_runinfo(self):
        inference_gold_scored_info = self._project_inference_path.format(self.project_folder_name,self.model_folder_name) + "active/gold_scored_runinfo"
        return inference_gold_scored_info

    def get_gold_scored_unique_path(self, batch_datetime_from_config = None, same_guid_folder=True,unique_uuid4 = None):
        to_score_unique_folder = ""
        scored_unique_folder = ""
        date_folder = ""

        try:
            if (batch_datetime_from_config is not None): 
               date_folder=batch_datetime_from_config.strftime('%Y_%m_%d')
            else: # realtime = "todays datetime"
                now = datetime.datetime.now()
                date_folder = now.strftime('%Y_%m_%d') 

            if(same_guid_folder):
                if(unique_uuid4 is not None): 
                    same_guid_folder = unique_uuid4
                else:
                    same_guid_folder = uuid.uuid4().hex
                to_score_unique_folder = self.GoldPathScoring + date_folder + '/'+same_guid_folder + "/"
                scored_unique_folder = self.ScoredPath + date_folder + '/'+ same_guid_folder + "/"
            else: # If you want to save "latest" version, or only 1 version that day (p.call_webservice uses both, both uniqe per day, and the latest)
                to_score_unique_folder = self.GoldPathScoring + date_folder + '/'
                scored_unique_folder = self.ScoredPath + date_folder + '/'
        finally:
            pass
        return to_score_unique_folder, scored_unique_folder, date_folder
    
    @property
    def BestModel(self):
        if (self._best_model is None): # Lazy load 1st version 
            source_best_run, fitted_model, experiment = self.get_best_model(self.ws)
            model_name = source_best_run.properties['model_name']
            self._best_model = Model(self.ws, model_name)
        return self._best_model

    @property
    def GoldScored(self): 
        try:
            if (self._gold_scored is None): # Lazy load 1st version 
                self._gold_scored = Dataset.get_by_name(self.ws, name=self.dataset_gold_scored_name_azure)
            return self._gold_scored # Latest version
        except UserErrorException as e1:
            if("Cannot load any data from the specified path" in e1.message):
                raise UserErrorException("ESML GoldScored seems to be empty? Have you scored any data? [project.save_scoring(...)]") from e1

    @property
    def GoldTrain(self): 
        try:
            if (self._gold_train is None): # Lazy load 1st version 
                self._gold_train = Dataset.get_by_name(self.ws, name=self.dataset_gold_train_name_azure)
            return self._gold_train # Latest version
        except UserErrorException as e1:
            if("Cannot load any data from the specified path" in e1.message):
                raise UserErrorException("ESML GoldTrain seems to be empty? Have you splitted data?  [project.split_gold_3]") from e1
    @property
    def GoldValidate(self): 
        try:
            if (self._gold_validate is None): # Lazy load 1st version 
                self._gold_validate = Dataset.get_by_name(self.ws, name=self.dataset_gold_validate_name_azure)
            return self._gold_validate # Latest version
        except UserErrorException as e1:
            if("Cannot load any data from the specified path" in e1.message):
                raise UserErrorException("ESML GoldValidate seems to be empty? Have you splitted data [project.split_gold_3]") from e1
    @property
    def GoldTest(self): 
        try:
            if (self._gold_test is None): # Lazy load 1st version 
                self._gold_test = Dataset.get_by_name(self.ws, name=self.dataset_gold_test_name_azure)
            return self._gold_test# Latest version
        except UserErrorException as e1:
            if("Cannot load any data from the specified path" in e1.message):
                raise UserErrorException("ESML GoldTest seems to be empty? Have you splitted data?  [project.split_gold_3]") from e1
    @property
    def GoldToScore(self): 
        try:
            if (self._gold_to_score is None): # Lazy load 1st version 
                self._gold_to_score = Dataset.get_by_name(self.ws, name=self.dataset_gold_to_score_name_azure)
            return self._gold_to_score # Latest version
        except UserErrorException as e1:
            if("Cannot load any data from the specified path" in e1.message):
                raise UserErrorException("ESML GoldTest seems to be empty? Have you splitted data?  [project.split_gold_3]") from e1

    @property
    def Gold(self): 
        # TODO: Load LATEST version folder. Solution: Singelton...always have in memory
        # TODO: To include files in subfolders, append '/**' after the folder name like so: '{Folder}/**'.
        try:
            if(self.inference_mode):
                self._gold_to_score = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPath)])  # If not registered, fetch from LAKE
                return self._gold_to_score # Latest version
            else:
                self._gold_dataset = Dataset.get_by_name(self.ws, name=self.dataset_gold_name_azure)
                return self._gold_dataset # Latest version
        except UserErrorException as e1:
            if("Cannot load any data from the specified path" in e1.message):
                raise UserErrorException("ESML GOLD dataset seems to be empty? Have you saved any data yet? use ESMLProject.save_gold_pandas_as_azure_dataset(df)") from e1
    @property
    def GoldPath(self):
        if(self.inference_mode):
            return self._inference_gold_path.format(self.project_folder_name,self.model_folder_name,self.inferenceModelVersion, self.dev_test_prod)
        else:
            return self._train_gold_path.format(self.project_folder_name,self.model_folder_name, self.dev_test_prod)

    @property
    def GoldPathDatabricks(self):
        if(self.inference_mode):
            return self._inference_gold_path.format(self.project_folder_name,self.model_folder_name,self.inferenceModelVersion, self.dev_test_prod) + "gold_dbx.parquet/*.parquet"
        else:
            return self._train_gold_path.format(self.project_folder_name,self.model_folder_name, self.dev_test_prod)+ "gold_dbx.parquet/*.parquet"
    @property
    def GoldDatabricks(self):
        if(self.inference_mode):
            return Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPathDatabricks)])
        else:
            return Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPathDatabricks)])

    @property
    def ScoredPath(self): # TODO: Default to LATEST version folder
        return self._inference_scored_path.format(self.project_folder_name,self.model_folder_name,self.inferenceModelVersion, self.dev_test_prod)

# Used just for "DESCRIBE" purpose, during creating the Scoring pipline "GoldPath" is used, and will return self.inference_mode
    @property
    def GoldPathScoring(self): 
        active_mode = self.inference_mode
        gold_path = ""
        try:
            self.inference_mode = True 
            gold_path = self.GoldPath
        finally:
            self.inference_mode = active_mode
        return gold_path
   
    @property
    def GoldPathToScoreBatch(self):
        date_folder_str = self.date_scoring_folder.strftime('%Y_%m_%d')
        target_path = self.GoldPathScoring + date_folder_str +'/'
        return target_path

# Used for DESCRIBE
    def get_workspace_from_config(self,cli_auth=None, vNetACR=True):
        try:
            if(cli_auth is None):
                self.ws = Workspace.from_config(path="../../../", _file_name= self.get_workspace_configname())
            else:
                self.ws = Workspace.from_config(path="../../../", auth=cli_auth, _file_name= self.get_workspace_configname())
        except:
            try:
                if(cli_auth is None):
                    self.ws = Workspace.from_config(path="../../", _file_name= self.get_workspace_configname())
                else:
                    self.ws = Workspace.from_config(path="../../", auth=cli_auth, _file_name= self.get_workspace_configname())
            except Exception as e:
                raise UserErrorException("Config could not be found neither 3 or 2 folders, via: Workspace.from_config(path=../../, auth=cli_auth, _file_name= self.get_workspace_configname())") from e
        return self.ws

    def authenticate_workspace_and_write_config(self, auth=None):
        if(auth is None):
            ws = Workspace.get(name = self.workspace_name,subscription_id = self.subscription_id,resource_group = self.resource_group)
        else:
            ws = Workspace.get(name = self.workspace_name,subscription_id = self.subscription_id,resource_group = self.resource_group,auth=auth)
            
        config_name = self.get_workspace_configname()

        old_loc = os.getcwd()
        try:
            ws.write_config(path="../../", file_name=config_name)
        except Exception as e:
            raise Exception("Error - authenticate_workspace_and_write_config - Cannot write config-file") from e
        finally: 
            os.chdir(old_loc) # Change back to working location...
        return ws, config_name

    def get_workspace_configname(self):
        return self.dev_test_prod + "_ws_config.json"

    def _batch_score_aml_pipeline(self,inference_model_version,date_folder,unique_folder,specific_file_guid,firstRowOnly):
        # 1) Merge features + scoring
        print("Saving batch scoring to lake for project folder {} and inference_model_version: {} ...".format(self.project_folder_name,inference_model_version))

        try:
            #0) Generate PATH from settings and Lake-design
            inference_before = self.inferenceModelVersion
            self.inferenceModelVersion = inference_model_version # IMPORTANT!!
            v_str = str(self.inferenceModelVersion)

            file_name_to_score = "{}.parquet".format("*") # All files
            if(specific_file_guid is not None):
                file_name_to_score = "to_score_{}.parquet".format(specific_file_guid)

            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty

            # 1) To score: Generate LAKE-path, what to READ, what to SCORE?
            day_folder = self.GoldPathScoring + date_folder + '/'
            unique_folder = self.GoldPathScoring + date_folder + '/'+unique_folder + "/"
            srs_folder = '../../../../common/temp_data/{}/inference/{}/Gold/'.format(self.project_folder_name,v_str)
            local_path = '{}{}'.format(srs_folder,file_name_to_score)
            ESMLProject.create_folder_if_not_exists(srs_folder)

            # 2) Score ComputeFactory + PipelineFactory
            pandas_X = None
            df_result = None
            df_result,model_version = self._compute_factory.batch_score(unique_folder, file_name_to_score) # A unique folder, a day
            df_result,model_version = self._compute_factory.batch_score(day_folder, file_name_to_score) # A datetime folder (usually a day, hour, minute)

            # 3) Save scored result
            scored_result = pandas_X.join(df_result)
            if(self.rnd == True): # No caching/saving to lake if R&D
                print("R&D - Do not save scoring to lake")
                return scored_result
            
            unique_folder = self.ScoredPath + date_folder + '/'+ unique_folder + "/"
            srs_folder = '../../../../common/temp_data/{}/inference/{}/Scored/'.format(self.project_folder_name,v_str)
            file_name = "scored.parquet" # Score all
            if(specific_file_guid is not None): # Score specific / Filter
                file_name = "scored_{}.parquet".format(specific_file_guid) # HERE ....who is this scoring about?

            local_path = '{}{}'.format(srs_folder,file_name)
            ESMLProject.create_folder_if_not_exists(srs_folder)
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))
            scored_result.to_parquet(local_path, engine='pyarrow', compression='snappy', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            self.LakeAccess.upload(file_name, srs_folder, unique_folder, overwrite=True,use_dataset_factory = False) # BLOB or GEN 2

            print("Saved SCORED data in LAKE, as file '{}'".format(file_name))
        except Exception as e:
            raise e
        finally:
            #ESMLProject.delete_all_in_folder('../../../../common/temp_data/') # What if..2 models running on same VM or server?
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty, for project only...for multiple models to be running at the same time
            os.chdir(old_loc)
            self.inferenceModelVersion = inference_before # Set back to same state

        return scored_result,model_version

    def save_scored_result(self, inference_model_version, pandas_X_test, df_result, user_id):
        # 1) Merge features + scoring
        scored_result = pandas_X_test.join(df_result)
        if(self.rnd == True): # No caching/saving to lake if R&D
            print("R&D - Do not save scoring to lake")
            return scored_result

        print("Saving scoring to lake for project folder {} and inference_model_version: {} ...".format(self.project_folder_name,inference_model_version))

        inference_before = self.inferenceModelVersion
        self.inferenceModelVersion = inference_model_version # IMPORTANT!! should be an INT also.
        v_str = str(self.inferenceModelVersion)

        if(user_id is None):
            caller_guid = "user_guid"
        else:
            caller_guid = user_id
        try:
            ESMLProject.clean_temp(self.project_folder_name) # clean temp
            # 2) Save pandas_X_test to goldpath

            to_score_folder, scored_folder, date_folder = self.get_gold_scored_unique_path()
            to_score_folder_latest, scored_folder_latest, date_folder_latest = self.get_gold_scored_unique_path(batch_datetime_from_config = None, same_guid_folder=False,unique_uuid4 = None)

            srs_folder = '../../../../common/temp_data/{}/inference/{}/Gold/'.format(self.project_folder_name,v_str)
            file_name = "to_score_{}.parquet".format(caller_guid) # HERE ....who is this scoring about?
            local_path = '{}{}'.format(srs_folder,file_name)
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))
            ESMLProject.create_folder_if_not_exists(srs_folder)
            pandas_X_test.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            self.LakeAccess.upload(file_name, srs_folder, to_score_folder, overwrite=True,use_dataset_factory = False) # BLOB or GEN 2 
            self.LakeAccess.upload(file_name, srs_folder, to_score_folder_latest, overwrite=True,use_dataset_factory = False) # Also upload LATEST to "date_folder root"

            print("")
            print("Saved DATA to score successfully in LAKE, as file '{}'".format(file_name))

            # 3) Save scored_results, to unique folder, for the day 
            # Note: Here we can save also, which CALLER/User-Guid it is about. We cab have a User_id_GUID as a "feature/column"

            srs_folder = '../../../../common/temp_data/{}/inference/{}/Scored/'.format(self.project_folder_name,v_str)
            file_name = "scored_{}.parquet".format(caller_guid) # HERE ....who is this scoring about?

            local_path = '{}{}'.format(srs_folder,file_name)
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))
            ESMLProject.create_folder_if_not_exists(srs_folder)
            scored_result.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            self.LakeAccess.upload(file_name, srs_folder, scored_folder, overwrite=True,use_dataset_factory = False) # BLOB or GEN 2
            self.LakeAccess.upload(file_name, srs_folder, scored_folder_latest, overwrite=True,use_dataset_factory = False) # LATEST to "date_folder root"
            
            print("Saved SCORED data in LAKE, as file '{}'".format(file_name))

            # Optional o register 
            try:
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, scored_folder + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, scored_folder + file_name+"_dbx/*.parquet")],validate=False)
                description = "Scored gold data with model version {}".format(v_str)
                self.registerGoldScored(ds,description,date_folder, v_str,caller_guid,self.rnd)
            except Exception as e2:
                print("Could not merge X_test to scored_all_X.parquet and register as Azure ML Dataset. You will have to do this on your own..")

        except Exception as e:
            raise e
        finally:
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty
            os.chdir(old_loc)
            self.inferenceModelVersion = inference_before # Set back to same state

        return scored_result

    def save_gold(self,dataframe, new_version=True):
        if(self.inference_mode):
            return self.save_gold_inference_pandas_as_azure_dataset(dataframe,new_version)
        else:
            return self.save_gold_pandas_as_azure_dataset(dataframe,new_version)

    def save_gold_pandas_as_azure_dataset(self,dataframe, new_version=True):
        srs_folder = '../../../../common/temp_data/{}/Gold/'.format(self.project_folder_name)
        target_path = self.GoldPath
        file_name = "gold.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)

        ESMLProject.create_folder_if_not_exists(srs_folder)
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            dataframe.to_parquet(local_path, engine='pyarrow',compression='snappy', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            ds = None
            if(self.rnd): # No versioning & overwrite
                self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPath + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPath +file_name+ "_dbx/*.parquet")],validate=False)
            else: # Version folder (don't overwrite) AND LatestVersion at "root", where we overwrite   #NB - This can be optimizes later, if we dont want to double write GOLD
                self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=True) # Save 1 - Latest GOLD, overwrite

                version_folder = self.GoldPath + uuid.uuid4().hex + "/"
                self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # Save 2 - versioning
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPath +file_name+ "_dbx/*.parquet")],validate=False)
        finally:
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty
            os.chdir(old_loc)
        # Set and return "LATEST" version
        return self.registerGold(ds, self.model_folder_name+": GOLD.parquet merged from all datasets. Source to be splitted (Train,Validate,Test)",new_version)

 #TRAIN, VALIDATE, TEST   
    def save_gold_train_pandas_as_azure_dataset(self,dataframe,split_percentage,label, new_version=True):
        srs_folder = '../../../../common/temp_data/{}/Gold/Train/'.format(self.project_folder_name)
        target_path = self.GoldPath + 'Train/'
        file_name = "gold_train.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)

        ESMLProject.create_folder_if_not_exists(srs_folder)
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            dataframe.to_parquet(local_path, engine='pyarrow', compression='snappy', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            ds = None
            if(self.rnd): # No versioning & overwrite
                self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path + file_name +"_dbx/*.parquet")],validate=False)
            else: # Version folder + don't overwrite
                version_folder = target_path + uuid.uuid4().hex + "/"
                self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # BLOB, or GEN 2
                ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)
        finally:
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty
            os.chdir(old_loc)
        # Set and return "LATEST" version
        return self.registerGoldTrain(ds, self.model_folder_name+"GOLD_TRAIN.parquet from splitted Train, Validate, Test",split_percentage,label,new_version)

    def save_gold_inference_pandas_as_azure_dataset(self,dataframe, new_version=True, label=None):
        target_path = self.GoldPathToScoreBatch
        srs_folder = '../../../../common/temp_data/{}/Gold/Inference/'.format(self.project_folder_name)
        file_name = "gold_to_score.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)
        
        ESMLProject.create_folder_if_not_exists(srs_folder)
        
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            dataframe.to_parquet(local_path, engine='pyarrow',compression='snappy',  index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            ds = None
            if(self.rnd): # No versioning & overwrite
                self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path +file_name +"_dbx/*.parquet")],validate=False)
            else: # Version folder + don't overwrite
                self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=True) # Save 1: Latest - Also save "latest", NB: Optimize potential 

                version_folder = target_path + uuid.uuid4().hex + "/"
                self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # Save2: unique per day (support multiple scorings per day)
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder +file_name +"_dbx/*.parquet")],validate=False)
        finally:
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty, if it existed for some reason
            os.chdir(old_loc)

        # Set and return "LATEST" version
        version_string = str(self.inferenceModelVersion)
        date_folder = self.date_scoring_folder.strftime('%Y_%m_%d')
        return self.registerGoldToScore(ds, self.model_folder_name+": GOLD_to_score.parquet",date_folder,version_string,new_version), version_folder

    def save_gold_validate_pandas_as_azure_dataset(self,dataframe,split_percentage,label, new_version=True):
        srs_folder = '../../../../common/temp_data/{}/Gold/Validate/'.format(self.project_folder_name)
        target_path = self.GoldPath + 'Validate/'
        file_name = "gold_validate.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)
        
        ESMLProject.create_folder_if_not_exists(srs_folder)
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            dataframe.to_parquet(local_path, engine='pyarrow', compression='snappy', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            ds = None
            if(self.rnd): # No versioning & overwrite
                self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path +file_name+ "_dbx/*.parquet")],validate=False)
            else: # Version folder + don't overwrite
                version_folder = target_path + uuid.uuid4().hex + "/"
                self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # BLOB, or GEN 2
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder +file_name+ "_dbx/*.parquet")],validate=False)
        finally:
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty, if it existed for some reason
            os.chdir(old_loc)

        # Set and return "LATEST" version
        return self.registerGoldValidate(ds, self.model_folder_name+": GOLD_VALIDATE.parquet from splitted Train, Validate, Test",split_percentage,label, new_version)

    def save_gold_test_pandas_as_azure_dataset(self,dataframe, split_percentage,label, new_version=True):
        srs_folder = '../../../../common/temp_data/{}/Gold/Test/'.format(self.project_folder_name)
        target_path = self.GoldPath + 'Test/'
        file_name = "gold_test.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)
        ESMLProject.create_folder_if_not_exists(srs_folder)
        try:
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))
            dataframe.to_parquet(local_path, engine='pyarrow',compression='snappy',  index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            ds = None
            if(self.rnd): # No versioning & overwrite
                self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path+ "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path+file_name+ "_dbx/*.parquet")],validate=False)
            else: # Version folder + don't overwrite
                version_folder = target_path + uuid.uuid4().hex + "/"
                self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # BLOB, or GEN 2
                try:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)
                except:
                    ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder +file_name+ "_dbx/*.parquet")],validate=False)
        finally:
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty
            os.chdir(old_loc)

        # Set and return "LATEST" version
        return self.registerGoldTest(ds, self.model_folder_name+": GOLD_TEST.parquet from splitted Train, Validate, Test",split_percentage,label,new_version)

#TRAIN, VALIDATE, TEST

    def split_gold_dbx(self,train_percentage=0.6, label=None,stratified=False,seed=42, new_version=True):
        return self.split_gold(self.GoldDatabricks,train_percentage, label,new_version,stratified,seed)

    def split_gold_3(self,train_percentage=0.6, label=None,stratified=False,seed=42, new_version=True):
        return self.split_gold(self.Gold,train_percentage, label,new_version,stratified,seed)

    def split_gold(self,azure_ml_gold_dataset, train_percentage=0.6, label_in=None,new_version=True, stratified=False,seed=42):
        label = None
        if (label_in is None):
            label = self.active_model["label"]
        else:
            label = label_in

        df = azure_ml_gold_dataset.to_pandas_dataframe()
        whats_left_for_both = round(1-train_percentage,1)  # 0.4 ...0.3 if 70%
        left_per_set = round((whats_left_for_both / 2),2) # 0.2  ...0.15
        validate_and_test = round((1-left_per_set),2) # 0.8 ....0.75

        if(stratified):
            print("Stratified split on column {} using StratifiedShuffleSplit twice, to get GOLD_TRAIN/OTHER and then 0.5 split on OTHER to get GOLD_VALIDATE & GOLD_TEST".format(label))
            train, validate, test = split_stratified(df,whats_left_for_both,left_per_set,label)
        else:
            train, validate, test = \
                np.split(df.sample(frac=1, random_state=seed), 
                        [int(train_percentage*len(df)), int(validate_and_test*len(df))])

        self.save_gold_train_pandas_as_azure_dataset(train,train_percentage,label, new_version)
        self.save_gold_validate_pandas_as_azure_dataset(validate,left_per_set,label,new_version)
        self.save_gold_test_pandas_as_azure_dataset(test,left_per_set,label,new_version)
    
        return train,validate,test
    
    
    def split_gold_3_groupBy(self,train_percentage=0.6, label=None, groupBy=None, new_version=True, seed=42):

        df = self.Gold.to_pandas_dataframe()
        whats_left_for_both = round(1-train_percentage,1)  # 0.4 ...0.3 if 70%
        left_per_set = round((whats_left_for_both / 2),2) # 0.2  ...0.15
        validate_and_test = round((1-left_per_set),2) # 0.8 ....0.75

        train, validate, test = \
              np.split(df.sample(frac=1, random_state=seed), 
                       [int(train_percentage*len(df)), int(validate_and_test*len(df))])

        self.save_gold_train_pandas_as_azure_dataset(train,train_percentage,label, new_version)
        self.save_gold_validate_pandas_as_azure_dataset(validate,left_per_set,label,new_version)
        self.save_gold_test_pandas_as_azure_dataset(test,left_per_set,label,new_version)
    
        return train,validate,test

    def registerGold(self, azure_dataset, description, new_version):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
    
        t={"model":self.model_folder_name}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_name_azure, tags=t, description=description,create_new_version=new_version)
        self._gold_dataset = ds
        return self.Gold

#TRAIN, VALIDATE, TEST
    def registerGoldTrain(self, azure_dataset, description, split_percentage,label,new_version):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_train_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        
        t={"split_percentage": split_percentage, "label": label, "model":self.model_folder_name}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_train_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_train = ds
        return self.GoldTrain

    def registerGoldValidate(self, azure_dataset, description, split_percentage,label, new_version):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_validate_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        t={"split_percentage": split_percentage, "label": label,"model":self.model_folder_name}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_validate_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_validate = ds
        return self.GoldValidate

    def registerGoldTest(self, azure_dataset, description, split_percentage,label, new_version):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_test_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        t={"split_percentage": split_percentage, "label": label ,"model":self.model_folder_name}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_test_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_test= ds
        return self.GoldTest

    def registerGoldScored(self, azure_dataset, description,date_time_folder,  model_version,caller_id = None, new_version=True):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_scored_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        t={"date_time_folder":date_time_folder, "caller_id":caller_id, "model_version": model_version ,"model":self.model_folder_name}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_scored_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_scored = ds
        return self.GoldScored

    def registerGoldToScore(self, azure_dataset, description, date_time_folder, model_version, new_version=True):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_to_score_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        t={"date_time_folder":date_time_folder, "model_version": model_version,"model":self.model_folder_name}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_to_score_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_to_score = ds
        return self.GoldToScore

#TRAIN, VALIDATE, TEST
   
    def DatasetByName(self,ds_name):
        for d in self.dataset_list:
            if (d.Name == ds_name):
                return d
        raise LookupError("Dataset with name {} does not exists. \n Tip: Loop the ESMLProject.Dataset and print .Name property to see Dataset names you have")

#TODO 
    def get_gold_scored_datasets(self, date_time_folder,model_version, caller_id=None):
        ds_list = []
        df_list = []
        ds_version_found = False
        ds1_found_but_no_higher = False

        for i in range(1, 100): # Search 100 DATASET versions, or return latest
            i_str = str(i)
           
            if(ds1_found_but_no_higher == True):
                last_i = i-2
                #print("Last dataset-version {}, but no higher version after that, for model-version {} with filter {} & {}".format(str(last_i),model_version,date_time_folder,caller_id))
                break

            ds = None
            try:
                ds = Dataset.get_by_name(workspace = self.ws, # Standard Azure ML Dataset method
                                    name = self.GoldScored.name, 
                                    version = i)
            except Exception as e:
                if("Cannot find dataset registered with name" in e.message):
                    pass
                else:
                    raise e

            if (ds is not None):
                #print("Dataset version {} found".format(i_str))
                ds_version = i
                ds_version_found = True

                # Ok, we have a Dataset, but is it compatible -> correct model version, and correct FILTER -> same date
                tag_date_time_folder = None
                tag_model_version = None
                tags = ds.tags #  t={"date_time_folder":date_time_folder, "caller_id":caller_id, "model_version": model_version}
                try:
                    tag_date_time_folder = tags["date_time_folder"]
                    tag_model_version = tags["model_version"]
                    tag_caller_id = tags["caller_id"]
                except:
                    print("get_scored() - Cannot filter on date_time_folder. Will return LATEST instead")
                
                include_ds = True
                if (date_time_folder is not None): # Date filter
                    if(tag_date_time_folder != date_time_folder):
                        include_ds = False
                
                if (model_version is not None): # Model version filter
                    if(tag_model_version != model_version):
                        include_ds = False

                if (caller_id is not None): # Caller id filter
                    if(tag_caller_id != caller_id):
                        include_ds = False
                if(include_ds):
                    ds_list.append(ds)
                    df_list.append(ds.to_pandas_dataframe())
            else:
                if (ds_version_found == True):
                    ds1_found_but_no_higher = True

        if(not ds_list):
            ds = Dataset.get_by_name(workspace = self.ws, # Standard Azure ML Dataset method
                                    name = self.GoldScored.name, 
                                    version =  "latest")
            ds_list.append(ds)
            df_list.append(ds.to_pandas_dataframe())
            
        return ds_list, df_list
    
    def get_scored(self, date_time_folder="last_month",  model_version="1",caller_id = None):
        ds_list,df_list = self.get_gold_scored_datasets(date_time_folder,  model_version,caller_id) # scored_id is an optinal FILTER, else all is returned

        #df_all = pd.concat(df_list, axis=1) # columns
        df_all = pd.concat(df_list)
        return ds_list, df_all

#TODO end

    def get_gold_version(self, ds_version = 'latest'): 
         return Dataset.get_by_name(workspace = self.ws,
                                 name = self.Gold.name, 
                                 version = ds_version)
      
    def get_gold_validate_Xy(self,label=None, ds_version = 'latest'): # TODO - p.GoldTest.X.to_pandas_dataframe()# TODO: Get  label = "Y" from .json of run
        gt = Dataset.get_by_name(workspace = self.ws,
                                        name =  self.GoldValidate.name, #  'M03_GOLD_Validate'
                                        version = ds_version)
        if(label is None): # Try reading from TAGS
            try:
                label = gt.tags["label"]
            except:
                raise UserErrorException("You need to provide LABEL as argument, since Azure Dataset {} TAGS,  did not contain the label info.".format(self.GoldValidate.name))

        df_test = gt.to_pandas_dataframe()
        print("{} : {}".format(self.GoldValidate.name, df_test.shape))
        X_test = df_test.drop([label], axis=1)
        print("X_test ",X_test.shape)
        
        y_test = df_test[label]
        print("y_test ",y_test.shape)
        return X_test, y_test, gt.tags

    def get_gold_test_Xy(self,label=None, ds_version = 'latest'): # TODO - p.GoldTest.X.to_pandas_dataframe()# TODO: Get  label = "Y" from .json of run
        gt = Dataset.get_by_name(workspace = self.ws,
                                        name =  self.GoldTest.name, #  'M03_GOLD_TEST'
                                        version = ds_version)
        if(label is None): # Try reading from TAGS
            try:
                label = gt.tags["label"]
            except:
                raise UserErrorException("You need to provide LABEL as argument, since Azure Dataset {} TAGS,  did not contain the label info.".format(self.GoldTest.name))
        df_test = gt.to_pandas_dataframe()
        print("{} : {}".format(self.GoldTest.name, df_test.shape))
        X_test = df_test.drop([label], axis=1)
        print("X_test ",X_test.shape)
        
        y_test = df_test[label]
        print("y_test ",y_test.shape)
        return X_test, y_test, gt.tags

    def init(self,ws_in = None):
        ws = None
        if (ws_in is None):
            ws = self.ws # use its own default WS
        else:
            ws = ws_in

        if(ws != self.ws): # Connect to other DatatStore - even if its the same physical lake
            self._recreate_datastore = True
        self._suppress_logging = True
 
        return self.automap_and_register_aml_datasets(ws)

    def unregister_all_datasets(self,ws):
        self.set_lake_as_datastore(ws)
        old_mode = self.inference_mode
        try:
            self.unregister_all(ws)
            self.inference_mode = not self.inference_mode
            self.unregister_all(ws)
        finally:
            self.inference_mode = old_mode


    def unregister_all(self, ws):
        try:
            for ds in self.dataset_list:
                print("Unregister Azure ML dataset for ESML dataset {}".format(ds.Name))
                in_name, bronze_name, silver_name = self.create_dataset_names(ds.Name)
                
                print("- IN name: {}".format(in_name))
                try:
                    d1 = Dataset.get_by_name(ws, in_name)
                    d1.unregister_all_versions()
                except Exception as e:
                    if("Invalid tuple for path" not in e.message):
                        pass #raise e
    
                print("- Bronze name: {}".format(bronze_name))
                try:
                    d1 = Dataset.get_by_name(ws,bronze_name)
                    d1.unregister_all_versions()
                except Exception as e:
                     if("Invalid tuple for path" not in e.message):
                         #raise e
                         pass 

                print("- Silver name: {}".format(silver_name))
                try:
                    d1 = Dataset.get_by_name(ws, silver_name)
                    d1.unregister_all_versions()
                except Exception as e:
                    if("Invalid tuple for path" not in e.message):
                        #raise e
                        pass

            print("Gold name: {} ".format(self.dataset_gold_name_azure))
            try:
                d1 = Dataset.get_by_name(ws, self.dataset_gold_name_azure)
                d1.unregister_all_versions()
            except Exception as e:
                if("Invalid tuple for path" not in e.message):
                    pass #raise e
            # train, test, validate
            try:
                d1 = Dataset.get_by_name(ws, self.dataset_gold_train_name_azure)
                d1.unregister_all_versions()
                d1 = Dataset.get_by_name(ws, self.dataset_gold_validate_name_azure)
                d1.unregister_all_versions()
                d1 = Dataset.get_by_name(ws, self.dataset_gold_test_name_azure)
                d1.unregister_all_versions()

                d1 = Dataset.get_by_name(ws, self.dataset_gold_to_score_name_azure)
                d1.unregister_all_versions()
            except Exception as e:
                 if("Invalid tuple for path" not in e.message):
                     pass
            try:
                d1 = Dataset.get_by_name(ws, self.dataset_gold_scored_name_azure)
                d1.unregister_all_versions()
            except Exception as e:
                if("Invalid tuple for path" not in e.message):
                    pass #raise e

        except Exception as e2:
             if("Cannot find dataset registered with name" in e2.message):
                 print ("Dataset not found, cannot be unregistered")
             if("Invalid tuple for path" not in e2.message):
                raise UserErrorException("Error! Cannot unregister ESML datasets in Azure ML studio workspace for project ") from e2

    def automap_and_register_aml_datasets(self, ws, dataset_name = "", dataset_description_in=""):
        self.ws = ws

        temp_folder = '../../../../common/temp_data/{}/'.format(self.project_folder_name)
        #print("Cleaning local temp for project at: {}".format(temp_folder))
        ESMLProject.create_folder_if_not_exists(temp_folder)
        ESMLProject.clean_temp(self.project_folder_name)
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))

            if(self._suppress_logging == False):
                print("Register ES-ML Datastore...")
            lakestore = self.set_lake_as_datastore(ws)
            self.readActiveDatesFromLake()
            self.checkLakeCompatability()

            print("")
            print("Inference mode (False = Training mode):", self.inference_mode)
            print("Load data as Datasets....")

            exists_dictionary = defaultdict(list)
            # VERISONS samename  "ds01_diabetes". Specify `create_new_version=True` to register the dataset as a new version. 
            # Use `update`, `add_tags`, or `remove_tags` to change only the description or tags.
            error_path = ""
            try:
                for ds in self.dataset_list:
                    print(ds.Name)
                    # specify datastore paths dstore_paths = [(lakestore, 'weather/*/*/*/*/data.parquet')]
                    #dstore_paths = [(lakestore,  ds.BronzePath(0) + "*.parquet")]
                    #partition_format = 'weather/{state}/{in_date:yyyy/MM/dd}/data.parquet'  # specify partition format
                    #dset = Dataset.Tabular.from_parquet_files(path=dstore_paths, partition_format=partition_format) # create the Tabular dataset with 'state' and 'date' as virtual columns 
                    dataset_description = ""
                    dataset_description = dataset_description_in + " "+ ds.DatasetFolderName
                    #name = dataset_name

                    # IN folder / Azure dataset
                    error_path = ""
                    dstore_paths = [(lakestore,  ds.InPath + "*.csv")]
                    desc_in =  "IN: " + dataset_description
                    try:
                        error_path = ds.InPath
                        in_ds = Dataset.Tabular.from_delimited_files(path=dstore_paths,validate=False) # create the Tabular dataset with 
                        try:
                            exists_dictionary.setdefault(ds.Name, []).append("IN_Folder_has_files")
                            ds.registerIn(in_ds,desc_in,False)
                        except UserErrorException as e:
                            print("Wrong path | OR wrong format (if .csv conversion to .parquet will be made) | OR error at registering dataset '{}' in Azure, with description: {}. Inner exception:\n{} ".format(ds.Name,desc_in,e))
                    except Exception as e2: # Try .parquet instead - Else just throw exception
                        print("IN (.csv or .parquet) coult not be initiated  for dataset {} with description {}. Trying as .parquet instead.".format(ds.Name,desc_in))
                        
                        desc_in =  "IN_PQ: " + dataset_description
                        in_ds = None
                        try:
                            dstore_paths = [(lakestore,  ds.InPath + "*.parquet")]
                            in_ds = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=False) # create the Tabular dataset with 
                            ds.registerIn(in_ds,desc_in,False)
                        except Exception as e3:
                            dstore_paths = [(lakestore,  ds.InPath + "in.parquet/*.parquet")]
                            in_ds = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=False) # create the Tabular dataset with
                            ds.registerIn(in_ds,desc_in,False)
                            if("Cannot load any data from the specified path" not in e3.message):
                                raise e3
                            
                        #if("Cannot load any data from the specified path" not in e2.message):
                        #    raise e2
                        
                    # BRONZE folder / Azure dataset
                    desc_bronze =  "BRONZE: " + dataset_description
                    error_path = ds.BronzePath
                    path_parquet_part = ds.BronzePath + "bronze_dbx.parquet/"
                    try:
                        dstore_paths = [(lakestore,  ds.BronzePath + "*.parquet")]
                        bronze_ds = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=True) # create the Tabular dataset with 'state' and 'date' as virtual columns 
                        exists_dictionary.setdefault(ds.Name, []).append("BRONZE_Folder_has_files")
                    except Exception as e2:
                        dstore_paths = [(lakestore,  path_parquet_part + "*.parquet")]
                        try:
                            bronze_ds = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=False)
                            exists_dictionary.setdefault(ds.Name, []).append("BRONZE_Folder_has_files")
                        except Exception as e3:
                            if("Cannot load any data from the specified path" not in e3.message):
                                raise e3
                    
                    # SILVER folder / Azure dataset
                    silver_parquet_part = ds.SilverPath + "silver.parquet/"
                    error_path = ds.SilverPath
                    desc_silver =  "SILVER: " + dataset_description
                    try:
                        dstore_paths = [(lakestore,  ds.SilverPath + "*.parquet")]
                        ds_silver = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=True) # create the Tabular dataset with 'state' and 'date' as virtual columns 
                        try:
                            exists_dictionary.setdefault(ds.Name, []).append("SILVER_Folder_has_files")
                            ds.registerSilver(ds_silver,desc_silver,False)
                        except UserErrorException as e:
                            print("Wrong path / or error at registering dataset '{}' in Azure, with description: {}. Inner exception:\n{}".format(ds.name,desc_silver,e))
                    except Exception as e2:
                        try:
                            dstore_paths = [(lakestore, silver_parquet_part + "*.parquet")]
                            ds_silver = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=False) # create the Tabular dataset with 'state' and 'date' as virtual columns 
                            try:
                                exists_dictionary.setdefault(ds.Name, []).append("SILVER_Folder_has_files")
                                ds.registerSilver(ds_silver,desc_silver,False)
                            except UserErrorException as e:
                                print("Wrong path / or error at registering dataset '{}' in Azure, with description: {}. Inner exception:\n{}".format(ds.name,desc_silver,e))
                        except UserErrorException as e3:
                            if("Cannot load any data from the specified path" not in e3.message):
                                raise e3

            except Exception as e2:
                
                if("Cannot load any data from the specified path" not in e2.message):
                    if(self.inference_mode):
                        str_1 = "to IN-folder is successful. Check in lake if: correct model_version={} and correct date_folder".format(self.inferenceModelVersion)
                        str_2 = "\n Tip_2: Maybe data is deleted in lake? But dataset is still registered? Check here in the datalake with Storage Explorer: {}".format(error_path)

                        raise UserErrorException("Error! Please check that Dataset name you provied in ESMLProject contructor also matches datalake-folder-names setup by your ESML core team" \
                        ". \n Tip_1: Since INFERENCE MODE=TRUE, check that your Ingestion-pipeline (Azure Data factory) " + str_1 + str_2) from e2
                    else:
                        raise UserErrorException("Error! Please check that Dataset name you provied in ESMLProject contructor also matches datalake-folder-names setup by your ESML core team") from e2

            print("")
            print("####### Automap & Autoregister - SUCCESS!")
            print("1) Auto mapped {} ESML Dataset with registered Azure ML Datasets (potentially all 3: IN,BRONZE, SILVER) in Datastore {} ".format(str(len(exists_dictionary.items())), lakestore.name))
            #print(" - Existing files already? Status: {} ".format(exists_dictionary.items()))
            print("")
            for k in exists_dictionary:
                print("Dataset '{}' status:".format(k))
                for listItem in exists_dictionary[k]:
                    print(" - "+ listItem)
            print("")
            print("2) Registered each Dataset with suffixes (_IN, _BRONZE, _SILVER) \n Tip: Use ESMLProject.Datasets list or .DatasetByName(myDatasetName) to read/write")
            print("#######")
        finally:
            ESMLProject.clean_temp(self.project_folder_name) # Ensure empty
            os.chdir(old_loc)
        return lakestore

    # https://docs.microsoft.com/en-us/python/api/azureml-core/azureml.data.dataset_factory.tabulardatasetfactory?view=azure-ml-py#register-pandas-dataframe-dataframe--target--name--description-none--tags-none--show-progress-true-
    # register_pandas_dataframe(dataframe, target, name, description=None, tags=None, show_progress=True)
    # target: Required, the datastore path where the dataframe parquet data will be uploaded to. A guid folder will be generated under the target path to avoid conflict.
    
    def save_silver(self,esml_dataset, dataframe):
        return self.save_silver_pandas_as_azure_dataset(esml_dataset, dataframe)

    def save_silver_pandas_as_azure_dataset(self,esml_dataset, dataframe):
        srs_folder = '../../../../common/temp_data/{}/{}/Silver/{}/'.format(self.project_folder_name,esml_dataset.Name,self.dev_test_prod)
        target_path = esml_dataset.SilverPath
        file_name = "silver.parquet" #file_name = uuid.uuid4().hex
        local_path = '{}{}'.format(srs_folder,file_name)
        
        ESMLProject.create_folder_if_not_exists(srs_folder)
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            dataframe.to_parquet(local_path, engine='pyarrow', compression='snappy', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            esml_dataset.upload_and_register_pandas_silver(file_name,srs_folder, target_path)
        finally:
            ESMLProject.clean_temp(self.project_folder_name)
            os.chdir(old_loc)
        return esml_dataset.Silver

    def save_bronze(self,esml_dataset, dataframe):
        return self.save_bronze_pandas_as_azure_dataset(esml_dataset, dataframe)
        
    def save_bronze_pandas_as_azure_dataset(self,esml_dataset, dataframe):
        srs_folder = '../../../../common/temp_data/{}/{}/Bronze/{}/'.format(self.project_folder_name,esml_dataset.Name, self.dev_test_prod)
        target_path = esml_dataset.BronzePath
        file_name = "bronze.parquet" # uuid.uuid4().hex
        local_path = '{}{}'.format(srs_folder,file_name)

        try:
            ESMLProject.create_folder_if_not_exists(srs_folder)
            #dataframe.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))
            dataframe.to_parquet(local_path, engine='pyarrow',compression='snappy', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            # (PathConflict) The specified path, or an element of the path, exists and its resource type is invalid for this operation.
            esml_dataset.upload_and_register_pandas_bronze(file_name,srs_folder, target_path)
        finally:
            ESMLProject.clean_temp(self.project_folder_name)
            os.chdir(old_loc)
        return esml_dataset.Bronze

    @staticmethod
    def create_folder_if_not_exists(new_folder):
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            if not os.path.exists(new_folder):
                os.makedirs(new_folder)
                #os.chmod(srs_folder,0o755)
        finally:  # Create folder if not exists
            os.chdir(old_loc)
            
    
    @staticmethod
    def clean_automl_logs():
        old_loc = os.getcwd()

        try: # Clean ALL, first
            os.chdir(os.path.dirname(__file__))
            srs_folder1 = Path('../automl.log')
            srs_folder2 = Path('../azure_automl_debug_dev.log')
            srs_folder3 = Path('../azure_automl_debug_test.log')
            srs_folder4 = Path('../azure_automl_debug_prod.log')
            srs_folder5 = Path('../azureml_automl.log')

            srs_folder6 = Path('automl.log')
            srs_folder7 = Path('azure_automl_debug_dev.log')
            srs_folder8 = Path('azure_automl_debug_test.log')
            srs_folder9 = Path('azure_automl_debug_prod.log')
            srs_folder10 = Path('azureml_automl.log')

            srs_folder11 = Path('../../../notebook_demos/automl.log')
            srs_folder12 = Path('../../../notebook_demos/azure_automl_debug_dev.log')
            srs_folder13 = Path('../../../notebook_demos/azure_automl_debug_test.log')
            srs_folder14 = Path('../../../notebook_demos/azure_automl_debug_prod.log')
            srs_folder15 = Path('../../../notebook_demos/azureml_automl.log')

            if srs_folder2.is_file():
                os.remove(srs_folder2)
            if srs_folder3.is_file():
                os.remove(srs_folder3)
            if srs_folder4.is_file():
                os.remove(srs_folder4)
            if srs_folder5.is_file():
                os.remove(srs_folder5)
            if srs_folder7.is_file():
                os.remove(srs_folder7)
            if srs_folder8.is_file():
                os.remove(srs_folder8)
            if srs_folder9.is_file():
                os.remove(srs_folder9)
            if srs_folder10.is_file():
                os.remove(srs_folder10)
            if srs_folder12.is_file():
                os.remove(srs_folder12)
            if srs_folder13.is_file():
                os.remove(srs_folder13)
            if srs_folder14.is_file():
                os.remove(srs_folder14)
            if srs_folder15.is_file():
                os.remove(srs_folder15)

            # Files can be locked, and throws error...
            if srs_folder11.is_file():
                os.remove(srs_folder11)
            if srs_folder1.is_file():
                os.remove(srs_folder1)
            if srs_folder6.is_file():
                os.remove(srs_folder6)
        except Exception as e:
            #print(e)
            pass
        finally:
            os.chdir(old_loc)

    @staticmethod
    def clean_azureml_folder():
        old_loc = os.getcwd()

        try: # Clean ALL, first
            os.chdir(os.path.dirname(__file__))
            srs_folder = Path('.azureml')
            srs_folder2 = Path('../.azureml')
            srs_folder3 = Path('../../.azureml')
            srs_folder4 = Path('../../../.azureml')
            srs_folder5 = Path('../../../.azureml')
            srs_folder6 = Path('../../../notebook_demos/.azureml')
            srs_folder7 = Path('../../../../.azureml')
            try:
                if srs_folder.exists() and srs_folder.is_dir():
                    shutil.rmtree(srs_folder) # Delete all
            except: pass
            
            try:
                if srs_folder2.exists() and srs_folder2.is_dir():
                    shutil.rmtree(srs_folder2) # Delete all
            except: pass

            try:
                if srs_folder3.exists() and srs_folder3.is_dir():
                    shutil.rmtree(srs_folder3) # Delete all
            except:pass
            try:
                if srs_folder4.exists() and srs_folder4.is_dir():
                    shutil.rmtree(srs_folder4) # Delete all
            except:pass
            try:
                if srs_folder5.exists() and srs_folder5.is_dir():
                    shutil.rmtree(srs_folder5) # Delete all
            except:pass
            try:
                if srs_folder6.exists() and srs_folder6.is_dir():
                    shutil.rmtree(srs_folder6) # Delete all
            except:pass
            try:
                if srs_folder7.exists() and srs_folder7.is_dir():
                    shutil.rmtree(srs_folder7) # Delete all
            except:pass
        finally:
            os.chdir(old_loc)

    @staticmethod
    def clean_temp(project_folder_name):
        old_loc = os.getcwd()

        try: # Clean ALL, first
            os.chdir(os.path.dirname(__file__))
            srs_folder = '../../../../common/temp_data/'+project_folder_name
            source_dir = Path(srs_folder)
            if source_dir.exists() and source_dir.is_dir():
                try:
                    shutil.rmtree(source_dir) # Delete all
                    os.makedirs(srs_folder) # Create "root" folder
                except OSError as e:
                    print("....")
                    #print("Error: %s : %s" % (srs_folder, e.strerror))
        except Exception as e:
            raise e
        finally:  # Create folder if not exists
            os.chdir(old_loc)
    @staticmethod
    def get_project_from_env_command_line():
        parser = argparse.ArgumentParser()
        parser.add_argument('--esml_environment', type=str, help='ESML target environment: dev,test,prod')
        parser.add_argument('--esml_inference_model_version', type=str, help='Model VERSION to score with')
        parser.add_argument('--esml_scoring_in_datetime', type=str, help='IN folder, datetype:datetime - the data to SCORE, same datetime as prestep Bronze2Gold pipeline')
        parser.add_argument('--esml_train_in_datetime', type=str, help='IN folder. datetype:datetime - the data to RETRAIN model on, same datetime as prestep Bronze2Gold pipeline')
        
        args = parser.parse_args()
        esml_environment = args.esml_environment
        inference_model_version = args.esml_inference_model_version
        scoring_folder_date = args.esml_scoring_in_datetime
        train_in_folder_date = args.esml_train_in_datetime

        p = None
        if((esml_environment is not None) and (inference_model_version is None)):
            print("Scenario 01: MLOPS - RETRAIN on same data, code changed - The argparse (Azure Devops) variable 'esml_environment ' (dev, test or prod) is set to: {}".format(esml_environment))
            p = ESMLProject(esml_environment)
        elif((esml_environment is not None) and (inference_model_version is not None) and (scoring_folder_date is not None)):
            inf_int = int(inference_model_version)
            if (inf_int <0):
                raise UserErrorException("If Scenario 02: SCORING pipeline with dynamic data - inference_model_version must be set, and 0 or positive. It is now {}".format(inference_model_version))

            print("Scenario 02: SCORING pipeline with dynamic data.  Env:{} | Version: {} | Scoring data: {}".format(esml_environment,inference_model_version,scoring_folder_date))
            p = ESMLProject(esml_environment,inference_model_version,scoring_folder_date,train_in_folder_date)
        elif((esml_environment is not None) and (train_in_folder_date is not None) and (inference_model_version is not None)):  # inference_model_version <0
            inf_int = int(inference_model_version)
            if (inf_int >=0):
                raise UserErrorException("If Scenario 03: RETRAINING pipeline with dynamic data - inference_model_version must be set, and negative. It is now {}".format(inference_model_version))

            print("Scenario 03: RETRAINING pipeline with dynamic data. Env:{} | Version: {} | Train data: {}".format(esml_environment,inference_model_version,train_in_folder_date))
            p = ESMLProject(esml_environment,inference_model_version,scoring_folder_date,train_in_folder_date)
        else: # Default 
            p = ESMLProject()
            print("args.esml_environment is None. Reading environment from config-files")
        return p

class ESMLDataset():
    #Defaults - project specicfic examples
    project_folder_name = "project002"
    model_folder_name = "03_diabetes_model_reg"
    model_aml_dataset_prefix = "M01"
    ds_name = "ds01_diabetes_ASDF"
    dataset_inference_suffix = "_inference_"

    # AZURE Datasets
    _in_train = None
    _in_inference = None
    _bronze_train = None
    _bronze_inference = None
    _silver_train = None
    _silver_inference = None
    #Names 
    _nameAzurePrefix = None
    _silver_name_azure = ""
    _bronze_name_azure = ""
    _in_name_azure = ""


    # Lake folders -  master/1_projects/project002/03_diabetes_model_reg/train/ds01_diabetes/out/bronze/
    # TODO: To include files in subfolders, append '/**' after the folder name like so: '{Folder}/**'.
    #_train_path_template = "master/1_projects/{}/{}/train/{}/{}/{}/{}/"
    _train_path_template = "{}/{}/{}/train/{}/{}/{}/{}/"
    _in_path_train = ""
    _in_path_inference = ""
    _bronze_path_train = ""
    _silver_path_train = ""

    _inference_path_template = "{}/{}/{}/inference/{}/{}/{}/{}/{}/"
    _bronze_path_inference = ""
    _silver_path_inference= ""

    # Compute power
    _cpu_gpu_databricks = "cpu"
    _runconfig = None # Can be set manually, if None default is set

    # Script names
    _in2bronze_prefix = "in2bronze"
    _bronze2silver_prefix = "bronze2silver"
    _in2silver_prefix = "in2silver"

    # GLOBAL
    inferenceModelVersion = 0
    _project = None
      
    def __init__(self,project, inferenceModelVersion, project_folder_name,model_folder_name,ds01_name): 
        self._project = project

        self.inferenceModelVersion = inferenceModelVersion
        self.project_folder_name = project_folder_name 
        self.model_folder_name = model_folder_name
        self.ds_name = ds01_name  

        # Lake - physical folders paths
            # IN
        self._in_path_inference = self._inference_path_template.format(self._project._proj_start_path, self.project_folder_name,self.model_folder_name, self.inferenceModelVersion,self.ds_name  ,"in",project.dev_test_prod,project.date_scoring_folder.strftime('%Y_%m_%d'))
        self._in_path_train = self._train_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.ds_name ,"in",project.dev_test_prod, project.InDateFolder)
            
            # OUT
        self._bronze_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name, self.inferenceModelVersion,self.ds_name  ,"out","bronze",project.dev_test_prod)
        self._silver_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.inferenceModelVersion,self.ds_name  , "out","silver",project.dev_test_prod)

        self._bronze_path_train = self._train_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.ds_name ,"out", "bronze",project.dev_test_prod)
        self._silver_path_train = self._train_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.ds_name ,"out", "silver",project.dev_test_prod)

# Get methods
    def get_bronze_version(self,ds_version): 
        return Dataset.get_by_name(
            workspace = self._project.ws,
            name = self.Bronze.name,
            version = ds_version)
    def get_silver_version(self,ds_version): 
        return Dataset.get_by_name(
            workspace = self._project.ws,
            name = self.Silver.name,
            version = ds_version)
    def get_indata_version(self,ds_version): 
        return Dataset.get_by_name(
            workspace = self._project.ws,
            name = self.InData.name,
            version = ds_version)
# GET/SET

    @property
    def in2bronze_filename(self):
        return self._in2bronze_prefix +"_"+ self.Name + ".py"
    @property
    def bronze2silver_filename(self):
        return self._bronze2silver_prefix +"_"+ self.Name + ".py"
    @property
    def in2silver_filename(self):
        return self._in2silver_prefix +"_"+ self.Name + ".py"

    @property
    def runconfig(self):
        return self._runconfig
    
    @runconfig.setter
    def runconfig(self, runconfig):
        self._runconfig = runconfig

    @property
    def cpu_gpu_databricks(self):
        return self._cpu_gpu_databricks
    @cpu_gpu_databricks.setter
    def cpu_gpu_databricks(self, cpu_gpu_databricks):
        self._cpu_gpu_databricks = cpu_gpu_databricks

# TODO: Same as GOLD, if versioning needed for this. For now - save storage
    @property
    def NameAzurePrefix(self):
        if(self._project.inference_mode):
            self._nameAzurePrefix = self._project.ModelAlias +"_"+self.ds_name+self.dataset_inference_suffix
        else:    
            self._nameAzurePrefix = self._project.ModelAlias +"_"+self.ds_name+"_train_"
        return self._nameAzurePrefix
    
    @property
    def BronzeDatabricks(self):
        return Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "bronze_dbx.parquet/*.parquet")],validate=False)

    @property
    def Bronze(self):
        try:
            if(self._project.inference_mode):
                if (self._bronze_inference is None): #Lazy load
                    try:
                        self._bronze_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "*.parquet")],validate=False)
                    except:
                        self._bronze_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "bronze_dbx.parquet/*.parquet")],validate=False)
                return self._bronze_inference # return cached. 
            else:
                if (self._bronze_train is None): # Lazy load
                    try:
                        self._bronze_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "*.parquet")],validate=True)
                    except:
                        self._bronze_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "bronze_dbx.parquet/*.parquet")],validate=False)
                return self._bronze_train
        except Exception as e:
            print("--------------- Bronze ---------------")
            if("Cannot load any data from the specified path" in e.message):
                print("--------------- Bronze2 ---------------")
                raise UserErrorException("ESML Bronze folder in lake seems to be empty."\
                 "\n Tip: Is there any data (.csv) in IN-folder for specific date-folder path?"\
                 "Why I'm asking? Because if data exists in IN-folder,"\
                 "this will automatically be converted from .csv to .parquet copied to OUT/BRONZE. No there is nothing here: {}".format(self.BronzePath)) from e

    @Bronze.setter
    def Bronze(self, bronze_azure_dataset):
        if(self._project.inference_mode):
            self._bronze_inference = bronze_azure_dataset
        else:
            self._bronze_train = bronze_azure_dataset
    
    @property
    def SilverDatabricks(self):
        return Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "silver_dbx.parquet/*.parquet")],validate=False)

    @property
    def Silver(self):
        if(self._project.inference_mode):
            if (self._silver_inference is None): #Lazy load - only 1 version supported. Always overwrite
                try:
                    self._silver_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "*.parquet")],validate=False)
                except:
                    self._silver_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "silver_dbx.parquet/*.parquet")],validate=False)
            return self._silver_inference
        else:
            if (self._silver_train is None): # Lazy load
                try:
                    self._silver_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "*.parquet")],validate=False)
                except:
                    self._silver_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "silver_dbx.parquet/*.parquet")],validate=False)
            return self._silver_train
   
    @Silver.setter
    def Silver(self, silver_azure_dataset):
        if(self._project.inference_mode): # Inference path
            self._silver_inference = silver_azure_dataset
        else:
            self._silver_train = silver_azure_dataset

    @property
    def InData(self):
        if(self._project.inference_mode): # Inference path
             if (self._in_inference is None): #Lazy load
                try:
                    self._in_inference = Dataset.Tabular.from_delimited_files(path = [(self._project.Lakestore, self.InPath + "*.csv")],validate=False,separator=',')
                except Exception as e:
                    print("ESML Note: Could not read InData (Scoring) as .CSV - Now trying as .PARQUET instead.")
                    try:
                        self._in_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.InPath + "*.parquet")],validate=False)
                    except:
                        print("It seems NOT to be a single.parquet file, but a partitioned file  (created from Spark maybe?) 'myfile.parquet/part-000.snappy.parquet' with folder") 
                        print("- Now trying as partioned .PARQUET instead. Note: You need to name your parquet file to 'in.parquet' that becomes the folder-name")
                        self._in_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.InPath + "in.parquet/*.parquet")],validate=False)
             return self._in_inference
        else:
            if (self._in_train is None): # Lazy load
                try:
                    self._in_train = Dataset.Tabular.from_delimited_files(path = [(self._project.Lakestore, self.InPath + "*.csv")],validate=False,separator=',')
                except Exception as e:
                    print("ESML Note: Could not read InData as .CSV - Now trying as .PARQUET instead.")
                    try:
                        self._in_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.InPath + "*.parquet")],validate=False)
                    except:
                        print("It seems NOT to be a single.parquet file, but a PARTITIONED parquet (created from Spark maybe?) 'myfile.parquet/part-000.snappy.parquet' with folder") 
                        print("- Now trying as partioned .PARQUET instead. Note: You need to name your parquet file to 'in.parquet' that becomes the folder-name")
                        self._in_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.InPath + "in.parquet/*.parquet")],validate=False)
            return self._in_train

    @InData.setter
    def InData(self, in_azure_dataset):
        if(self._project.inference_mode):
            df_csv = self.InData.to_pandas_dataframe() 
            if ( 'Unnamed: 0' in df_csv): # Fix crap savings of CSV (using Spark CSV-driver or Excel, forgetting Index=False at save etc) 
                df_csv = df_csv.drop('Unnamed: 0', axis=1)
                df_csv.reset_index(drop=True, inplace=True)
            self._in_inference = in_azure_dataset
            self.Bronze = self._project.save_bronze_pandas_as_azure_dataset(self, df_csv) # Auto-set BRONZE
        else:
            df_csv = self.InData.to_pandas_dataframe() 
            if ( 'Unnamed: 0' in df_csv): # Fix crap savings of CSV (using Spark CSV-driver or Excel, forgetting Index=False at save etc) 
                df_csv = df_csv.drop('Unnamed: 0', axis=1)
                df_csv.reset_index(drop=True, inplace=True)
            self._in_train = in_azure_dataset
            self.Bronze = self._project.save_bronze_pandas_as_azure_dataset(self, df_csv) # Auto-set BRONZE

# SAVE DATA - 
    def upload_and_register_pandas_bronze(self,file_name, srs_folder, target_path,new_version=False):
        self._project.LakeAccess.upload(file_name,srs_folder, target_path, overwrite=True) # GEN 2

        try:
            self.Bronze = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "*.parquet")],validate=False)
        except: 
            self.Bronze = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "bronze_dbx.parquet/*.parquet")],validate=False)
        self.registerBronze(self.Bronze,"BRONZE from refinement",new_version)
        return self.Bronze

    def upload_and_register_pandas_silver(self,file_name, srs_folder, target_path,new_version=False):
        self._project.LakeAccess.upload(file_name,srs_folder, target_path, overwrite=True) # GEN 2

        try:
            self.Silver = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "*.parquet")],validate=False)
        except:
            self.Silver = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "silver.parquet/*.parquet")],validate=False)
        description = "SILVER from refinement"
        self.registerSilver(self.Silver, description,new_version)
        return self.Silver


    def registerIn(self,azure_dataset, description,new_version=True):
        if(self._project.inference_mode):
            self._in_name_azure = self._project.ModelAlias +"_"+self.ds_name+self.dataset_inference_suffix + "IN"
        else:
            self._in_name_azure = self._project.ModelAlias +"_"+self.ds_name+"_train_IN"
        ESMLDataset.unregister_if_rnd(self._project.ws,self._project.rnd,self._in_name_azure )
        
        if(self._project.rnd == False):
            new_version = True
        ds_in = azure_dataset.register(workspace=self._project.ws,name=self._in_name_azure, description=description, create_new_version=new_version)
        self.InData = ds_in

    def registerBronze(self,azure_dataset, description,new_version=True):
        
        if(self._project.inference_mode):
            self._bronze_name_azure = self._project.ModelAlias +"_"+self.ds_name+self.dataset_inference_suffix + "BRONZE"
        else: 
            self._bronze_name_azure = self._project.ModelAlias +"_"+self.ds_name+"_train_BRONZE"

        ESMLDataset.unregister_if_rnd(self._project.ws,self._project.rnd,self._bronze_name_azure)
        if(self._project.rnd == False):
            new_version = True # yes, if not..There is already a dataset registered under name
        ds = azure_dataset.register(workspace=self._project.ws,name=self._bronze_name_azure, description=description, create_new_version=new_version)
        self.Bronze = ds

    def registerSilver(self,azure_dataset, desc_silver,new_version=True):
        if(self._project.inference_mode):
            self._silver_name_azure = self._project.ModelAlias +"_"+self.ds_name+self.dataset_inference_suffix + "SILVER"
        else:    
            self._silver_name_azure = self._project.ModelAlias +"_"+self.ds_name+"_train_SILVER"
        ESMLDataset.unregister_if_rnd(self._project.ws,self._project.rnd,self._silver_name_azure)
        if(self._project.rnd == False):
            new_version = True # # yes, if not..error, need to use UPDATE 
        ds_silver = azure_dataset.register(workspace=self._project.ws,name=self._silver_name_azure, description=desc_silver,create_new_version=new_version)
        self.Silver = ds_silver

    @staticmethod
    def unregister_if_rnd(ws,rnd,name):
        try:
            ds_found = Dataset.get_by_name(workspace=ws,name=name)
            if(rnd):
                print("Since R&D setting - unregister dataset {}, before register again".format(name))
                ds_found.unregister_all_versions()
                #ds_found.update(description="RND Phase. No versioning. Latest only", tags={"ESML-RnD": "true"})
            else:
                pass #ds_found.update(description="Production phase. Versioning enabled", tags={"ESML-RnD": "false"})
        except UserErrorException as e1:
            if("Cannot find dataset registered with name" in e1.message):
                return
            else:
                raise e1


#READ ONLY- with logic of "Version folder for inference"

    @property
    def AzureName_IN(self):
        return self.NameAzurePrefix + "IN"
    @property
    def AzureName_Bronze(self):
        return self.NameAzurePrefix + "BRONZE"

    @property
    def AzureName_Silver(self):
        return self.NameAzurePrefix + "SILVER"

    @property
    def InPathTemplate(self):
        if(self._project.inference_mode):
            self._in_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name, "{inference_model_version}",self.ds_name  ,"in","{dev_test_prod}","{folder_date}")
            return self._in_path_inference
        else:
            self._in_path_train = self._train_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.ds_name ,"in","{dev_test_prod}","{folder_date}")
            return self._in_path_train

    @property
    def InPath(self):
        if(self._project.inference_mode):
            self._in_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name, self.inferenceModelVersion,self.ds_name  ,"in",self._project.dev_test_prod,self._project.date_scoring_folder.strftime('%Y/%m/%d'))
            return self._in_path_inference
        else:
            self._in_path_train = self._train_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.ds_name ,"in",self._project.dev_test_prod,self._project.InDateFolder)
            return self._in_path_train
   
    @property
    def BronzePathTemplate(self):
        if(self._project.inference_mode):
            self._bronze_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name, "{inference_model_version}",self.ds_name  ,"out","bronze","{dev_test_prod}")
            return self._bronze_path_inference
        else:
            return self._bronze_path_train

    @property
    def BronzePath(self):
        if(self._project.inference_mode):
            self._bronze_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name, self.inferenceModelVersion,self.ds_name  ,"out","bronze",self._project.dev_test_prod)
            return self._bronze_path_inference
        else: 
            return self._bronze_path_train
        
    @property
    def SilverPath(self):
        if(self._project.inference_mode):
            self._silver_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.inferenceModelVersion,self.ds_name ,"out", "silver",self._project.dev_test_prod)
            return self._silver_path_inference
        else:
            return self._silver_path_train

    # Helper method, for "descrbibe"
    @property
    def InPath_Scoring(self):
        active_mode = self._project.inference_mode
        in_path = ""
        try:
            self._project.inference_mode = True
            in_path = self.InPath
        finally:
            self._project.inference_mode = active_mode
        return in_path

    # Helper method, end

       
    @property
    def DatasetFolderName(self):
        return self.ds_name
    @property
    def Name(self):
        return self.ds_name