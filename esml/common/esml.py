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
import json
import sys
import os
import math
from typing import SupportsComplex
from azureml.core.dataset import Dataset 
from azureml.core import Workspace
from azureml.core import Datastore
from azureml.exceptions import UserErrorException
from azureml.exceptions import ProjectSystemException
from storage_factory import LakeAccess
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

class ESMLProject():
    ws = None
    datastore = None
    lake_config = None
    env_config = None
    
    _gold_dataset = None
    _gold_train = None
    _gold_validate = None
    _gold_test = None
    _gold_scored = None
        
    project_folder_name = "project"
    model_folder_name = "kalle"
    dataset_folder_names = None
    dataset_list = []
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
    compute_factory = None
    automl_factory = None
    demo_mode = True
    multi_output = None
    
    def __init__(self, dev_test_prod=None):
        self.demo_mode = False # dont change this
        
        if(dev_test_prod is not None): # Override config with esml_environment parameter (for MLOps)
            if (dev_test_prod in ["dev","test","prod"]):
                self.ReloadConfiguration() # from config
                self.dev_test_prod = dev_test_prod # overrides config
                self.initDatasets(self.inferenceModelVersion, self.project_folder_name,self.model_folder_name,self.dataset_folder_names) 
            else:
                raise Exception("dev_test_prod parameter, must be either [dev,test,prod]")
        else: # Load from config
            self.ReloadConfiguration()
            self.initDatasets(self.inferenceModelVersion, self.project_folder_name,self.model_folder_name,self.dataset_folder_names)

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

        print("Training GOLD \n")
        print(self.GoldPath)
        print(" \n")

        print("ENVIRONMENT - DEV, TEST, or PROD?")
        print("ACTIVE ENVIRONMENT = {}".format(self.dev_test_prod))
        print("ACTIVE subscription = {}".format(self.subscription_id))
        print("-",self.resource_group)
        print("-",self.workspace_name)
        
        print("-",self.location)
        print("-", self.common_rg_name)

        rg_name, vnet_name, subnet_name = self.vNetForActiveEnvironment()
        print("Active vNet:", vnet_name)
        print("Active SubNet -",subnet_name)
        print("AML for docker:",self.use_aml_cluster_to_build_images)
        
    #Register - at Initiation, and when saving
    def create_dataset_names(self, datasetName):
        self._in_name_azure = self.ModelAlias +"_"+datasetName+"_IN"
        self._bronze_name_azure = self.ModelAlias +"_"+datasetName+"_BRONZE"
        self._silver_name_azure = self.ModelAlias +"_"+datasetName+"_SILVER"
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
            with open("../settings/active_dev_test_prod.json", "w") as f:
                json.dump(data, f)
        except Exception as e:
            raise ValueError("ESMLProject.save_active_env - could not write active_dev_test_prod.json") from e
        finally: 
            os.chdir(old_loc) # Change back working location...

    def parseConfig(self, lake_config):
        self.lake_config = lake_config
        self.projectNumber = self.lake_config['project_number']
        self.project_folder_name = self.lake_config['project_folder_name']
        
        self._modelNumber = self.lake_config['model_number']
        self._modelNrString = self.model_int_to_string()
        self.model_folder_name = self.lake_config['model_folder_name'] #2_prod/1_projects/project005/00_titanic_model/train/ds01_titanic/out/bronze/
        self.dataset_folder_names = self.lake_config['dataset_folder_names'] 
        self._model_short_alias = self.lake_config['model_short_alias']
        self._model_number = self.lake_config['model_number']

    def parseDateFolderConfig(self, date_in_folder, scoring):
        date_string = date_in_folder["{}_in_folder_date".format(self.dev_test_prod)] # String in DateTime format
        date_infolder = datetime.datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S.%f') # DateTime
        self._in_folder_date = date_infolder.strftime('%Y/%m/%d') #  String 2020/01/01

        date_str = scoring["{}_scoring_folder_date".format(self.dev_test_prod)] # String in DateTime format
        date_scoring_folder = datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S.%f') # DateTime
        self._in_scoring_folder_date = date_scoring_folder.strftime('%Y/%m/%d') #  String 2020/01/01
        self.inferenceModelVersion = int(scoring['{}_inference_model_version'.format(self.dev_test_prod)])

    def checkLakeCompatability(self):
        try:
            lake_paths = [(self.Lakestore, "active")]
            ds_train_json = Dataset.Tabular.from_json_lines_files(lake_paths, validate=False, include_path=False, set_column_types=None, partition_format=None, invalid_lines='error', encoding='utf8')
            df = ds_train_json.to_pandas_dataframe()

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
            print("ESML in-folder settings override = FALSE. [active_in_folder.json,active_scoring_in_folder.json] not found. \n - Using [active_in_folder.json,active_scoring_in_folder.json] from ArgParse or GIT. No override from datalake settings")
            print(e.message)
        finally:
            os.chdir(old_loc) # Switch back to callers "working dir"

    def parseEnvConfig(self, env_config):
        self.overrideEnvConfig(env_config['active_dev_test_prod'],env_config) # Sets ACTIVE subscription also

    def vNetForActiveEnvironment(self):
        rg_name,vnet_name, subnet_name = None,None,None

        if(self.lake_storage_accounts == 1): # 1 lake for all -> ignore dev_test_prod
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

    def overrideEnvConfig(self, dev_test_prod_to_activate,env_config): 
        self._dev_test_prod = dev_test_prod_to_activate
        
        #if (self.dev_test_prod != dev_test_prod_to_activate): # ONLY set this again, IF different...otherwise "loop of infintiy"
        #    print("self.dev_test_prod != dev_test_prod_to_activate")
        #    self.dev_test_prod = dev_test_prod_to_activate  # Sets ACTIVE subscription also

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

        self.lake_name = self.env_config['lake_name']
        self.lake_design_version = self.env_config['lake_design_version']

        self.common_rg_name = self.env_config['common_rg_name'].format(self.dev_test_prod.upper())
        self.common_vnet_name = self.env_config['common_vnet_name'].format(self.dev_test_prod)
        self.common_subnet_name = self.env_config['dev_common_subnet_name']

        if((len(self.common_subnet_name) > 0)): # At least DEV is set
            if ("{}" in self.common_subnet_name):
                self.active_common_subnet_name = self.common_subnet_name.format(self.dev_test_prod)
            else:
                self.active_common_subnet_name = self.common_subnet_name
        
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
        return self.datastore
    
    def get_best_model(self, ws,pipeline_run=False):
        self.initAutoMLFactory()
        return self.automl_factory.get_best_model(self,pipeline_run)

    def get_training_aml_compute(self,ws, use_non_model_specific_cluster=False, create_cluster_with_suffix_char=None):
        self.initComputeFactory(ws)
        
        if(use_non_model_specific_cluster==True):
            print("Using a non model specific cluster (enterprice policy cluster), yet environment specific")
            compute,name = self.compute_factory.get_training_aml_compute(self.dev_test_prod, self.override_enterprise_settings_with_model_specific,self._projectNoString,self._modelNrString,create_cluster_with_suffix_char)
            self.use_compute_cluster_to_build_images(ws, name)
            return compute

        else:
            print("Using a model specific cluster, per configuration in project specific settings, (the integer of 'model_number' is the base for the name)")
            compute,name = self.compute_factory.get_training_aml_compute(self.dev_test_prod, self.override_enterprise_settings_with_model_specific,self._projectNoString,self._modelNrString,create_cluster_with_suffix_char)
            self.use_compute_cluster_to_build_images(ws, name)
            return compute

    '''
    def get_latest_model(self, ws):
        if(self.automl_factory is None):
             self.automl_factory = AutoMLFactory(self)
        return self.automl_factory.get_latest_model(ws)
    '''

    def initComputeFactory(self,ws,reload_config=False):
        if(reload_config==True): # Force recreate, reload config
            self.compute_factory = ComputeFactory(self,ws,self.dev_test_prod,self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)

        if (self.compute_factory is not None): #Only switch to a new FACTORY is existing, and if ws changed.
           if (self.ws is not None and self.ws != ws): # If WORKSPACE switches, "create a new ComputeFactory"
                self.compute_factory = ComputeFactory(self,ws,self.dev_test_prod,self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)
        else: # Just create a factory
            self.compute_factory = ComputeFactory(self,ws,self.dev_test_prod,self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)

    @staticmethod
    def call_webservice_own_url(pandas_X_test, api_uri,api_key,firstRowOnly=True):
        return ComputeFactory.call_webservice_static(pandas_X_test, api_uri,api_key,firstRowOnly)

    '''
    ESML - This will also cache the scored results to DATALAKE,   IF `inference_model_version=1` in `settings/project_specific/lake_settings.json`
    '''
    def call_webservice(self,ws, pandas_X_test,user_id=None, firstRowOnly=False,inference_model_version=None, reload_config=True):
        self.initComputeFactory(ws,reload_config)

        df_result,model_version = self.compute_factory.call_webservice(pandas_X_test,firstRowOnly) # TODO: Use inference_model_version to pick webservice/model version, other than the "single one & latest"
        
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

    # Returns [service,api_uri, self.kv_aks_api_secret] - the api_secret is stored in your keyvault
    def deploy_automl_model_to_aks(self, model,inference_config, overwrite_endpoint=True,deployment_config=None):

        if(model is None):
            print("Model is none - nothing to deploy")
            return None
        else:
            print("Deploying model: {} with verison: {} to environment: {} with overwrite_endpoint={}".format(model.name, model.version, self.dev_test_prod,overwrite_endpoint))
        target_workspace = self.get_other_workspace(self.dev_test_prod)
        self.initComputeFactory(target_workspace)

        self.use_compute_cluster_to_build_images(target_workspace,self.compute_factory.aml_cluster_name)
        if(overwrite_endpoint):
            self.compute_factory.delete_aks_endpoint(target_workspace)
        return self.compute_factory.deploy_online_on_aks(self,model,inference_config, self.dev_test_prod,deployment_config, self.override_enterprise_settings_with_model_specific, self._projectNoString,self._modelNrString)

    def initAutoMLFactory(self):
        if(self.automl_factory is None):
            self.automl_factory = AutoMLFactory(self)

    def get_active_model_inference_config(self, ws):
        self.initAutoMLFactory()
        if(self.compute_factory is None):
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
    def verbose_logging(self):
        return self._verbose_logging

    @verbose_logging.setter
    def verbose_logging(self, enable_verbose_logging):
        self._verbose_logging = enable_verbose_logging

    @property
    def ComputeFactory(self):
        self.initComputeFactory(self.ws, reload_config=True)
        return self.compute_factory
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
    def Gold(self): 
        # TODO: Load LATEST version folder. Solution: Singelton...always have in memory
        # TODO: To include files in subfolders, append '/**' after the folder name like so: '{Folder}/**'.
        try:
            if (self._gold_dataset is None): # Lazy load 1st version 
                #self._gold_dataset = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPath + "*.parquet")])
                self._gold_dataset = Dataset.get_by_name(self.ws, name=self.dataset_gold_name_azure)
            return self._gold_dataset # Latest version
        except UserErrorException as e1:
            if("Cannot load any data from the specified path" in e1.message):
                raise UserErrorException("ESML GOLD dataset seems to be empty? Have you saved any data yet? use ESMLProject.save_gold_pandas_as_azure_dataset(df)") from e1
    @property
    def GoldPath(self): # TODO: Load LATEST version folder
         if(self.inferenceModelVersion > 0):
            return self._inference_gold_path.format(self.project_folder_name,self.model_folder_name,self.inferenceModelVersion, self.dev_test_prod)
         else:
            return self._train_gold_path.format(self.project_folder_name,self.model_folder_name, self.dev_test_prod)
    @property
    def ScoredPath(self): # TODO: Load LATEST version folder
        return self._inference_scored_path.format(self.project_folder_name,self.model_folder_name,self.inferenceModelVersion, self.dev_test_prod)

    def get_workspace_from_config(self,cli_auth=None, vNetACR=True):
        try:
            if(cli_auth is None):
                return Workspace.from_config(path="../../../", _file_name= self.get_workspace_configname())
            else:
                return Workspace.from_config(path="../../../", auth=cli_auth, _file_name= self.get_workspace_configname())
        except:
            try:
                if(cli_auth is None):
                    return Workspace.from_config(path="../../", _file_name= self.get_workspace_configname())
                else:
                    return Workspace.from_config(path="../../", auth=cli_auth, _file_name= self.get_workspace_configname())
            except Exception as e:
                raise UserErrorException("Config could not be found neither 3 or 2 folders, via: Workspace.from_config(path=../../, auth=cli_auth, _file_name= self.get_workspace_configname())") from e

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

            ESMLProject.clean_temp(self.project_folder_name)

            # 1) To score: Generate LAKE-path, what to READ, what to SCORE?
            day_folder = self.GoldPath + date_folder + '/'
            unique_folder = self.GoldPath + date_folder + '/'+unique_folder + "/"
            srs_folder = './common/temp_data/{}/inference/{}/Gold/'.format(self.project_folder_name,v_str)
            local_path = '{}{}'.format(srs_folder,file_name_to_score)
            ESMLProject.create_folder_if_not_exists(srs_folder)

            # 2) Score ComputeFactory + PipelineFactory
            pandas_X = None
            df_result = None
            df_result,model_version = self.compute_factory.batch_score(unique_folder, file_name_to_score) # A unique folder, a day
            df_result,model_version = self.compute_factory.batch_score(day_folder, file_name_to_score) # A datetime folder (usually a day, hour, minute)

            # 3) Save scored result
            scored_result = pandas_X.join(df_result)
            if(self.rnd == True): # No caching/saving to lake if R&D
                print("R&D - Do not save scoring to lake")
                return scored_result
            
            unique_folder = self.ScoredPath + date_folder + '/'+ unique_folder + "/"
            srs_folder = './common/temp_data/{}/inference/{}/Scored/'.format(self.project_folder_name,v_str)
            file_name = "scored.parquet" # Score all
            if(specific_file_guid is not None): # Score specific / Filter
                file_name = "scored_{}.parquet".format(specific_file_guid) # HERE ....who is this scoring about?

            local_path = '{}{}'.format(srs_folder,file_name)
            ESMLProject.create_folder_if_not_exists(srs_folder)
            scored_result.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            self.LakeAccess.upload(file_name, srs_folder, unique_folder, overwrite=True,use_dataset_factory = False) # BLOB or GEN 2

            print("Saved SCORED data in LAKE, as file '{}'".format(file_name))
        except Exception as e:
            raise e
        finally:
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
            now = datetime.datetime.now()
            date_folder = now.strftime('%Y_%m_%d') 
            same_guid_folder = uuid.uuid4().hex
            ESMLProject.clean_temp(self.project_folder_name)

            # 2) Save pandas_X_test to goldpath
            unique_folder = self.GoldPath + date_folder + '/'+same_guid_folder + "/"
            srs_folder = './common/temp_data/{}/inference/{}/Gold/'.format(self.project_folder_name,v_str)
            file_name = "to_score_{}.parquet".format(caller_guid) # HERE ....who is this scoring about?
            local_path = '{}{}'.format(srs_folder,file_name)
            ESMLProject.create_folder_if_not_exists(srs_folder)
            pandas_X_test.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            self.LakeAccess.upload(file_name, srs_folder, unique_folder, overwrite=True,use_dataset_factory = False) # BLOB or GEN 2 

            print("")
            print("Saved DATA to score successfully in LAKE, as file '{}'".format(file_name))

            # 3) Save scored_results, to unique folder, for the day 
            # Note: Here we can save also, which CALLER/User-Guid it is about. We cab have a User_id_GUID as a "feature/column"
            unique_folder = self.ScoredPath + date_folder + '/'+ same_guid_folder + "/"
            srs_folder = './common/temp_data/{}/inference/{}/Scored/'.format(self.project_folder_name,v_str)
            file_name = "scored_{}.parquet".format(caller_guid) # HERE ....who is this scoring about?

            local_path = '{}{}'.format(srs_folder,file_name)
            ESMLProject.create_folder_if_not_exists(srs_folder)
            scored_result.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            self.LakeAccess.upload(file_name, srs_folder, unique_folder, overwrite=True,use_dataset_factory = False) # BLOB or GEN 2

            print("Saved SCORED data in LAKE, as file '{}'".format(file_name))

            # Needed?
            try:
                ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, unique_folder + "*.parquet")],validate=False)
                description = "Scored gold data with model version {}".format(v_str)
                self.registerGoldScored(ds,description,date_folder, v_str,caller_guid,self.rnd)
            except Exception as e2:
                print("Could not merge X_test to scored_all_X.parquet and register as Azure ML Dataset. You will have to do this on your own..")

        except Exception as e:
            raise e
        finally:
            self.inferenceModelVersion = inference_before # Set back to same state

        return scored_result

    def save_gold(self,dataframe, new_version=True):
        return self.save_gold_pandas_as_azure_dataset(dataframe,new_version)

    def save_gold_pandas_as_azure_dataset(self,dataframe, new_version=True):
        srs_folder = './common/temp_data/{}/Gold/'.format(self.project_folder_name)
        target_path = self.GoldPath
        file_name = "gold.parquet"
        #file_name = uuid.uuid4().hex
        local_path = '{}{}'.format(srs_folder,file_name)
        #ESMLProject.clean_temp(self.project_folder_name)
        ESMLProject.create_folder_if_not_exists(srs_folder)

        dataframe.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

        ds = None
        if(self.rnd): # No versioning & overwrite
            #self.Lakestore.upload(src_dir=srs_folder, target_path=target_path, overwrite=self.rnd) # BLOB
            self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, self.GoldPath + "*.parquet")],validate=False)
        else: # Version folder + don't overwrite
            version_folder = self.GoldPath + uuid.uuid4().hex + "/"
            #self.Lakestore.upload(src_dir=srs_folder, target_path=version_folder, overwrite=False) # BLOB
            self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # BLOB or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)

        # Set and return "LATEST" version
        return self.registerGold(ds, "GOLD.parquet merged from all datasets. Source to be splitted (Train,Validate,Test)",new_version)

 #TRAIN, VALIDATE, TEST   
    def save_gold_train_pandas_as_azure_dataset(self,dataframe,split_percentage,label, new_version=True):
        srs_folder = './common/temp_data/{}/Gold/Train/'.format(self.project_folder_name)
        target_path = self.GoldPath + 'Train/'
        file_name = "gold_train.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)
        #ESMLProject.clean_temp(self.project_folder_name)
        ESMLProject.create_folder_if_not_exists(srs_folder)

        dataframe.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

        ds = None
        if(self.rnd): # No versioning & overwrite
            self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path + "*.parquet")],validate=False)
        else: # Version folder + don't overwrite
            version_folder = target_path + uuid.uuid4().hex + "/"
            self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # BLOB, or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)

        # Set and return "LATEST" version
        return self.registerGoldTrain(ds, "GOLD_TRAIN.parquet from splitted Train, Validate, Test",split_percentage,label,new_version)

    def save_gold_validate_pandas_as_azure_dataset(self,dataframe,split_percentage,label, new_version=True):
        srs_folder = './common/temp_data/{}/Gold/Validate/'.format(self.project_folder_name)
        target_path = self.GoldPath + 'Validate/'
        file_name = "gold_validate.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)
        #ESMLProject.clean_temp(self.project_folder_name)
        ESMLProject.create_folder_if_not_exists(srs_folder)

        dataframe.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

        ds = None
        if(self.rnd): # No versioning & overwrite
            self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path + "*.parquet")],validate=False)
        else: # Version folder + don't overwrite
            version_folder = target_path + uuid.uuid4().hex + "/"
            self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # BLOB, or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)

        # Set and return "LATEST" version
        return self.registerGoldValidate(ds, "GOLD_VALIDATE.parquet from splitted Train, Validate, Test",split_percentage,label, new_version)

    def save_gold_test_pandas_as_azure_dataset(self,dataframe, split_percentage,label, new_version=True):
        srs_folder = './common/temp_data/{}/Gold/Test/'.format(self.project_folder_name)
        target_path = self.GoldPath + 'Test/'
        file_name = "gold_test.parquet"
        local_path = '{}{}'.format(srs_folder,file_name)
        #ESMLProject.clean_temp(self.project_folder_name)
        ESMLProject.create_folder_if_not_exists(srs_folder)

        dataframe.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

        ds = None
        if(self.rnd): # No versioning & overwrite
            self.LakeAccess.upload(file_name, srs_folder, target_path, overwrite=self.rnd) # BLOB or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, target_path+ "*.parquet")],validate=False)
        else: # Version folder + don't overwrite
            version_folder = target_path + uuid.uuid4().hex + "/"
            self.LakeAccess.upload(file_name,srs_folder, version_folder, overwrite=self.rnd) # BLOB, or GEN 2
            ds = Dataset.Tabular.from_parquet_files(path = [(self.Lakestore, version_folder + "*.parquet")],validate=False)

        # Set and return "LATEST" version
        return self.registerGoldTest(ds, "GOLD_TEST.parquet from splitted Train, Validate, Test",split_percentage,label,new_version)

#TRAIN, VALIDATE, TEST

    def split_gold_3(self,train_percentage=0.6, label=None,new_version=True, seed=42):

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
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_name_azure, description=description,create_new_version=new_version)
        self._gold_dataset = ds
        return self.Gold

#TRAIN, VALIDATE, TEST
    def registerGoldTrain(self, azure_dataset, description, split_percentage,label,new_version):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_train_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        
        t={"split_percentage": split_percentage, "label": label}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_train_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_train = ds
        return self.GoldTrain

    def registerGoldValidate(self, azure_dataset, description, split_percentage,label, new_version):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_validate_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        t={"split_percentage": split_percentage, "label": label}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_validate_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_validate = ds
        return self.GoldValidate

    def registerGoldTest(self, azure_dataset, description, split_percentage,label, new_version):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_test_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        t={"split_percentage": split_percentage, "label": label}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_test_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_test= ds
        return self.GoldTest

    def registerGoldScored(self, azure_dataset, description,date_time_folder,  model_version,caller_id = None, new_version=True):
        ESMLDataset.unregister_if_rnd(self.ws,self.rnd,self.dataset_gold_scored_name_azure)

        if(self.rnd == False): # Always NEW_VERSION if Production phase
            new_version = True
        t={"date_time_folder":date_time_folder, "caller_id":caller_id, "model_version": model_version}
        ds = azure_dataset.register(workspace=self.ws,name=self.dataset_gold_scored_name_azure, description=description,tags=t,create_new_version=new_version)
        self._gold_scored = ds
        return self.GoldScored

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

    def init(self,ws):
        if(ws != self.ws): # Connect to other DatatStore - even if its the same physical lake
            self._recreate_datastore = True
        self._suppress_logging = True
 
        self.automap_and_register_aml_datasets(ws)

    def unregister_all_datasets(self,ws):
        self.set_lake_as_datastore(ws)
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
                         pass #raise e

                print("- Silver name: {}".format(silver_name))
                try:
                    d1 = Dataset.get_by_name(ws, silver_name)
                    d1.unregister_all_versions()
                except Exception as e:
                    if("Invalid tuple for path" not in e.message):
                        pass #raise e

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

        temp_folder = './common/temp_data/{}/'.format(self.project_folder_name)
        #print("Cleaning local temp for project at: {}".format(temp_folder))
        ESMLProject.clean_temp(self.project_folder_name)
        ESMLProject.create_folder_if_not_exists(temp_folder)

        if(self._suppress_logging == False):
            print("Register ES-ML Datastore...")
        lakestore = self.set_lake_as_datastore(ws)
        self.readActiveDatesFromLake()
        self.checkLakeCompatability()

        print("")
        print("Load data as Datasets....")

        exists_dictionary = defaultdict(list)
        # VERISONS samename  "ds01_diabetes". Specify `create_new_version=True` to register the dataset as a new version. 
        # Use `update`, `add_tags`, or `remove_tags` to change only the description or tags.

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
                dstore_paths = [(lakestore,  ds.InPath + "*.csv")]
                desc_in =  "IN: " + dataset_description
                try:
                    in_ds = Dataset.Tabular.from_delimited_files(path=dstore_paths,validate=False) # create the Tabular dataset with 
                    try:
                        exists_dictionary.setdefault(ds.Name, []).append("IN_Folder_has_files")
                        ds.registerIn(in_ds,desc_in,False)
                    except UserErrorException as e:
                        print("Datasets already intiated with name {} in Azure, with description: {}. Inner exception:\n{} ".format(ds.Name,desc_in,e))
                except Exception as e2: # Try .parquet instead - Else just throw exception
                    print("IN (.csv or .parquet) coult not be initiated  for dataset {} with description {}. Trying as .parquet instead.".format(ds.Name,desc_in))
                    dstore_paths = [(lakestore,  ds.InPath + "*.parquet")]
                    desc_in =  "IN_PQ: " + dataset_description
                    in_ds = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=False) # create the Tabular dataset with 
                    ds.registerIn(in_ds,desc_in,False)

                    if("Cannot load any data from the specified path" not in e2.message):
                        raise e2

                # BRONZE folder / Azure dataset
                dstore_paths = [(lakestore,  ds.BronzePath + "*.parquet")]
                desc_bronze =  "BRONZE: " + dataset_description
                try:
                    bronze_ds = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=False) # create the Tabular dataset with 'state' and 'date' as virtual columns 
                    try:
                        exists_dictionary.setdefault(ds.Name, []).append("BRONZE_Folder_has_files")
                        #ds.registerBronze(bronze_ds,desc_bronze,False)
                    except UserErrorException as e:
                        print("Datasets already intiated with name {} in Azure, with description: {}. Inner exception:\n{}".format(ds.name,desc_bronze,e))
                except UserErrorException as e2:
                    if("Cannot load any data from the specified path" not in e2.message):
                        raise e2
                
                # SILVER folder / Azure dataset
                dstore_paths = [(lakestore,  ds.SilverPath + "*.parquet")]
                desc_silver =  "SILVER: " + dataset_description
                try:
                    ds_silver = Dataset.Tabular.from_parquet_files(path=dstore_paths,validate=False) # create the Tabular dataset with 'state' and 'date' as virtual columns 
                    try:
                        exists_dictionary.setdefault(ds.Name, []).append("SILVER_Folder_has_files")
                        ds.registerSilver(ds_silver,desc_silver,False)
                    except UserErrorException as e:
                        print("Datasets already intiated with name {} in Azure, with description: {}. Inner exception:\n{}".format(ds.name,desc_silver,e))
                except UserErrorException as e2:
                    if("Cannot load any data from the specified path" not in e2.message):
                        raise e2
        except Exception as e2:
            if("Cannot load any data from the specified path" not in e2.message):
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
        return lakestore

    # https://docs.microsoft.com/en-us/python/api/azureml-core/azureml.data.dataset_factory.tabulardatasetfactory?view=azure-ml-py#register-pandas-dataframe-dataframe--target--name--description-none--tags-none--show-progress-true-
    # register_pandas_dataframe(dataframe, target, name, description=None, tags=None, show_progress=True)
    # target: Required, the datastore path where the dataframe parquet data will be uploaded to. A guid folder will be generated under the target path to avoid conflict.
    
    def save_silver(self,esml_dataset, dataframe):
        return self.save_silver_pandas_as_azure_dataset(esml_dataset, dataframe)

    def save_silver_pandas_as_azure_dataset(self,esml_dataset, dataframe):
        srs_folder = './common/temp_data/{}/{}/Silver/{}/'.format(self.project_folder_name,esml_dataset.Name,self.dev_test_prod)
        target_path = esml_dataset.SilverPath
        file_name = "silver.parquet" #file_name = uuid.uuid4().hex
        local_path = '{}{}'.format(srs_folder,file_name)
        #ESMLProject.clean_temp(self.project_folder_name)
        ESMLProject.create_folder_if_not_exists(srs_folder)

        dataframe.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

        esml_dataset.upload_and_register_pandas_silver(file_name,srs_folder, target_path)
        return esml_dataset.Silver

    def save_bronze(self,esml_dataset, dataframe):
        return self.save_bronze_pandas_as_azure_dataset(esml_dataset, dataframe)
        
    def save_bronze_pandas_as_azure_dataset(self,esml_dataset, dataframe):
        srs_folder = './common/temp_data/{}/{}/Bronze/{}/'.format(self.project_folder_name,esml_dataset.Name, self.dev_test_prod)
        target_path = esml_dataset.BronzePath
        file_name = "bronze.parquet" # uuid.uuid4().hex
        local_path = '{}{}'.format(srs_folder,file_name)
        #ESMLProject.clean_temp(self.project_folder_name)
        ESMLProject.create_folder_if_not_exists(srs_folder)
           
        dataframe.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

        esml_dataset.upload_and_register_pandas_bronze(file_name,srs_folder, target_path)
        return esml_dataset.Bronze


    @staticmethod 
    def _z_pandas_to_parquet_date_safe(esml_dataset,local_path):
        print("trying to save parquet from Pandas (csv) manually since Azure ML Dataset failed casting timestamp via Parquet")

        pd_df = esml_dataset.to_pandas_dataframe()
        csv_name = local_path + ".csv"
        pd_df.to_csv(csv_name,index=False)

        df = pd.read_csv(csv_name)
        df.to_parquet(local_path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

    @staticmethod
    def create_folder_if_not_exists(new_folder):
        if not os.path.exists(new_folder):
            os.makedirs(new_folder)
            print("..")                
            #os.chmod(srs_folder,0o755)

    def clean_temp(project_folder_name):
        old_loc = os.getcwd()
        srs_folder = './temp_data/'+project_folder_name

        try: # Clean ALL, first
            os.chdir(os.path.dirname(__file__))
            try:
                print("...")
                shutil.rmtree(srs_folder) # Delete all
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
        args = parser.parse_args()
        esml_environment = args.esml_environment

        p = None
        if(esml_environment is not None):
            print("The argparse (Azure Devops) variable 'esml_environment ' (dev, test or prod) is set to: {}".format(esml_environment))
            p = ESMLProject(esml_environment)
        else:
            p = ESMLProject()
            print("args.esml_environment is None. Reading environment from config-files")
        return p
           
class ESMLDataset():
    #Defaults - project specicfic examples
    project_folder_name = "project002"
    model_folder_name = "03_diabetes_model_reg"
    model_aml_dataset_prefix = "M01"
    ds_name = "ds01_diabetes_ASDF"

    # AZURE Datasets
    _in_train = None
    _in_inference = None
    _bronze_train = None
    _bronze_inference = None
    _silver_train = None
    _silver_inference = None
    #Names 
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
        self._in_path_inference = self._inference_path_template.format(self._project._proj_start_path, self.project_folder_name,self.model_folder_name, self.inferenceModelVersion,self.ds_name  ,"in",project.dev_test_prod,project.InDateFolder)
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

# TODO: Same as GOLD, if versioning needed for this. For now - save storage
    @property
    def Bronze(self):
        try:
            if (self.inferenceModelVersion >0): # Inference path
                if (self._bronze_inference is None): #Lazy load
                    # TODO: Same as GOLD, if versioning needed for this. For now - save storage
                    self._bronze_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "*.parquet")],validate=False)

                return self._bronze_inference # return cached. 
            else:
                if (self._bronze_train is None): # Lazy load
                    self._bronze_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "*.parquet")],validate=False)
                return self._bronze_train
        except Exception as e:
            if("Cannot load any data from the specified path" in e.message):
                raise UserErrorException("ESML Bronze folder in lake seems to be empty."\
                 "\n Tip: Is there any data (.csv) in IN-folder for specific date-folder path?"\
                 "Why I'm asking? Because if data exists in IN-folder,"\
                 "this will automatically be converted from .csv to .parquet copied to OUT/BRONZE. No there is nothing here: {}".format(self.BronzePath)) from e

    @Bronze.setter
    def Bronze(self, bronze_azure_dataset):
        if (self.inferenceModelVersion >0): # Inference path
             #print("Bronze.set INFERENCE")
             self._bronze_inference = bronze_azure_dataset
        else:
            #print("Bronze.set")
            self._bronze_train = bronze_azure_dataset

# TODO: Same as GOLD, if versioning needed for this. For now - save storage
    @property
    def Silver(self):
        if (self.inferenceModelVersion >0): # Inference path
            if (self._silver_inference is None): #Lazy load - only 1 version supported. Always overwrite
                self._silver_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "*.parquet")],validate=False)
            return self._silver_inference # return cached. 
        else:
            if (self._silver_train is None): # Lazy load
                self._silver_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "*.parquet")],validate=False)
            
            return self._silver_train
   
    @Silver.setter
    def Silver(self, silver_azure_dataset):
        if (self.inferenceModelVersion >0): # Inference path
            #print("Silver.set INFERENCE")
            self._silver_inference = silver_azure_dataset
        else:
            #print("Silver.set")
            self._silver_train = silver_azure_dataset

    @property
    def InData(self):
        if (self.inferenceModelVersion >0): # Inference path  
            if (self._in_inference is None): #Lazy load
                try:
                    self._in_inference = Dataset.Tabular.from_delimited_files(path = [(self._project.Lakestore, self.InPath + "*.csv")],validate=False)
                except Exception as e:
                    print("ESML Note: Could not read InData as .CSV - Now trying as .PARQUET instead.")
                    self._in_inference = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.InPath + "*.parquet")],validate=False)

            return self._in_inference
        else:
             if (self._in_train is None): # Lazy load
                try:
                    self._in_train = Dataset.Tabular.from_delimited_files(path = [(self._project.Lakestore, self.InPath + "*.csv")],validate=False)
                except Exception as e:
                    print("ESML Note: Could not read InData as .CSV - Now trying as .PARQUET instead.")
                    self._in_train = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.InPath + "*.parquet")],validate=False)
             return self._in_train

    @InData.setter
    def InData(self, in_azure_dataset):

        df_csv = self.InData.to_pandas_dataframe() 
        if ( 'Unnamed: 0' in df_csv): # Fix crap savings of CSV (using Spark CSV-driver or Excel, forgetting Index=False at save etc) 
            df_csv = df_csv.drop('Unnamed: 0', axis=1)
            df_csv.reset_index(drop=True, inplace=True)

        if (self.inferenceModelVersion >0): # Inference path
            self._in_inference = in_azure_dataset

            self.Bronze = self._project.save_bronze_pandas_as_azure_dataset(self, df_csv) # Auto-set BRONZE
        else:
            self._in_train = in_azure_dataset
            self.Bronze = self._project.save_bronze_pandas_as_azure_dataset(self, df_csv) # Auto-set BRONZE

# SAVE DATA - 
    def upload_and_register_pandas_bronze(self,file_name, srs_folder, target_path,new_version=False):
        self._project.LakeAccess.upload(file_name,srs_folder, target_path, overwrite=True) # GEN 2

        self.Bronze = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.BronzePath + "*.parquet")],validate=False)
        self.registerBronze(self.Bronze,"BRONZE from refinement",new_version)
        return self.Bronze

    def upload_and_register_pandas_silver(self,file_name, srs_folder, target_path,new_version=False):
        self._project.LakeAccess.upload(file_name,srs_folder, target_path, overwrite=True) # GEN 2

        self.Silver = Dataset.Tabular.from_parquet_files(path = [(self._project.Lakestore, self.SilverPath + "*.parquet")],validate=False)
        description = "SILVER from refinement"
        self.registerSilver(self.Silver, description,new_version)
        return self.Silver


    def registerIn(self,azure_dataset, description,new_version=True):
        self._in_name_azure = self._project.ModelAlias +"_"+self.ds_name+"_IN"
        ESMLDataset.unregister_if_rnd(self._project.ws,self._project.rnd,self._in_name_azure )
        
        if(self._project.rnd == False):
            new_version = True
        ds_in = azure_dataset.register(workspace=self._project.ws,name=self._in_name_azure, description=description, create_new_version=new_version)
        self.InData = ds_in

    def registerBronze(self,azure_dataset, description,new_version=True):
        self._bronze_name_azure = self._project.ModelAlias +"_"+self.ds_name+"_BRONZE"
        ESMLDataset.unregister_if_rnd(self._project.ws,self._project.rnd,self._bronze_name_azure)
        if(self._project.rnd == False):
            new_version = True # yes, if not..There is already a dataset registered under name
        ds = azure_dataset.register(workspace=self._project.ws,name=self._bronze_name_azure, description=description, create_new_version=new_version)
        self.Bronze = ds

    def registerSilver(self,azure_dataset, desc_silver,new_version=True):
        self._silver_name_azure = self._project.ModelAlias +"_"+self.ds_name+"_SILVER"
        ESMLDataset.unregister_if_rnd(self._project.ws,self._project.rnd,self._silver_name_azure)
        if(self._project.rnd == False):
            new_version = True # # yes, if not..error
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
    def InPath(self):
        if(self.inferenceModelVersion >0): 
            self._in_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name, self.inferenceModelVersion,self.ds_name  ,"in",self._project.dev_test_prod,self._project.InDateFolder)
            return self._in_path_inference
        else:
            self._in_path_train = self._train_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.ds_name ,"in",self._project.dev_test_prod,self._project.InDateFolder)
            return self._in_path_train
    @property
    def BronzePath(self):
        if(self.inferenceModelVersion >0):
            self._bronze_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name, self.inferenceModelVersion,self.ds_name  ,"out","bronze",self._project.dev_test_prod)
            return self._bronze_path_inference
        else:
            return self._bronze_path_train
    @property
    def SilverPath(self):
        if(self.inferenceModelVersion >0):
            self._silver_path_inference = self._inference_path_template.format(self._project._proj_start_path,self.project_folder_name,self.model_folder_name,self.inferenceModelVersion,self.ds_name ,"out", "silver",self._project.dev_test_prod)
            return self._silver_path_inference
        else:
            return self._silver_path_train
       
    @property
    def DatasetFolderName(self):
        return self.ds_name
    @property
    def Name(self):
        return self.ds_name