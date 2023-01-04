from abc import ABCMeta, abstractmethod
from ..interfaces.iESMLModelCompare import IESMLModelCompare
from ..interfaces.iESMLTestScoringFactory import IESMLTestScoringFactory

from azureml.core import Experiment
from azureml.core import Model
from azureml.pipeline.core import PipelineRun
from azureml.train.automl.run import AutoMLRun
from azureml.core import Run
from azureml.core.dataset import Dataset
from azureml.core.resource_configuration import ResourceConfiguration
from azureml.core.authentication import ServicePrincipalAuthentication
from azureml.core import Workspace
from azureml.core import Environment
from azureml.exceptions import ProjectSystemException
import joblib
import time
import datetime
import os
from azureml.core.model import InferenceConfig
import shutil

class IESMLController:
    __metaclass__ = ABCMeta

    # Sub, RG, WS
    subscription_id = None
    resource_group = None
    workspace_name = None

    # Dev, Test, Prod
    
    _subscription_id_dev = None
    _subscription_id_test = None
    _subscription_id_prod = None

    _resource_group_dev = None
    _resource_group_test = None
    _resource_group_prod = None

    _workspace_name_dev = None
    _workspace_name_test = None
    _workspace_name_prod = None
    
    ## Auth
    _supported_revision = '1.4'
    _dev_test_prod = "dev"

    _iModelCompare = None
    _iTestScoringFactory = None
    _iTrainer = None

    _resource_configuration = None

    esml_path_script_template_enterprise = "../../../settings/enterprise_specific/dev_test_prod_defaults/pipeline_template"
    esml_path_snapshot_folder = "../../../01_pipelines/"

    _secret_name_tenant = "esml-tenant-id"
    _secret_name_project_sp_id = "esml-project-sp-id"
    _secret_name_project_sp_secret = "esml-project-sp-secret"

    _esml_project_folder_name = None
    _esml_model_name = None
    _esml_model_alias = None
    
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

    @classmethod
    def version(self): return "1.4"

    def __init__(self,modelCompare,testScoringFactory, esml_project_folder_name, esml_model_name, esml_model_alias,all_envs, secret_name_tenant = None,secret_name_project_sp_id= None,secret_name_project_sp_secret = None):

        if not isinstance(modelCompare, IESMLModelCompare): raise Exception('Bad interface. Should be IESMLModelCompare')
        if not IESMLModelCompare.version() == self._supported_revision: raise Exception('Bad revision, should be ' +self. _supported_revision)

        if not isinstance(testScoringFactory, IESMLTestScoringFactory): raise Exception('Bad interface. Should be IESMLTestScoringFactory')
        if not IESMLModelCompare.version() == self._supported_revision: raise Exception('Bad revision,  should be '+ self._supported_revision)

        self._iModelCompare = modelCompare
        self._iTestScoringFactory = testScoringFactory

        self._esml_model_name = esml_model_name
        self._esml_model_alias = esml_model_alias
        self._esml_project_folder_name = esml_project_folder_name

        self._iModelCompare.esml_controller = self # Set this controller to the compare class
        self._resource_configuration = ResourceConfiguration(cpu=1, memory_in_gb=0.5) # When REGISTER model
        
        if(secret_name_tenant is not None): # override default naming convention on kv-secret-names
            self._secret_name_tenant = secret_name_tenant
            self._secret_name_project_sp_id =secret_name_project_sp_id
            self._secret_name_project_sp_secret = secret_name_project_sp_secret

        try:
            self._subscription_id_dev = all_envs["dev"]["subscription_id"]
            self.subscription_id = self._subscription_id_dev # start at DEV 

            self._subscription_id_test = all_envs["test"]["subscription_id"]
            self._subscription_id_prod = all_envs["prod"]["subscription_id"]

            self._resource_group_dev = all_envs["dev"]["resourcegroup_id"]
            self._resource_group_test = all_envs["test"]["resourcegroup_id"]
            self._resource_group_prod = all_envs["prod"]["resourcegroup_id"]

            self._workspace_name_dev = all_envs["dev"]["workspace_name"]
            self._workspace_name_test = all_envs["test"]["workspace_name"]
            self._workspace_name_prod = all_envs["prod"]["workspace_name"]
        except:
            print("INFO: Could not load all ESML environments in ESMLController. maybe DEMO mode / not all are configured or created? ")

        self.dev_test_prod = "dev" # Set default value

    @staticmethod
    def get_esml_environment_name(): 
        return "ESML-AzureML-144-AutoML_126"
    
    @staticmethod
    def get_known_model_name_pkl():
        return 'model.pkl'#'esml_leading_model.pkl'
    @staticmethod
    def get_known_scoring_file_name(version_number=0):
        return 'scoring_file_v_1_0_{}.py'.format(version_number)
        
    ###
    # properties
    ###
    @property
    @abstractmethod
    def dev_test_prod(self):
        return self._dev_test_prod

    @dev_test_prod.setter
    def dev_test_prod(self, dev_test_prod_in):

        if(dev_test_prod_in == "dev"):
            self.subscription_id = self._subscription_id_dev
            self.resource_group = self._resource_group_dev
            self.workspace_name = self._workspace_name_dev
        elif(dev_test_prod_in == "test"):
            self.subscription_id = self._subscription_id_test
            self.resource_group = self._resource_group_test
            self.workspace_name = self._workspace_name_test
        elif(dev_test_prod_in == "prod"):
            self.subscription_id = self._subscription_id_prod
            self.resource_group = self._resource_group_prod
            self.workspace_name = self._workspace_name_prod

        self._dev_test_prod = dev_test_prod_in


    @property
    @abstractmethod
    def register_model_resource_configuration(self):
        return  self._resource_configuration 

    @register_model_resource_configuration.setter
    def register_model_resource_configuration(self, resource_configuration):
         self._resource_configuration  = resource_configuration

    ##
    # services
    ##
    @property
    def ESMLComparer(self):
        return self._iModelCompare
    @property
    def ESMLTestScoringFactory(self):
        return self._iTestScoringFactory

    @property
    def dataset_gold_train_runinfo_name_azure(self):
        return self._esml_model_alias+"_GOLD_TRAINED_RUNINFO"

    @property
    def experiment_name(self):
        return self._esml_model_name
    
    ###
    # Abstract methods
    ###

    ###
    # returns: experiment, model,main_run, best_automl_run=None,fitted_model=None
    ###
    @abstractmethod
    def get_best_model(self, ws):
        raise NotImplementedError

    ###
    # Internal method of ESML. Use public register_model() instead. But here you can effect the logic of correct workspace.
    # returns:  model_registered_in_target, model_source
    ###
    @abstractmethod
    def _register_model_in_correct_workspace(self,current_environment, current_ws, target_environment,new_model=None, description_in=None,pkl_name_in=None):
        raise NotImplementedError

    ###
    # Model.register , here you can choose your own way how to register model_framework,model_framework_version, sample_dataset
    ## DEFAULT in ESML: model_framework=Model.Framework.SCIKITLEARN,  model_framework_version=sklearn.__version__
    # returns: model
    ###
    @abstractmethod
    def _register_aml_model(self,full_local_path,model_name,tags,target_ws,description_in):
        raise NotImplementedError
    
    ###
    # Impl methods
    ###

    def get_other_workspace(self, source_ws, target_dev_test_prod):
        kv = source_ws.get_default_keyvault() # Get "current" workspace, either CLI Authenticated if MLOps
        other_ws = None
        current_env = self.dev_test_prod

        try:
            self.dev_test_prod = target_dev_test_prod # Reloads config from TARGET. # TODO-2022-08 reload config
            print("Connecting to env: {}".format(target_dev_test_prod))
            print("- ws name: {}".format(source_ws.name))
            
            print("- self._secret_name_tenant: {}".format(self._secret_name_tenant))
            print("- self._secret_name_project_sp_id: {}".format(self._secret_name_project_sp_id))
            print("- self._secret_name_project_sp_secret: {}".format(self._secret_name_project_sp_secret))

            sp = ServicePrincipalAuthentication(tenant_id=kv.get_secret(name=self._secret_name_tenant), # tenantID
                                                service_principal_id=kv.get_secret(name=self._secret_name_project_sp_id), # clientId
                                                service_principal_password=kv.get_secret(name=self._secret_name_project_sp_secret)) # clientSecret

            other_ws = Workspace.get(name = self.workspace_name,subscription_id = self.subscription_id,resource_group = self.resource_group,auth=sp) # TODO-2022-08 reload config
        except ProjectSystemException as e:
            print("")
            print("INFO")
            print("You have no (or access to) Azure ML Studio Workspace in environment '{}'".format(target_dev_test_prod))
            print("You need the below created/access: ")
            print("")
            print("Subscription ID: ", self.subscription_id)
            print("Resource group", self.resource_group)
            print("Workspace name", self.workspace_name)
            print("")
        finally:
            self.dev_test_prod = current_env

        return other_ws


    def get_next_environment(self):
        if(self.dev_test_prod == "dev"):
            return "test"
        elif (self.dev_test_prod == "test"):
            return "prod"
        elif(self.dev_test_prod == "prod"):
            return "prod"

###
# Get MODEL
###

    @staticmethod
    def _get_run_fitted_model(experiment, run_id):
        main_run = None
        best_run = None
        source_fitted_model = None

        # 1: AutoML first
        try:
            main_run = AutoMLRun(experiment=experiment, run_id=run_id)
            best_run, source_fitted_model = main_run.get_output()
        except Exception as e:
            print("1)Soft Error: AutoML.get_output() gave error: {}".format(e))
            print("2)Soft Error: Now trying as PipelineRun() or Run() instead of AutoMLRun(),to get fitted_model")
            
            try: # 2: PipelineRun 
                main_run = PipelineRun(experiment=experiment, run_id=run_id)
                best_run = main_run
                try:
                    source_fitted_model = joblib.load("model.pkl")
                    print("load Model with joblib.load, name model.pkl SUCCESS") # SUCCESS!
                except Exception as e:
                    print("Cannot load Model with name model.pkl from PipelineRun(), now trying from Run()")

            except Exception as e2:
                print("3)Soft Error: PipelineRun() gave error: {}".format(e2))
                print("4)Soft Error: It is not an AutoMLRun(), nor PipelineRun(). Lets initate a regular Run()")
                main_run = Run(experiment=experiment, run_id=run_id)
                best_run = main_run
                
                try: # 3: Run 
                    source_fitted_model = joblib.load("model.pkl")
                    print("load Model with joblib.load, name model.pkl SUCCESS") # SUCCESS!
                except Exception as e:
                    print("Cannot load Model with name model.pkl from Run(), now trying from Run()")

        return main_run, best_run,source_fitted_model

     ###
    # Gets LATEST version of model, via EXPERIMENT TAGS and MODEL TAGS, as fallback LOOPING all Models in workspace. Also fetches the best RUN and FITTED MODEL
    # Pros: Quick if TAGS exists (since ModelName and RunId is known no looping nessesary), and safe as 1st time when to TAGS exists.
    # Cons: Only works in DEV (not TEST, PROD) Do not work, fetching parentless Model. Needs an experiment and run
    # Tip when to use: When comparing within same Azure ML workspace. QUICK and SAFE within workspace
    ###
    @staticmethod
    def get_best_model_run_fitted_model_Dev(ws,experiment_name, get_latest_challenger=False, filter_on_version = None):
        model,run_id,model_name = IESMLController._get_best_model_via_experiment_tags_or_loop(ws,experiment_name,get_latest_challenger,filter_on_version) # 2021-09 update

        if(model is None): # guard
            #print("No best model found in this Azure ML Studio, for this ESMLProject and ESMLModel. 1st time")
            return None,None,None,None,None
        else:
            #model_name = model.tags["model_name"]
            #run_id = model.tags["run_id"]
            experiment = Experiment(ws, experiment_name)
            main_run, best_run, fitted_model = IESMLController._get_run_fitted_model(experiment=experiment, run_id=run_id)
        return experiment, model,main_run, best_run,fitted_model

    ###
    # Gets LATEST run of training pipelie, via METADATA from ESML Azure dataset (after pipeline run)
    # Pros: Quick, since ModelName is known. Works in Dev,Test, Prod if pipelines, IN_2_GOLD_TRAIN has been executed before.
    # Cons: Only ESML PIPELINE runs works (1st time in RnD phase using notebook you cannot use this)
    # Tip when to use: PIPELINEs. IN_2_GOLD_TRAIN (if no earlier run use a fallback method)
    ###
    @staticmethod
    def get_latest_run_via_PipelineMetaDataset(ws,experiment_name, dataset_gold_train_runinfo_name_azure):
        aml_model = None
        aml_model_name = None
        best_run = None
        source_fitted_model = None
        best_automl_run = None

        if(aml_model is None):
            try:
                # 0 - Get "Pipelin run" info, for the most recent "trained model"
                ds1 = Dataset.get_by_name(workspace = ws, name = dataset_gold_train_runinfo_name_azure)
                run_id = ds1.to_pandas_dataframe().iloc[0]["pipeline_run_id"] #  ['pipeline_run_id', 'training_data_used', 'training_data_source_date', 'date_at_pipeline_run','model_version_current','model_version_newly_trained']
                experiment = Experiment(workspace=ws, name=experiment_name)
                
                try: # 2: PipelineRun 
                    main_run = PipelineRun(experiment=experiment, run_id=run_id)
                    best_run = main_run
                    fitted_model = None # TODO need to download pickle, and initiate model
                except Exception as e2:
                    print("3)Soft Error: PipelineRun() gave error: {}".format(e2))
                    print("4)Soft Error: Lets initate a regular Run()")
                    main_run = Run(experiment=experiment, run_id=run_id)
                    best_run = main_run
                    fitted_model = None # None

                aml_model_name = best_run.properties['model_name']
                aml_model = Model(ws, aml_model_name)
            except:
                pass

        #return aml_model,aml_model_name, source_fitted_model, experiment_name # self._esml_model_name
        return experiment, aml_model, main_run, best_automl_run,fitted_model # self._esml_model_name


    @staticmethod
    def copy_scoring_script_from_template_if_not_exists(model_alias):
        snapshot_folder = IESMLController.esml_path_snapshot_folder + model_alias + "/" # For scoring script location - online deployment
        target_folder = snapshot_folder + "your_code/"

        if(os.path.exists(target_folder)==False):
            os.makedirs(os.path.dirname(target_folder), exist_ok=True)

        source_file = 'your_{}'.format(IESMLController.get_known_scoring_file_name()) # 'your_scoring_file_v_1_0_0.py'
        source = IESMLController.esml_path_script_template_enterprise + "/your_code/" + source_file
        target_file = snapshot_folder + "your_code/" + source_file
        file_exist = os.path.exists(target_file)

        if(file_exist == False): # Scoring script file
            print("ESML - Scoring script file does not exists in snapshot folder: {} - now creating a defaule ESML scoring script (supports: classification, regression), for you to optionally edit at: ".format(target_file))
            shutil.copy(source, target_file)
        return target_file

    @staticmethod
    def get_default_environment_if_run_env_not_exists(the_run,ws):
        env = None
        if(the_run is None):
            env = Environment.get(workspace=ws, name=IESMLController.get_esml_environment_name()) 
        else:
            try:
                the_run.get_environment()
            except Exception as e5:
                print("ESML: Could not fetch Environment from Run() - now getting ESML default Azure ML Environment")
                env = Environment.get(workspace=ws, name=IESMLController.get_esml_environment_name())
        return env

    @staticmethod
    def get_best_model_inference_config(ws,model_folder_name, model_alias="M10", scoring_script_folder_local=None, current_model=None,run_id_tag=None, best_run = None):
        if(current_model is None and run_id_tag is None and best_run is None):
            current_model,run_id_tag, model_name = IESMLController.get_best_model_via_modeltags_only_DevTestProd(ws,model_folder_name)
            run,best_run,fitted_model = IESMLController.init_run(ws,model_folder_name, run_id_tag,current_model)
            the_run = best_run
        else:
            the_run = best_run
            model_name = current_model.name

        inference_config = None
        old_loc = os.getcwd()
        script_file_local = None
        try:
            os.chdir(os.path.dirname(__file__))
            if(scoring_script_folder_local is None):
                script_file_local = IESMLController.copy_scoring_script_from_template_if_not_exists(model_alias)
            if(os.path.isfile(script_file_local)):
                print("INFO: Local scoring script file exists at {}".format(script_file_local))

            script_file_abs = os.path.abspath(script_file_local)
            env = IESMLController.get_default_environment_if_run_env_not_exists(the_run,ws)
            inference_config = InferenceConfig(environment=env, entry_script=script_file_abs)
        except Exception as e2:
            #print(e2)
            print("Error: If best model is a MANUAL model, you need to have created a SCORING_FILE, at your snapshot folder at {}.".format(script_file_local))
            print("- The name of the scoring file you can retrieve with {}, example of location ma now be missing".format(script_file_local))
            print("- Note: If AutoML is the BEST model, then AutoML have created a scoring_file automatically, and this error would not occur")
            print ("- Run:{} and Model name: {} with model-version {}".format(run_id_tag,current_model.name,current_model.version))
            raise e2
        finally:
             os.chdir(old_loc)
        return inference_config, current_model, the_run

    @staticmethod
    def download_fitted_model(model, best_run, experiment_name = None):
        if_get_pickle_success = False
        fitted_model = None
        try:
            model_path = './outputs/{}'.format(model.name) # does not matter what path, it is the local target
            print("Now downloading files from model from {}".format(model_path))
            print(" ## ESML:Model.download()")
            model_download_return = model.download(target_dir=model_path, exist_ok=True)
            head, tail = os.path.split(model_download_return)

            m_path = './outputs/{}/{}'.format(model.name,tail)

            print("model_download_return path: {}".format(model_download_return))
            print("model_download_return filename: {}".format(tail))
                    
            try:
                print("Now trying with modelname as folder for pickel file, and using the file in that folder")
                print("Pickle path: {}".format(m_path)) # outputs/11_diabetes/11_diabetes
                fitted_model = joblib.load(m_path)
                if_get_pickle_success = True
            except Exception as e:
                if(FileNotFoundError is type(e)):
                    print("FileNotFoundError")
                    print(" ## ESML:Model.download()")
                    print(" ## ESML: now trying with IESMLController.get_known_model_name_pkl()")
                    print(" ## ESML:")
                    def_name = IESMLController.get_known_model_name_pkl()
                    print("ESML VARNING: Could not load FITTED model via Experiment model tag and via Model() - now trying to dowload .pkl with default name: {}, from Model.download()".format(def_name))
                    print("Pickle path earlier that failed, with default name: {}".format(m_path))
                    m_path = './outputs/'+def_name
                    print("New pickle path: {}".format(m_path))
                    fitted_model = joblib.load(m_path)
                    if_get_pickle_success = True
                elif(EOFError is type(e)):
                    print("EOFError")
                    print("Error - the .pkl file written is corrupt. This may happen if you have WRITTEN (joblib.dump) it with a pickle/joblib library version, and now trying to LOAD ( joblib.load ) with another version")
                    raise e
                else:
                    raise e
        except Exception as e:
            try:
                print(" ## ESML:Run.download_files() - Downloading the files from the RUN() instead of from Model...")
                print(" ## ESML: now trying with IESMLController.get_known_model_name_pkl()")
                print(" ## ESML:")

                def_name = IESMLController.get_known_model_name_pkl()
                print("ESML VARNING: Could not load FITTED model via Experiment model tag and via Model() - now trying to dowload .pkl with default name: {}, directly from RUN.download_files()".format(def_name))
                best_run.download_files() #  (target_dir=wrong_model_path, exist_ok=True)
                        
                print("Pickle path earlier that failed, with default name: {}".format(m_path))
                m_path = './outputs/'+def_name
                print("Pickle path, new with default name: {}".format(m_path))
                print("Run/best_run.id: {}".format(best_run.id))
                print("Model name: {}".format(model.name))
                print("experiment_name: {}".format(experiment_name))
                print("joblib version: {}".format(joblib.__version__))
                fitted_model = joblib.load(m_path)
                if_get_pickle_success = True
            except Exception as e:
                if(FileNotFoundError is type(e)):
                    print("FileNotFoundError")
                elif(EOFError is type(e)):
                    print("EOFError")
                    print("Error - the .pkl file written is corrupt. This may happen if you have WRITTEN (joblib.dump) it with a pickle/joblib library version, and now trying to LOAD ( joblib.load ) with another version")
                    raise e
                else:
                    raise e

        if(if_get_pickle_success):
            print("SUCCESS! Fitted model downloaded and extracted!")
        return fitted_model,if_get_pickle_success

    @staticmethod
    def init_run(ws,experiment_name, run_id, best_model = None, debug_print=True):
        exp = Experiment(workspace=ws, name=experiment_name)
        run = None
        best_run = None # AutoML only
        fitted_model = None
        run_id = IESMLController.get_safe_automl_parent_run_id(run_id)
        pipeline_run = None
        
        try: # if (run_type == "automl_run" or run_type == "notebook_automl"):
            if(debug_print):
                print("ESML INFO: try: automl_run or notebook_automl")
                print("Experiment name: {}".format(experiment_name))
                print("ws name: {}".format(ws.name))
                print("run_id: {}".format(run_id))

            print(" ## ESML: AutoMLRun? ")
            run = AutoMLRun(experiment=exp, run_id=run_id)
            best_run, fitted_model = run.get_output()
            print(" ## ESML: AutoMLRun = TRUE")
        except Exception as e1: # elif(run_type == "pipeline_automl_step"):
            if(debug_print):
                print(" ## ESML: AutoMLRun = FALSE")
                print(" - ESML INFO: Trying as PipelineRun (AML or DatabricksStep)")
                print(" ## ESML: PipelineRun? ")

            try:
                pipeline_run = PipelineRun(experiment=exp, run_id=run_id)
                best_run = main_run
                if(debug_print):
                    print(" ## ESML: PipelineRun = TRUE")
            except Exception as e:
                if(debug_print):
                    print(" ## ESML: PipelineRun = FALSE")
                    print(str(e))
                try:
                    if(debug_print):
                        print(" ## ESML: Run?")
                    main_run = Run(experiment=exp, run_id=run_id)
                    best_run = main_run
                    if(debug_print):
                        print(" ## ESML: Run = TRUE")
                except Exception as e4:
                    print(" ## ESML weird...it was not a Run, PipelineRun, AutoMLRun")
                    raise e4

            ##
            # Initiate MODEL from run.tags, or override with MODEL from parameter
            ##
            model_name = None
            best_model_version = None
            active_model = None

            if(best_run is not None):
                model_name = best_run.experiment.tags.get('model_name')
                best_model_version = best_run.experiment.tags.get('best_model_version') # latest promoted
            if(best_model is not None):
                active_model = best_model
                if(model_name is not None and best_model_version is not None): # Should not crash code, since just verifying
                    m_test = Model(workspace=ws,name=model_name, version=best_model_version)
                    if (m_test.name != best_model.name and m_test.version != best_model.version):
                        print("ESML Warning - m_test.name != best_model.name and m_test.version != best_model.version -> ESML will choose your injected 'best_model'")
            else:
                active_model = Model(workspace=ws,name=model_name, version=best_model_version)
            ##
            # If Pipeline with ManualStep - TRAIN PIPELINE (not if INFERENCE)
            ##
            if (pipeline_run is not None):
                step_list = list(pipeline_run.get_steps())
                step_len = len(step_list) # 6
                if(step_len == 0): # StepRun = Manual
                    #run = pipeline_run.parent
                    best_run = pipeline_run
                    fitted_model, if_get_pickle_success = IESMLController.download_fitted_model(active_model, best_run, exp.name)
                else: # Pipeline with AutoMLStep
                    automl_step_id = 1 #  The second last step. This current step, is the last step with index 0

                    automl_run_step_by_index = step_list[automl_step_id]
                    if(debug_print):
                        print("automl_run_step_by_index: {} and type {}".format(automl_run_step_by_index.id,type(automl_run_step_by_index)))
                    automl_step_run_id = automl_run_step_by_index.id
                    if(debug_print):
                        print("automl_step_run_id:{} which is 'new_run_id' in comparer.compare_scoring_current_vs_new_model".format(automl_step_run_id))
                    
                    experiment_run = ws.experiments[experiment_name] # Get the experiment. Alternatively: Experiment(workspace=source_workspace, name=experiment_name)
                    automl_step_run = AutoMLRun(experiment_run, run_id = automl_step_run_id)
                    best_run, fitted_model = automl_step_run.get_output()
            elif(main_run is not None):
                fitted_model, if_get_pickle_success = IESMLController.download_fitted_model(active_model, best_run, exp.name)
                raise NotImplementedError("ESML Unhandled: Since it was not a PipelineRun, AutoMLRun, just a Run - this is not handled by ESML")

        return run,best_run,fitted_model
          
    @staticmethod
    def get_best_model_inference_config_old(ws,experiment_name, current_model=None,run_id_tag=None, best_run = None):
        if(current_model is None and run_id_tag is None and best_run is None):
            current_model,run_id_tag, model_name = IESMLController.get_best_model_via_modeltags_only_DevTestProd(ws,experiment_name)
            run,best_run,fitted_model = IESMLController.init_run(ws,experiment_name, run_id_tag,current_model)
            the_run = best_run
        else:
            the_run = best_run
            model_name = current_model.name

        inference_config = None

        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            script_file_local = "../../../settings/project_specific/model/dev_test_prod/train/ml/scoring_file_{}.py".format(model_name)
            if(os.path.isfile(script_file_local)):
                print("INFO: Local scoring script file exists at {}".format(script_file_local))

            try:
                target_path = 'outputs/'+IESMLController.get_known_scoring_file_name()
                print("Trying Download from {}".format(target_path))
                the_run.download_file(target_path, script_file_local)
                print("Downloaded scoring file from outputs/ successfully")
            except Exception as e1:
                #print(e1)
                target_path = IESMLController.get_known_scoring_file_name()
                print("Trying Download from {}".format(target_path))
                the_run.download_file(target_path, script_file_local)
                print("Downloaded scoring file from ./ successfully")

            script_file_abs = os.path.abspath(script_file_local)
            env = None
            try:
                the_run.get_environment()
            except Exception as e5:
                print("ESML: Could not fetch Environment from Run() - now getting ESML default Azure ML Environment")
                env = Environment.get(workspace=ws, name=IESMLController.get_esml_environment_name()) 

            inference_config = InferenceConfig(environment=env, entry_script=script_file_abs)
        except Exception as e2:
            #print(e2)
            print("Error: If best model is a MANUAL model, you need to have created and uploaded a SCORING_FILE, at your training pipeline run, at {}.".format(target_path))
            print("- The name of the scoring file you can retrieve with {}, example of location now missing".format(target_path))
            print("- Note: If AutoML is the BEST model, then AutoML have created a scoring_file automatically, and this error would not occur")
            print ("- Run:{} and Model name: {} with model-version {}".format(run_id_tag,current_model.name,current_model.version))
            try:
                print("ESML -As fallback ESML will now - upload the default scoring file in './your_code/your_scoring_file_v_1_0_0.py' to the RUN and use that")
                # Upload Scoring script - Only needed if MAnual ML, since AutoML does this automatically TODO 4 YOU - implement this ./your_code/your_scoring_file_v_1_0_0.py
                # path_scoring_file_in_snapshot_folder = './your_code/your_{}'.format(IESMLController.get_known_scoring_file_name())
                path_scoring_file_in_snapshot_folder = '../settings/project_specific/model/your_{}'.format(IESMLController.get_known_scoring_file_name())

                the_run.upload_file(IESMLController.get_known_scoring_file_name(), path_scoring_file_in_snapshot_folder)
                script_file_local = "../settings/project_specific/model/dev_test_prod/train/ml/scoring_file_{}.py".format(model_name)
                print("Run.id = {} - After the_run.upload_file".format(the_run.id))
                
                try:
                    target_path = 'outputs/'+IESMLController.get_known_scoring_file_name()
                    print("Downloading scoring file from {}".format(target_path))
                    the_run.download_file(target_path, script_file_local)
                    print("Downloaded scoring file from outputs/ successfully")
                except Exception as e3:
                    target_path = IESMLController.get_known_scoring_file_name()
                    print("Downloading scoring file from {}".format(target_path))
                    the_run.download_file(target_path, script_file_local)
                    print("Downloaded scoring file from ./ successfully")

            except Exception as e3: 
                print("Error: If best model is a MANUAL model, you need to have created and uploaded a SCORING_FILE, at your training pipeline run, at {}.".format(target_path))
                print("- The name of the scoring file you can retrieve with {}, example of location now missing: ".format(target_path))
                print("- Note: If AutoML is the BEST model, then AutoML have created a scoring_file automatically, and this error would not occur")
                raise e3
            
        finally:
             os.chdir(old_loc)
        return inference_config, current_model, the_run

    @staticmethod
    def init_run_old(ws,experiment_name, run_id, best_model = None):
        exp = Experiment(workspace=ws, name=experiment_name)
        run = None
        best_run = None # AutoML only
        fitted_model = None
        debug_print = True
        run_id = IESMLController.get_safe_automl_parent_run_id(run_id)
        
        try: # if (run_type == "automl_run" or run_type == "notebook_automl"):
            if(debug_print):
                print("ESML INFO: try: automl_run or notebook_automl")
                print("Experiment name: {}".format(experiment_name))
                print("ws name: {}".format(ws.name))
                print("run_id: {}".format(run_id))
            run = AutoMLRun(experiment=exp, run_id=run_id)
            best_run, fitted_model = run.get_output()
        except: # elif(run_type == "pipeline_automl_step"):
            if(debug_print):
                print("ESML INFO: Trying as PipelineRun (AML or DatabricksStep)")
            pipeline_run = PipelineRun(experiment=exp, run_id=run_id)
            #pipeline_run = run.parent # Parent is the pipeline run, current is the current step.

            ##
            # If AutoML run or Manual step. If TRAIN - not if INFERENCE
            ##
            step_list = list(pipeline_run.get_steps())
            step_len = len(step_list) # 6
            if(step_len == 0): # StepRun = Manual
                run = pipeline_run.parent
                best_run = pipeline_run
                try:
                    model_name = best_run.experiment.tags['model_name']
                    best_model_version = best_run.experiment.tags['best_model_version'] # latest promoted
                    m = None

                    m = Model(workspace=ws,name=model_name, version=best_model_version)
                    m2 = best_model
                    if (m.name != m2.name):
                        print("ESML Warning - best_model.name != best_run.experiment.tags['model_name'] - choosing run name")
                    
                    #if(best_model is None):
                    #    m = Model(workspace=ws,name=model_name, version=best_model_version)
                    #else:
                    #    m = best_model
               
                    model_path = 'outputs_or_other/{}.pkl'.format(m.name) # does not matter what path, it is the local target
                    m_path = m.download(target_dir=model_path, exist_ok=True)
                    print("Pickle path: {}".format(m_path))
                    fitted_model = joblib.load(m_path)
                except Exception as e:
                    def_name = IESMLController.get_known_model_name_pkl()
                    print("ESML VARNING: Could not load FITTED model via Experiment model tag and via Model() - now trying to dowload .pkl with default name: {}, directly from RUN".format(def_name))
                    best_run.download_files() #  (target_dir=wrong_model_path, exist_ok=True)
                    
                    print("Pickle path earlier that failed, with default name: {}".format(m_path))
                    m_path = './outputs/'+def_name
                    print("Pickle path, new with default name: {}".format(m_path))
                    print("Run id: {}".format(run_id))
                    print("best_run id: {}".format(best_run.id))
                    print("Model name: {}".format(model_name))
                    print("experiment_name name: {}".format(experiment_name))
                    print("joblib version: {}".format(joblib.__version__))
                    try:
                        fitted_model = joblib.load(m_path)
                    except Exception as e3:
                        print(e3)

            else: # AutoML pipeline
                automl_step_id = 1 #  The second last step. This current step, is the last step with index 0

                automl_run_step_by_index = step_list[automl_step_id]
                if(debug_print):
                    print("automl_run_step_by_index: {} and type {}".format(automl_run_step_by_index.id,type(automl_run_step_by_index)))
                automl_step_run_id = automl_run_step_by_index.id
                if(debug_print):
                    print("automl_step_run_id:{} which is 'new_run_id' in comparer.compare_scoring_current_vs_new_model".format(automl_step_run_id))
                
                experiment_run = ws.experiments[experiment_name] # Get the experiment. Alternatively: Experiment(workspace=source_workspace, name=experiment_name)
                automl_step_run = AutoMLRun(experiment_run, run_id = automl_step_run_id)
                best_run, fitted_model = automl_step_run.get_output()
            '''
            elif(run_type == "notebook_manual_run"):
                pass
            elif(run_type == "pipeline_manual_run"):
                pass
            '''
        
        return run,best_run,fitted_model

    def check_if_test_scoring_exists_as_tags(self, model):
        a_scoring = ""
        exists = False
        if (self.ESMLTestScoringFactory.ml_type == "regression"):
            a_scoring = model.tags.get("test_set_R2")
        elif (self.ESMLTestScoringFactory.ml_type == "classification"):
            a_scoring = model.tags.get("test_set_Accuracy")
        
        if(len(a_scoring) > 0):
            exists = True
        return exists
    
    @staticmethod
    def get_safe_automl_parent_run_id(astring):
        str_len = len(astring)
        end_str = astring[-2]+astring[-1]
        res = astring
        if (end_str == "_0"):
            print("ESML Info: get_safe_automl_parent_run_id() did remove child _0 to get PARENT RUN, needed for rehydration of RUN")
            end = int((str_len-2))
            res = astring[0:end]
        return res
    ### 
    # Gets LATEST created model of PROMOTED status or NEW status, if get_latest_challenger=False
    # Pros: Try/Catch: Quick if DEV and INNER LOOP, and FLEXIBLE, since fallback to support search with parentless models/OUTER LOOP (across aml workspaces)
    ###
    @staticmethod
    def get_best_or_challenger_model_with_run_in_dev(experiment_name, source_workspace,get_latest_challenger=False):
        model = None
        run_id = None
        run = None
        model_name = None
        
        '''
        print("ESML INFO:IESMLController:105: get_best_or_challenger_model_with_run_in_dev(get_latest_challenger={})".format(get_latest_challenger))
        try: # Get Model and RUN at the same time
            print("ESML INFO: TRY: get_best_model_run_fitted_model_Dev")
            source_experiment, model,main_run, best_automl_run,source_fitted_model = IESMLController.get_best_model_run_fitted_model_Dev(source_workspace,experiment_name,get_latest_challenger)
            run_id = main_run.id 
            run = main_run
            model_name = model.name
            print("ESML INFO:106 run_id = main_run.id")
        except Exception as e:
        '''
        #print("ESML INFO: CATCH: get_best_model_via_modeltags_only_DevTestProd")
        #print ("ESML Warning:106:ModelCompare:101:SOURCE:Dev: Tried an optimized FETCH to get model and hydrate run at the same time - did not work. Not fetching model separately")
        source_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(source_workspace,experiment_name,get_latest_challenger)
        model=source_model
        model_name = model_name_tag
        run_id = run_id_tag
        model_name = model_name_tag

        return model,run_id,run,model_name
    ### 
    # Gets LATEST version of model, via ESML tags
    # Pros: quick, needed for parentless models (across aml workspaces)
    # Cons: Only MODEL is returned (not fitted model, not run, not experiment)
    # When to use: ESMLCompare (2) when comparing across different aml workspaces: target_environment != current_env
    # RETURNS: Model(), run_id
    ###
    @staticmethod
    def get_best_model_via_modeltags_only_DevTestProd(ws,tag_experiment_name,get_latest_challenger=False,filter_on_version=None, sort_by_created_instead_of_version=True):
        #experiment_name : 10_titanic_model_clas
        #model_name : AutoML97755f9d411
        #run_id : AutoML_97755f9d-4509-4594-8485-9e4f9cf3a419
        #trained_in_environment : test
        #trained_in_workspace : asdf
        latest_model = None
        model_highest_version = None
        all_versions_in_same_experiment = []
        run_id = None
        model_name = None
        filtered_list= None
        latest_tagged_with_status_new = None
        
        try:
            tag_esml_status = ""

            start = time.time()
            print("Searching with Model list LAMBDA FILTER, on experiment_name in Model.tags called: {} . Meaning ESML checks for both Notebook run (AutoMLRun, Run) and PipelineRuns (AutoMLStep, PipelineRun)".format(tag_experiment_name))
            print("E.g. Even if Pipeline experiment is called '11_diabetes_model_reg_IN_2_GOLD_TRAIN' it will be included, since original model_folder_name in ESML is '11_diabetes_model_reg' as a notebook Run experiment name. Both is included in search")
            all_models = Model.list(workspace=ws)

            if(filter_on_version is not None):
                print("Filter on version:ON")
                if(get_latest_challenger ==False):
                    filtered_list = list(filter(lambda r: (r.tags.get("experiment_name") == tag_experiment_name and r.version == filter_on_version 
                    and r.tags.get("status_code") != IESMLController.esml_status_new
                    and (r.tags.get("status_code") == IESMLController.esml_status_promoted_2_dev 
                    or r.tags.get("status_code") == IESMLController.esml_status_promoted_2_test
                    or r.tags.get("status_code") == IESMLController.esml_status_promoted_2_prod)
                    ), all_models))
                else:
                    filtered_list = list(filter(lambda r: (r.tags.get("experiment_name") == tag_experiment_name and r.version == filter_on_version 
                    and r.tags.get("status_code") == IESMLController.esml_status_new
                    ), all_models))

            else:
                if(get_latest_challenger ==False):
                    filtered_list = list(filter(lambda r: (r.tags.get("experiment_name") == tag_experiment_name 
                    and r.tags.get("status_code") != IESMLController.esml_status_new
                    and (r.tags.get("status_code") == IESMLController.esml_status_promoted_2_dev 
                    or r.tags.get("status_code") == IESMLController.esml_status_promoted_2_test
                    or r.tags.get("status_code") == IESMLController.esml_status_promoted_2_prod)
                    ), all_models))
                else:
                    filtered_list = list(filter(lambda r: (r.tags.get("experiment_name") == tag_experiment_name 
                    and r.tags.get("status_code") == IESMLController.esml_status_new
                    ), all_models))

            
            end = time.time()
            seconds = end - start
            minutes = seconds / 60
            print("Filter search, minutes: {}".format(minutes))

            # SORT
            if (sort_by_created_instead_of_version == True): 
                filtered_list.sort(key=lambda r: r.created_time,reverse=True)
            else:
                filtered_list.sort(key=lambda r: r.version,reverse=True)

            ## Q: Why sort on date, instead of version?
            ## A: Because Manual Run via Notebook give Model name AutoML00b58dfed0 (v17) VS PipelineRun ModelName 11_diabetes_model_reg(v 11) -> Both are TAGGED with experiment_name=11_diabetes_model_reg
            ## A: Manual run can have higher VERSION, but created EARLIER, hence .created_time always brings "latest registered model", when .version does not.
            
            if (len(filtered_list) > 0): # IF we found any...
                model_highest_version = filtered_list[0]
            else: # No models promoted - Just take latest, that is note DEMOTED
                filtered_list = list(filter(lambda r: (r.tags.get("experiment_name") == tag_experiment_name 
                and r.tags.get("status_code") != IESMLController.esml_status_demoted_or_archive
                ), all_models))
                model_highest_version = filtered_list[0]

        except Exception as e:
            print(e)
            print("Cannot find tag 'experiment_name' on all models, hence cannot use optimized search, looping manually now..." )
            start = time.time()
            print("TIME: Model list LOOP filter, on experiment_name")

            for model in Model.list(workspace=ws): # Latest=True does not work. Gave me June 32 (Sept 2022).

                if "experiment_name" not in model.tags: # KeyError...if not ESML registered MODEL
                    continue
                experiment_name = model.tags["experiment_name"] # KeyError...if not ESML registered MODEL

                #trained_in_environment = model.tags["trained_in_environment"]
                #model_name = model.tags["model_name"]
                #print("model.experiment_name", model.experiment_name) # None...for "external registrations"
                if(experiment_name== tag_experiment_name): # Get all models from same experiment (also great if same model_name...but..then we need to register as custom model_name, which is the same as expermient_name )
                    if(filter_on_version is not None):
                        if(filter_on_version == model.version):
                            latest_model = model
                            #print ("found model matching experiment_name, also matching on model_version")
                            all_versions_in_same_experiment.append(latest_model)
                            break
                    else:
                        if("status_code" in model.tags):
                            if(model.tags["status_code"] == IESMLController.esml_status_promoted_2_dev or 
                            model.tags["status_code"] == IESMLController.esml_status_promoted_2_test or model.tags["status_code"] == IESMLController.esml_status_promoted_2_prod):
                                latest_model = model
                            elif(model.tags["status_code"] == IESMLController.esml_status_new):
                                latest_tagged_with_status_new = model # 1st model, hence winning/leading model
                        else: # fallback
                            latest_model = model

                        all_versions_in_same_experiment.append(latest_model)  # All models in this experiment
            if (len(all_versions_in_same_experiment) > 0): # IF we found any...
                model_highest_version = all_versions_in_same_experiment[0] # Try to get LATEST/highest version
            else:
                model_highest_version = latest_tagged_with_status_new # If NEW only. No promoted models yet.
            end = time.time()
            seconds = end - start
            minutes = seconds / 60
            print("Minutes: {}".format(minutes))
        
        try:
            run_id = model_highest_version.tags.get("run_id")
            model_name = model_highest_version.tags.get("model_name")
        except Exception as e:
            print("Could not find tags, run_id or model_name on model_highest_version")
            print(e)

        return model_highest_version, run_id, model_name

    ###
    # Gets LATEST version of model, via TAGS, or as fallback LOOPING all Models in workspace
    # Pros: No tags/meta data needed, since fallback method.  Works on 1st timers where no model is registred/tagged. No ESML dependency.
    # Cons: - 
    # Tip when to use: Use this if you only need MODEL and want a SAFE method. ( otherwise if also RUN and FITTED_MODEL use get_best_model_and_run_via_tags_or_loop)
    ###
    @staticmethod
    def _get_best_model_via_experiment_tags_or_loop(ws,experiment_name,get_latest_challenger=False, filter_on_version = None):
        latest_model = None
        latest_tagged_with_status_new = None
        active_workspace = ws

        if(active_workspace is None):
            raise Exception("get_best_model_via_experiment_name:Azure ML workspace is null.")
        '''
        ex1 = Experiment(active_workspace, experiment_name)
        tag_model_name = None
        tag_model_version = None
        model_tag_run_id = None
        model_tag_name = None

        if (ex1.tags is not None and "best_model_version" in ex1.tags and "model_name" in ex1.tags):
            print("DEBUG: Gets the best model via experiment")
            tag_model_name = ex1.tags["model_name"]
            tag_model_version = ex1.tags["best_model_version"]
        
            if (filter_on_version is not None):
                latest_model = Model(active_workspace, name=tag_model_name, version=filter_on_version)
                #print ("found model via REMOTE FILTER + VersionFilter as input.Tags: mode_name, model_version")
            else:
                latest_model = Model(active_workspace, name=tag_model_name, version=tag_model_version)
                #print ("found model via REMOTE FILTER: Experiment TAGS: model_name")
        else:
        '''
        print ("Searching model - LOOPING the experiment to match name (1st time thing, since no tags)")
        for m in Model.list(active_workspace):
            if(m.experiment_name == experiment_name):
                
                if(filter_on_version is not None):
                    if(filter_on_version == m.version):
                        latest_model = m
                        #print ("found model matching experiment_name, also matching on model_version")
                        break
                else:
                    if("status_code" in m.tags):
                        if(get_latest_challenger == False):
                            if(m.tags["status_code"] == IESMLController.esml_status_promoted_2_dev or 
                            m.tags["status_code"] == IESMLController.esml_status_promoted_2_test or m.tags["status_code"] == IESMLController.esml_status_promoted_2_prod):
                                latest_model = m
                        elif(m.tags["status_code"] == IESMLController.esml_status_new):
                            latest_model = m # new model
                    else: # fallback
                        latest_model = m
                    #print ("found model matching experiment_name, selecting latest registered.")
                break
                
        if (latest_model is not None): # Update Experiment tag
            ex = Experiment(active_workspace, experiment_name)
            if("status_code" in latest_model.tags):
                tags = {'model_name':latest_model.name, 'best_model_version':latest_model.version,"status_code":latest_model.tags["status_code"]}
            else:
                tags = {'model_name':latest_model.name, 'best_model_version':latest_model.version}
            ex.set_tags(tags)
        '''
        elif(latest_tagged_with_status_new is not None):
            ex = Experiment(active_workspace, experiment_name)
            tags = {'model_name':latest_tagged_with_status_new.name, 'best_model_version':latest_tagged_with_status_new.version,
                "status_code":latest_tagged_with_status_new.tags["status_code"]  }
            ex.set_tags(tags)
            latest_model = latest_tagged_with_status_new
            print("Note: There was no models earlier promoted, the latest NEW model, is the leading one. latest_model = latest_tagged_with_status_new")
        '''

        try:
            if (latest_model is not None):
                model_tag_run_id = latest_model.tags["run_id"]
                model_tag_name = latest_model.tags["model_name"]
        except: 
            print("Could not find tags, run_id or model_name on latest_model")

        return latest_model,model_tag_run_id,model_tag_name


###
# REGISTER model, abstract implemented method
# Note: For last parameter 'esml_status', please use IESMLController.esml_status_... properties, such as IESMLController.esml_status_new
# returns: model_registered_in_target
###

    def register_model(self,source_ws, target_env, source_model=None, run=None, esml_status=None,model_path=None,extra_model_tags=None):
        #input
        source_env = self.dev_test_prod
        source_ws_name = source_ws.name
        target_workspace = None

        #returns
        model_registered_in_target = None
        model_source = None

        if (source_env == "prod"):
            raise Exception("Source environment cannot be PROD, cannot register from PROD to PROD, or from PROD to X. Source must be DEV or TEST")
            target_workspace = source_ws # Last stop. Prod->Prod

        if(esml_status is None): # default behavoiur is to PROMOTE if register to TEST and PROD, pass esml_status as parameter to override this behaviour
            if (target_env == "test"):
                esml_status = IESMLController.esml_status_promoted_2_test
            elif (target_env == "prod"):
                esml_status = IESMLController.esml_status_promoted_2_prod
            elif (target_env == "dev"):
                pass # The user decides, can be esml_status_not_new or esml_status_promoted_2_dev
            else:
                esml_status = IESMLController.esml_status_new # default value
        
        target_workspace = self.get_other_workspace(source_ws,target_env) # dev, test, prod
        dev_workspace = self.get_other_workspace(source_ws, "dev")
        
        model_name = None
        model = None
        if(source_model is not None): # no model
            model_name = source_model.name
            model = source_model
        elif(run is None):  #no run
            print("source_model_to_copy_tags_from is None...1st time")
            current_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(dev_workspace,self.experiment_name)
            #experiment, source_model_to_copy_tags_from, main_run,best_automl_run, fitted_model = IESMLController.get_best_model_run_fitted_model_Dev(dev_workspace,self.experiment_name)
            model_name = current_model.name
            model = current_model

        # 2a) Register model (If DEV to DEV, we can get more lineage and metadata, since an actual RUN exists (Run, AutoMLRun, AutoMLStep that has an AutoMLRun))
        if(target_env == "dev"): 
            if(run is not None): # Probably Run from notebook, not pipelinerun
                experiment = dev_workspace.experiments[self.experiment_name]
                #try:
                #    model_name = run.properties['model_name']
                #except Exception as e:
                #    print("Could not get model_name from run.properties")
                #    print(e)

                #print("registering model with name: {}, from run.".format(model_name))
                model_registered_in_target = self._register_model_on_run(source_model,model_name,source_env,source_ws_name,run,experiment,esml_status,model_path,extra_model_tags)
            else: # fall back...
                model_registered_in_target, model_source = self._register_model_in_correct_workspace("dev", dev_workspace, "dev",new_model=model,esml_status=esml_status)

            #model_registered_in_target = self._register_model_on_run(source_model_to_copy_tags_from,model_name,source_env,source_ws_name,main_run,experiment)
        else: # 2b) If target is TEST or PROD, we dont have a RUN to connect to - only a MODEL registry
            if(target_env == "test"):  # run or experiment in SOURCE exists
                model_registered_in_target, model_source = self._register_model_in_correct_workspace(source_env, source_ws, target_env,new_model=model,esml_status=esml_status)
            elif(target_env == "prod" and source_env=="test"): # No run or experiment in SOURCE
                source_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(target_workspace,self.experiment_name)
                model_registered_in_target, model_source = self._register_model_in_correct_workspace(source_env, source_ws, target_env,new_model=model,esml_status=esml_status)
            elif(target_env == "prod" and source_env=="dev"): # Run or experiment in SOURCE exists (skip TEST is never recommended, but possible)
                model_registered_in_target, model_source = self._register_model_in_correct_workspace(source_env, source_ws, target_env,new_model=model,esml_status=esml_status)

        return model_registered_in_target
                

    ###
    # Maps ESML status to MLFlow stages. Is tagged on Model
    ##
    @staticmethod
    def _get_flow_equivalent(esml_status):
        ml_flow_stage = "None"

        if(esml_status == IESMLController.esml_status_new):
            ml_flow_stage = "None"
        elif(esml_status == IESMLController.esml_status_demoted_or_archive): # Demoted or already compared and failed.
            ml_flow_stage = "Archive"
        elif(esml_status == IESMLController.esml_status_promoted_2_dev or esml_status == IESMLController.esml_status_promoted_2_test): # Staging
            ml_flow_stage = "Staging"
        elif(esml_status == IESMLController.esml_status_promoted_2_prod): # Staging
            ml_flow_stage = "Production"
        return ml_flow_stage

    def _register_model_on_run(self,source_model_to_copy_tags_from,model_name, source_env,source_ws_name, remote_run, experiment, esml_status=None,model_path=None, extra_model_tags=None):
        #remote_run, experiment = self._get_active_model_run_and_experiment(target_workspace,target_env, override_enterprise_settings_with_model_specific) # 2022-08-08 do not READ anything to disk/file
        #  # 2022-05-02: best_run.run_id -> AttributeError: 'Run' object has no attribute 'run_id'

        run_id = remote_run.id

        time_stamp = str(datetime.datetime.now())
        tags = {"esml_time_updated": time_stamp, "run_id": run_id, "model_name": model_name, "trained_in_environment": source_env, 
        "trained_in_workspace": source_ws_name, "experiment_name": experiment.name}

        if(source_model_to_copy_tags_from is not None):
            if("test_set_ROC_AUC" in source_model_to_copy_tags_from.tags):
                tags["test_set_Accuracy"] = source_model_to_copy_tags_from.tags["test_set_Accuracy"]
                tags["test_set_ROC_AUC"] = source_model_to_copy_tags_from.tags["test_set_ROC_AUC"]
                tags["test_set_Precision"] = source_model_to_copy_tags_from.tags["test_set_Precision"]
                tags["test_set_Recall"] = source_model_to_copy_tags_from.tags["test_set_Recall"]
                tags["test_set_F1_Score"] = source_model_to_copy_tags_from.tags["test_set_F1_Score"]
                tags["test_set_Matthews_Correlation"] = source_model_to_copy_tags_from.tags["test_set_Matthews_Correlation"]
                tags["test_set_CM"] = source_model_to_copy_tags_from.tags["test_set_CM"]
            if("test_set_RMSE" in source_model_to_copy_tags_from.tags):
                tags["test_set_RMSE"] = source_model_to_copy_tags_from.tags["test_set_RMSE"]
                tags["test_set_R2"] = source_model_to_copy_tags_from.tags["test_set_R2"]
                tags["test_set_MAPE"] = source_model_to_copy_tags_from.tags["test_set_MAPE"]
                tags["test_set_Spearman_Correlation"] = source_model_to_copy_tags_from.tags["test_set_Spearman_Correlation"]
            if("esml_time_updated " in source_model_to_copy_tags_from.tags):
                tags["esml_time_updated"] = source_model_to_copy_tags_from.tags["esml_time_updated"]

        if(esml_status is not None):
            tags["status_code"] = esml_status
        else:
            tags["status_code"]=IESMLController.esml_status_new

        try:
            tags["mflow_stage"] = IESMLController._get_flow_equivalent(tags["status_code"])
        except: 
            print ("Warning: Could not map MFLow stages from ESML status. Hence to tag for this. Source: IESMLController._get_flow_equivalent(esml_status_code)")

        if(extra_model_tags is not None):
            tags = {**tags, **extra_model_tags}
            #tags.update(extra_model_tags) # status_code : {'status_code': 'esml_newly_trained', 'trained_with': 'AutoMLRun'}

        print("model_name at remote_run.register_model: ", model_name)
        print("model_path (will override model_name when register) at remote_run.register_model: ", model_path)
        model = None
        if(model_path is not None):
            model = remote_run.register_model(model_name=model_name,model_path=model_path, tags=tags, description="") # Works, if manual ML you need to specify path where you saved model.
        else:
            model = remote_run.register_model(model_name=model_name, tags=tags, description="") # Works. If AutoML, pass the MAIN_RUN of AutoML that has AutoMLSettings property
            
        #model_path = "outputs/model.pkl"
        #print("model_name: before remote_run.register_model {} and model_path {}".format(model_name,model_path))
        #model = remote_run.register_model(model_name=model_name,model_path=model_path, tags=tags,properties=tags, description="") #  TypeError: register_model() got an unexpected keyword argument 'model_path'
        print("model.version", model.version)

        # Also TAG Experiemnt with model and version - if this is the leading model
        if(tags["status_code"] == IESMLController.esml_status_promoted_2_dev or tags["status_code"] == IESMLController.esml_status_promoted_2_test or tags["status_code"] == IESMLController.esml_status_promoted_2_prod):
            tags = {'model_name':model_name, 'best_model_version': str(model.version)}
            experiment.set_tags(tags)

        print("Model name {} is registered.".format(model.name))
        return model

    