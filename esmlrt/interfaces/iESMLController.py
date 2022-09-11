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
from azureml.exceptions import ProjectSystemException
import joblib
import time

class IESMLController:
    __metaclass__ = ABCMeta

    # Sub, RG, WS
    subscription_id = 'ca0a8c40-b06a-4e4e-8434-63c03a1dee34'
    resource_group = 'abc-def-esml-project002-weu-dev-004-rg'
    workspace_name = 'aml-prj002-weu-dev-003'

    # Dev, Test, Prod
    
    _subscription_id_dev = 'ca0a8c40-b06a-4e4e-8434-63c03a1dee34'
    _subscription_id_test = 'ca0a8c40-b06a-4e4e-8434-63c03a1dee34'
    _subscription_id_prod = 'ca0a8c40-b06a-4e4e-8434-63c03a1dee34'

    _resource_group_dev = 'MSFT-WEU-EAP_PROJECT02_AI-DEV-RG'
    _resource_group_test = 'MSFT-WEU-EAP_PROJECT02_AI-test-RG'
    _resource_group_prod = 'todo'

    _workspace_name_dev = 'msft-weu-dev-eap-proj02_ai-amls'
    _workspace_name_test = 'msft-weu-test-eap-proj02_ai-amls'
    _workspace_name_prod = 'todo'
    
    ## Auth
    _supported_revision = '1.4'
    _dev_test_prod = "dev"

    _iModelCompare = None
    _iTestScoringFactory = None
    _iTrainer = None

    _resource_configuration = None
    _secret_name_tenant = "esml-tenant-id"
    _secret_name_project_sp_id = "esml-project-sp-id"
    _secret_name_project_sp_secret = "esml-project-sp-secret"

    _esml_project_folder_name = None
    _esml_model_name = None
    _esml_model_alias = None

    # STATUS
    esml_status_new = "esml_newly_trained"
    esml_status_not_new = "esml_not_newly_trained"
    esml_status_promoted = "esml_promoted"

    @classmethod
    def version(self): return "1.4"

    def __init__(self,modelCompare,testScoringFactory, esml_project_folder_name, esml_model_name, esml_model_alias, secret_name_tenant = None,secret_name_project_sp_id= None,secret_name_project_sp_secret = None):

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

    ###
    # properties
    ###
    @property
    @abstractmethod
    def dev_test_prod(self):
        return self._dev_test_prod

    @dev_test_prod.setter
    def dev_test_prod(self, dev_test_prod):

        if(dev_test_prod == "dev"):
            self.subscription_id = self._subscription_id_dev
            self.resource_group = self._resource_group_dev
            self.workspace_name = self._workspace_name_dev
        elif(dev_test_prod == "test"):
            self.subscription_id = self._subscription_id_test
            self.resource_group = self._resource_group_test
            self.workspace_name = self._workspace_name_test
        elif(dev_test_prod == "prod"):
            self.subscription_id = self._subscription_id_prod
            self.resource_group = self._resource_group_prod
            self.workspace_name = self._workspace_name_prod

        self._dev_test_prod = dev_test_prod


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
        kv = source_ws.get_default_keyvault() # Get "current" workspace, either CLI Authenticated if MLOps, or in DEMO/DEBUG Interactive
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
    # Pros: Quick it TAGS exists (since ModelName and RunId is known no looping nessesary), and safe as 1st time when to TAGS exists.
    # Cons: Only works in DEV (not TEST, PROD) Do not work, fetching parentless Model. Needs an experiment and run
    # Tip when to use: When comparing within same Azure ML workspace. QUICK and SAFE within workspace
    ###
    @staticmethod
    def get_best_model_run_fitted_model_Dev(ws,experiment_name, filter_on_version = None):
        model,run_id,model_name = IESMLController._get_best_model_via_experiment_tags_or_loop(ws,experiment_name,filter_on_version) # 2021-09 update

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

     ### 
    # Gets LATEST version of model, via ESML tags
    # Pros: quick, needed for parentless models (across aml workspaces)
    # Cons: Only MODEL is returned (not fitted model, not run, not experiment)
    # When to use: ESMLCompare (2) when comparing across different aml workspaces: target_environment != current_env
    # RETURNS: Model(), run_id
    ###
    @staticmethod
    def get_best_model_via_modeltags_only_DevTestProd(ws,tag_experiment_name,filter_on_version=None, sort_by_created_instead_of_version=True):
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
        
        try:
            tag_esml_status = ""

            start = time.time()
            print("TIME: Model list LAMBDA FILTER, on experiment_name {}".format(tag_experiment_name))
            all_models = Model.list(workspace=ws)
            if(filter_on_version is not None):
                print("Filter on version:ON")
                filtered_list = list(filter(lambda r: (r.tags.get("experiment_name") == tag_experiment_name and r.version == filter_on_version and r.tags.get("status_code") != IESMLController.esml_status_new), all_models))
            else:
                filtered_list = list(filter(lambda r: (r.tags.get("experiment_name") == tag_experiment_name and r.tags.get("status_code") != IESMLController.esml_status_new), all_models))
            
            print("TIME: FILTER ModelList:")
            end = time.time()
            seconds = end - start
            minutes = seconds / 60
            print("Minutes: {}".format(minutes))

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
                        latest_model = model
                        all_versions_in_same_experiment.append(latest_model)  # All models in this experiment
            if (len(all_versions_in_same_experiment) > 0): # IF we found any...
                model_highest_version = all_versions_in_same_experiment[0] # Try to get LATEST/highest version
            end = time.time()
            seconds = end - start
            minutes = seconds / 60
            print("Minutes: {}".format(minutes))
        
        try:
            run_id = model_highest_version.tags["run_id"]
            model_name = model_highest_version.tags["model_name"]
        except: 
            print("Could not find tags, run_id or model_name on model_highest_version")

        return model_highest_version, run_id, model_name

    ###
    # Gets LATEST version of model, via TAGS, or as fallback LOOPING all Models in workspace
    # Pros: No tags/meta data needed, since fallback method.  Works on 1st timers where no model is registred/tagged. No ESML dependency.
    # Cons: - 
    # Tip when to use: Use this if you only need MODEL and want a SAFE method. ( otherwise if also RUN and FITTED_MODEL use get_best_model_and_run_via_tags_or_loop)
    ###
    @staticmethod
    def _get_best_model_via_experiment_tags_or_loop(ws,experiment_name,filter_on_version = None):
        latest_model = None
        active_workspace = ws

        if(active_workspace is None):
            raise Exception("get_best_model_via_experiment_name:Azure ML workspace is null.")

        ex1 = Experiment(active_workspace, experiment_name) # Can be other workspace (dev,test,prod), but same experiment name
        tag_model_name = None
        tag_model_version = None
        model_tag_run_id = None
        model_tag_name = None

        if (ex1.tags is not None and "best_model_version" in ex1.tags and "model_name" in ex1.tags):
            tag_model_name = ex1.tags["model_name"]
            tag_model_version = ex1.tags["best_model_version"]
        
            if (filter_on_version is not None):
                latest_model = Model(active_workspace, name=tag_model_name, version=filter_on_version)
                #print ("found model via REMOTE FILTER + VersionFilter as input.Tags: mode_name, model_version")
            else:
                latest_model = Model(active_workspace, name=tag_model_name, version=tag_model_version)
                #print ("found model via REMOTE FILTER: Experiment TAGS: model_name")
        else:
            print ("Searching model - LOOPING the experiment to match name (1st time thing, since no tags)")
            for m in Model.list(active_workspace):
                if(m.experiment_name == experiment_name):
                    
                    if(filter_on_version is not None):
                        if(filter_on_version == m.version):
                            latest_model = m
                            #print ("found model matching experiment_name, also matching on model_version")
                            break
                    else:
                        latest_model = m
                        #print ("found model matching experiment_name, selecting latest registered.")
                    break
                    
            if (latest_model is not None): # Update Experiment tag
                ex = Experiment(active_workspace, experiment_name)
                tags = {'model_name':latest_model.name, 'best_model_version':m.version}
                ex.set_tags(tags)

        try:
            model_tag_run_id = latest_model.tags["run_id"]
            model_tag_name = latest_model.tags["model_name"]
        except: 
            print("Could not find tags, run_id or model_name on latest_model")

        return latest_model,model_tag_run_id,model_tag_name


###
# REGISTER model, abstract implemented method
# Note: For last parameter 'esml_status', please use IESMLController.esml_status_... properties, such as IESMLController.esml_status_not_new
# returns: model_registered_in_target
###

    def register_model(self,source_ws, target_env, source_model=None, run=None, esml_status=None,extra_model_tags=None):
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

        if(esml_status is None):
            esml_status = IESMLController.esml_status_not_new
        
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
                try:
                    model_name = run.properties['model_name']
                except Exception as e:
                    print("Could not get model_name from run.properties")
                    print(e)

                print("registering model with name: {}, from run.".format(model_name))
                model_registered_in_target = self._register_model_on_run(source_model,model_name,source_env,source_ws_name,run,experiment,esml_status,extra_model_tags)
            else: # fall back...
                model_registered_in_target, model_source = self._register_model_in_correct_workspace("dev", dev_workspace, "dev",new_model=model)

            #model_registered_in_target = self._register_model_on_run(source_model_to_copy_tags_from,model_name,source_env,source_ws_name,main_run,experiment)
        else: # 2b) If target is TEST or PROD, we dont have a RUN to connect to - only a MODEL registry
            if(target_env == "test"):  # run or experiment in SOURCE exists
                model_registered_in_target, model_source = self._register_model_in_correct_workspace(source_env, source_ws, target_env,new_model=model)
            elif(target_env == "prod" and source_env=="test"): # No run or experiment in SOURCE
                source_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(target_workspace,self.experiment_name)
                model_registered_in_target, model_source = self._register_model_in_correct_workspace(source_env, source_ws, target_env,new_model=model)
            elif(target_env == "prod" and source_env=="dev"): # Run or experiment in SOURCE exists (skip TEST is never recommended, but possible)
                model_registered_in_target, model_source = self._register_model_in_correct_workspace(source_env, source_ws, target_env,new_model=model)

        return model_registered_in_target
                


    def _register_model_on_run(self,source_model_to_copy_tags_from,model_name, source_env,source_ws_name, remote_run, experiment, esml_status=None, extra_model_tags=None):
        #remote_run, experiment = self._get_active_model_run_and_experiment(target_workspace,target_env, override_enterprise_settings_with_model_specific) # 2022-08-08 do not READ anything to disk/file
        #  # 2022-05-02: best_run.run_id -> AttributeError: 'Run' object has no attribute 'run_id'

        run_id = remote_run.id # TODO does .run_id exists in PipelineRun? (.id) It does in a ScriptRun.
        tags = {"run_id": run_id, "model_name": model_name, "trained_in_environment": source_env, 
        "trained_in_workspace": source_ws_name, "experiment_name": experiment.name}

        if(source_model_to_copy_tags_from is not None):
            if("test_set_ROC_AUC" in source_model_to_copy_tags_from.tags):
                tags["test_set_Accuracy"] = source_model_to_copy_tags_from.tags["test_set_Accuracy"]
                tags["test_set_ROC_AUC"] = source_model_to_copy_tags_from.tags["test_set_ROC_AUC"]
                tags["test_set_Precision"] = source_model_to_copy_tags_from.tags["test_set_Precision"]
                tags["test_set_Recall"] = source_model_to_copy_tags_from.tags["test_set_Recall"]
                tags["test_set_F1_Score"] = source_model_to_copy_tags_from.tags["test_set_F1_Score"]
                tags["test_set_Matthews_Correlation"] = source_model_to_copy_tags_from.tags["test_set_Matthews_Correlation"]
                tags["test_set_CM"] = source_model_to_copy_tags_from.tags["source_model_to_copy_tags_from"]
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

        if(extra_model_tags is not None):
            tags = {**tags, **extra_model_tags}
            #tags.update(extra_model_tags) # status_code : {'status_code': 'esml_newly_trained', 'trained_with': 'AutoMLRun'}

        print("model_name at emote_run.register_model: ", model_name)
        model = remote_run.register_model(model_name=model_name, tags=tags, description="") # Works. If AutoML, pass the MAIN_RUN of AutoML that has AutoMLSettings property
        
        #model_path = "outputs/model.pkl"
        #print("model_name: before remote_run.register_model {} and model_path {}".format(model_name,model_path))
        #model = remote_run.register_model(model_name=model_name,model_path=model_path, tags=tags,properties=tags, description="") #  TypeError: register_model() got an unexpected keyword argument 'model_path'
        print("model.version", model.version)

        #self.write_run_config(experiment.name, model.name,remote_run.run_id, target_env, model.version) # 2022-08-08 do not WRITE anything to disk/file

        # Also TAG Experiemnt with model and version
        tags = {'model_name':model_name, 'best_model_version': str(model.version)}
        experiment.set_tags(tags)

        print("Model name {} is registered.".format(model.name))
        return model

    