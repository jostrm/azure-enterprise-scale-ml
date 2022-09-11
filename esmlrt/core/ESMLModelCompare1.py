import os
import json
from azureml.core import Experiment
from azureml.core import Model
from azureml.train.automl.run import AutoMLRun
from azureml.pipeline.core import PipelineRun
from azureml.telemetry import UserErrorException
import sklearn
import tempfile
from azureml.core.resource_configuration import ResourceConfiguration
from interfaces.iESMLModelCompare import IESMLModelCompare
from interfaces.iESMLController import IESMLController
#from ..interfaces.iESMLModelCompare import IESMLModelCompare

class ESMLModelCompare(IESMLModelCompare):

    dev_test_prod = "dev"
    project = None
    active_model_config = None
    debug_always_promote_model = False
    model_settings = None
    model_name_automl = "AutoML_Generated_Name"
    
    metrics_output_name = 'metrics_output' # PipelineRun
    best_model_output_name = 'best_model_output'
    

    def __init__(self,project):
        if not isinstance(project, IESMLController): raise Exception('Bad interface. Should be IESMLController')
        if not IESMLController.version() == '1.4': raise Exception('Bad revision')

        self.project = project

    def LoadConfiguration(self, dev_test_prod, override_enterprise_settings_with_model_specific = True):
        old_loc = os.getcwd()
        
        try:
            if(dev_test_prod != "dev" and dev_test_prod != "test" and dev_test_prod != "prod"):
                raise ValueError("dev_test_prod needs to be either: 'dev','test', or 'prod' - but it is={}".format(dev_test_prod))
            self.dev_test_prod = dev_test_prod

            os.chdir(os.path.dirname(__file__))

            #user_settings = "../../"
            user_settings = ""

            start_path = "enterprise_specific/dev_test_prod_defaults"
            if (override_enterprise_settings_with_model_specific):
                start_path = "project_specific/model/dev_test_prod_override"
            automl_active_path = "project_specific/model/dev_test_prod"

            if(self.dev_test_prod == "dev"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_dev.json".format(user_settings,automl_active_path)) as f:
                    self.active_model_config = json.load(f)
            if(self.dev_test_prod == "test"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_test.json".format(user_settings,automl_active_path)) as f:
                    self.active_model_config = json.load(f)
            if(self.dev_test_prod == "prod"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_prod.json".format(user_settings,automl_active_path)) as f:
                    self.active_model_config = json.load(f)

            # Model specific settings - for all environments
            with open("{}../settings/project_specific/model/model_settings.json".format(user_settings,automl_active_path)) as f:
                self.model_settings = json.load(f)

        except Exception as e:
            raise ValueError("ESMLModelCompare - LoadConfiguration - could not open .json config files: automl_env.json") from e
        finally: 
            os.chdir(old_loc) # Change back working location...

    def get_task_type(self, target_run):
        my_dictionary = target_run.get_properties()
        j_str = my_dictionary['AMLSettingsJsonString']
        j_dic = json.loads(j_str)
        task_type = j_dic['task_type']
        return task_type
    
    
    def connect_to_target_workspace(self, target_environment = None):
        p = self.project
        current_env = p.dev_test_prod

        if (target_environment is None): # if DEV -> then TEST
            target_environment= p.get_next_environment()
            #raise UserErrorException("You must set a TARGET environement. It can be same as SOURCE. 'dev' to 'dev' is OK, or 'dev' -> 'test', 'text'->'prod'")

        if (target_environment== "prod" and p.dev_test_prod=="test"): # target=PROD -> compare against previous models in PROD...highest level
            print ("Connect from TEST to PROD ( if you want to compare TEST-model with latest registered in PROD subscription/workspace")
            print("")
            try:
                #p.dev_test_prod = "prod" # get settings for target
                #auth = AzureCliAuthentication()
                ##target_workspace = Workspace.get(name = p.workspace_name,subscription_id = p.subscription_id,resource_group = p.resource_group,auth=cli_auth)
                target_workspace = p.get_other_workspace(target_environment)
            finally:
                pass
                #p.dev_test_prod = current_env # flip back to TEST
        elif (target_environment == "test" and p.dev_test_prod == "dev"): # target=test -> compare againt previous stage "dev"
            print ("Connect from DEV to TEST subscription/workspace  ( if you want to compare TEST-model with latest registered in PROD")
            print("")
            try:
                target_workspace = p.get_other_workspace(target_environment)
            finally:
                pass
                #p.dev_test_prod = current_env # flip back to DEV
        elif (target_environment == p.dev_test_prod ): # -> compare againt previous model in same "dev" workspace
            print ("target=source environement. Compare model version in DEV/TEST/PROD with latest registered in same DEV/TEST/PROD workspace (same workspace & subscriptiom comparison)")
            print("")
            target_workspace = p.ws
        
        return target_workspace
    '''
     if (target_environment == "dev" & p.dev_test_prod = "dev") -> compare againt  stage "dev" -> Should be same if no difference is made
     if (target_environment== "test" & p.dev_test_prod = "dev") -> compare againt next stage "test" -> should always be better in TEST, since longer traininng run
     if (target_environment == "prod" & & p.dev_test_prod = "test") -> compare "test" againt next stage "prod"  -> TEST and PROD might be same
     if (target_environment == "prod" & & p.dev_test_prod = "dev") -> Exception! Should always use corret staging cycle. Not "jump over"
    '''
    def compare_scoring_current_vs_new_model(self, target_environment = None):
        self.LoadConfiguration(self.project.dev_test_prod, self.project.override_enterprise_settings_with_model_specific)
        p = self.project
        source_workspace = p.ws
        target_workspace = None
        experiment_name = self.project.model_folder_name
        promote_new_model = False
        current_env = self.project.dev_test_prod
        
        if (target_environment is None): # if DEV -> then TEST
            target_environment= self.get_next_environment(p)
            #raise UserErrorException("You must set a TARGET environement. It can be same as SOURCE. 'dev' to 'dev' is OK, or 'dev' -> 'test', 'text'->'prod'")
        
        if (target_environment== "prod" and p.dev_test_prod=="test"): # target=PROD -> compare against previous models in PROD...highest level
            print ("Compare model version in TEST with latest registered in PROD subscription/workspace")
            print("")
            try:
                #p.dev_test_prod = "prod" # get settings for target
                #auth = AzureCliAuthentication()
                ##target_workspace = Workspace.get(name = p.workspace_name,subscription_id = p.subscription_id,resource_group = p.resource_group,auth=cli_auth)
                target_workspace = p.get_other_workspace(target_environment)
            finally:
                p.dev_test_prod = current_env # flip back to TEST
        elif (target_environment == "test" and p.dev_test_prod == "dev"): # target=test -> compare againt previous stage "dev"
            print ("Compare model version in DEV with latest registered in TEST subscription/workspace")
            print("")
            try:
                target_workspace = p.get_other_workspace(target_environment)
            finally:
                p.dev_test_prod = current_env # flip back to DEV
        elif (target_environment == p.dev_test_prod ): # -> compare againt previous model in same "dev" workspace
            print ("target=source environement. Compare model version in DEV/TEST/PROD with latest registered in same DEV/TEST/PROD workspace (same workspace & subscriptiom comparison)")
            print("")
            target_workspace = source_workspace

        
        # NEW model (Not registered) - fetch from json
        new_run_id = self.active_model_config["run_id"] # Should NOT be empty, either -1 or AutoML GUID 
        print("new_run_id",new_run_id)

        new_experiment_name = self.active_model_config["experiment_name"]
        new_model_name = self.active_model_config["model_name_automl"]
        new_dev_test_prod = self.active_model_config["dev_test_prod"]

        previous_registered_model_version = self.active_model_config["registered_model_version"] # Can be -1 if never registered
 
         # SOURCE (latest registered) vs TARGET (latest registered)
        source_model_name = ""
        source_metrics = None
        source_task_type = None
        #source_best_run_id = None 

        target_model_name = ""
        target_best_run_id = None
        target_metrics = None
        target_task_type = None
        source_model = None

        #if(source_model is None):
        if(not new_run_id):
            print("No run_id for source model. Need to train a model in environment: {}, nothing to evaluate for now. If target exists, its better than nothing.".format(target_environment))
            promote_new_model = False
            return promote_new_model,source_model_name,None,target_model_name, target_best_run_id,target_workspace,None
        else:
            #try: # GET source from saved new RUN_ID
            if (target_environment != current_env): # If REGISTER model in other WORKSPACE, no Run or Experiment exists
                source_model = p.get_best_model_via_modeltags_only(source_workspace,experiment_name,filter_on_version=None)
                source_exp = Experiment(workspace=source_workspace, name=experiment_name) # Fetch the OLD run from SOURCE () TODO: What if TEST->PROD and both are just "registered" from DEV?)
                source_best_run_id = source_model.tags["run_id"]
                source_run = AutoMLRun(experiment=source_exp, run_id=source_best_run_id)
                
                source_best_run, source_fitted_model = source_run.get_output()
                source_task_type = self.get_task_type(source_run)
                source_model_name = source_best_run.properties['model_name']
                source_model = Model(source_workspace, name=source_model_name) # LAtest best version
            else: # Same source=target, may be 1st time of model
                source_exp = Experiment(workspace=source_workspace, name=experiment_name)
                source_run = AutoMLRun(experiment=source_exp, run_id=new_run_id)  # From local cache..Assume just retrained model.

                source_best_run, source_fitted_model = source_run.get_output()
                source_model_name = source_best_run.properties['model_name']

                print ("active_model_config from 'automl_active_model_env.json': source_model_name:",source_model_name)
                #print ("active_model_config automl_active_model_env.json: new_run_id:",new_run_id)
                #print ("active_model_config automl_active_model_env.json: source_workspace:",source_workspace)
                #print ("active_model_config automl_active_model_env.json: experiment_name:",experiment_name)

                source_task_type = self.get_task_type(source_run)
                try:
                    source_model = Model(source_workspace, name=source_model_name) # LAtest best version
                except: 
                    promote_new_model = True
                    print("Could not find EXISTING MODEL with same experiment name = No TARGET run. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))

            #except Exception as e1:
            #     raise UserErrorException("Cannot find SOURCE AutoMLRun for model best run id {}, in environment {}. Try register model manually".format(new_run_id, p.dev_test_prod)) from e1

        try: # Compare latest SOURCE_MODEL with TARGET_MODEL
            if(target_workspace == source_workspace): # dev->dev, or test->test, or prod->prod
                 print("TARGET is in the same Azure ML Studio workspace as SOURCE, comparing with latest registered model...")
            
            #target_model, target_best_run_id = AutoMLFactory(p).get_latest_model(target_workspace)
            #target_model, target_best_run_id = AutoMLFactory(p).get_latest_model_from_experiment_name(target_workspace,experiment_name)
            target_exp, model,target_run, target_best_run,target_model = None,None,None,None,None
            try:
                
                if (target_environment != current_env): # If REGISTER model in other WORKSPACE, no Run or Experiment exists
                    target_model = p.get_best_model_via_modeltags_only(target_workspace,experiment_name,filter_on_version=None)
                    source_exp = Experiment(workspace=source_workspace, name=experiment_name) # Fetch the OLD run from SOURCE () TODO: What if TEST->PROD and both are just "registered" from DEV?)
                    target_best_run_id = target_model.tags["run_id"]
                    target_run = AutoMLRun(experiment=source_exp, run_id=target_best_run_id)
                    target_best_run, fitted_model = source_run.get_output()
                else:
                    target_exp, target_model,target_run, target_best_run,fitted_model = p.get_best_model_and_run_via_experiment_name_and_ws(target_workspace)  # 2021-12-09  WORKS dev_2_test and DEV..but not if "mixed as TEST"

                    #######
                    #target_model = p.get_best_model_via_modeltags_only(target_workspace,experiment_name,filter_on_version=None) # 2021-12-09 test below...
                    #print("target_model is ...{}".format( target_model.name))
                    #target_exp = Experiment(workspace=source_workspace, name=experiment_name) # Fetch the OLD run from SOURCE () TODO: What if TEST->PROD and both are just "registered" from DEV?)
                    #target_best_run_id = target_model.tags["run_id"]
                    #target_run = AutoMLRun(experiment=target_exp, run_id=target_best_run_id)
                    #target_best_run, fitted_model = source_run.get_output()
                    #######

                if(target_model is not None):
                    target_best_run_id = target_model.tags["run_id"] # model.tags.get("run_id") Example: AutoML_08bb87d4-9587-4b99-b781-fe16bd13f140
                    target_model_name = target_model.tags["model_name"]
                    target_best_model_version = target_model.version

                    #print("Target found (registered):")
                    #print(" Target - best_run_id", target_best_run_id)
                    #print(" Target - best_run_id (best run)", target_best_run.id)
                    #print(" Target - model_name (from model.tag)",target_model_name)
                    #print("target - model_name (from target_best_run.properties[''model_name'])",target_best_run.properties['model_name'] )
                    #print(" Target - model_version",target_best_model_version)
            except Exception as e1:
                print(e1)
                promote_new_model = True
                print("Could not find EXISTING MODEL with same experiment name = No TARGET run. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
                                
            if(target_model is not None):
                if(target_environment != current_env):
                    target_task_type = source_task_type # Asssume same type, if REGISTER model in other WORKSPACE
                else:
                    print("target_best_run_id", target_best_run_id)

                    if (target_best_run_id is not None): 
                        #target_model_name = target_best_run.properties['model_name'] # model.name
                        try:
                            target_task_type = self.get_task_type(target_run)
                        except:
                            target_task_type = source_task_type # Asssume same type, if REGISTER model in other WORKSPACE
                    else: 
                        promote_new_model = True
                        print("No TARGET run_id. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
            else:
                promote_new_model = True
                print("No TARGET MODEL. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
        except Exception as e:
            raise e
            #raise UserErrorException("Unkown error. Cannot load TARGET AutoMLRun for model best run id {}, in environment {}. Try register model manually".format(target_best_run_id, target_environment)) from e
        
        # IF we have a target to compare with
        if (promote_new_model == False):
            promote_new_model = self.promote_model(source_best_run, target_best_run,target_best_run_id,source_task_type, target_task_type,source_model,target_model)
        # END, IF we have a target to compare with
        
        # Save NEW model (Not registered)
        self.model_name_automl = source_model_name
        if promote_new_model:
            self.write_run_config(new_experiment_name, source_model_name, new_run_id, new_dev_test_prod)
        #else:
        #    self.write_run_config(new_experiment_name, source_model_name, -1, new_dev_test_prod) 

        return promote_new_model,source_model_name,new_run_id,target_model_name, target_best_run_id,target_workspace,source_model

    # https://docs.microsoft.com/en-us/python/api/azureml-automl-core/azureml.automl.core.shared.constants.tasks?view=azure-ml-py
    def promote_model(self, source_best_run, target_best_run, target_best_run_id, source_task_type, target_task_type, source_model, target_model):
        if (self.debug_always_promote_model==True): # Guard
            print("OBS! 'debug_always_promote_model=TRUE' - will not perform scoring-comparison, nor look into scoring-WEIGHTs in `settings/project_specific/model/model_settings.json")
            return True
        #task_type = self.model_settings.get('task_type','regression')

        print("New trained model & cached RUN, has TASK_TYPE: {} and Best_Run_id: {}".format(source_task_type,source_best_run.id))
        print("Target model & RUN, in Azure ML Studio workspace to compare with, has TASK_TYPE: {} and Best_Run_id:{} ".format(target_task_type,target_best_run.id))

        if(target_best_run_id is None): # 1st run, 1st model...just promote
            print("This is the first model. No target to compare with, hence we will PROMOTE")
            return True

        if (source_task_type != target_task_type): 
            print("Error: Cannot compare models of different machine learning task_type: {} != {} , or target_task_type is none (promote_new_model is returned as True)".format(source_task_type,target_task_type))
            print(" - Example: Cannot compare REGRESSION with CLASSIFICATION...")
            return True
        task_type = source_task_type

        reg_map, cl_map = self.get_metric_mappings()
        promote_new_model = False

        try: 
            print("")
            print("Q: Do we have SCORING DRIFT / CONCEPT DRIFT? - Is a model trained on NEW data better? = the one in production degraded?") # not fit for the data it scores - real world changed, other CONCEPT)"
            print("")

            if(task_type == "classification"):
                print("New trained model: ")
                source_metrics = self.classification_print_metrics(source_best_run,source_model)
                print("")
                print("Target model, to compare with; ")
                target_metrics = self.classification_print_metrics(target_best_run,target_model)
                print("")

                selected_metric_array = self.model_settings['classification_compare_metrics']

                lower_is_better = ["Log_loss_weight"]
                promote_new_model = self.compare_metrics(cl_map, source_metrics, target_metrics,selected_metric_array,lower_is_better)

            elif (task_type == "regression" or task_type == "forecasting"):
                print("New trained model: ")
                source_metrics = self.regression_print_metrics(source_best_run,source_model)
                print("")
                print("Target model, to compare with; ")
                target_metrics = self.regression_print_metrics(target_best_run,target_model)
                print("")

                selected_metric_array = self.model_settings['regression_compare_metrics']
                lower_is_better = ["RMSE_promote_weight", "MAPE_promote_weight","MAE_promote_weight"] # Else, HIGHER is better ["R2_promote_weight", "Spearman_promote_weight"]
                promote_new_model = self.compare_metrics(reg_map, source_metrics, target_metrics,selected_metric_array,lower_is_better)
                
            elif (task_type in ['image-classification', 'image-multi-labeling', 'image-object-detection', 'image-instance-segmentation']): 
                pass
            elif (task_type == 'text-classification-multilabel'): 
                pass
        except Exception as e3:
            promote_new_model = True
            print("Error: Cannot compare models (promote_new_model is currently=True)")
            print("Inner Exception: ", e3)
        finally: 
            return promote_new_model
            
    def compare_metrics(self, metric_map, source_metrics, target_metrics, selected_metric_array,lower_is_better):
        promote_new_model = False

        if(selected_metric_array is not None and len(selected_metric_array) > 0):
            print("Selected metrics, and weights, to be used when comparing for promotion/scoring drift")
            latest_metric = ""
            
            for m in selected_metric_array:
                latest_metric = m
                m_map = metric_map[m]
                current_prod = float(target_metrics[m_map])
                newly_trained = float(source_metrics[m_map])

                #if(newly_trained == -1.0 or current_prod == -1.0): # Old model was probably another task_type (cannot compare REGRESSION with CLASSIFICATION -> Just promote..)
                #    print("!Current best model (or newly trained) is of different Machine learning task_types (cannot compare REGRESSION with CLASSIFICATION) promote_new_model is returned as True)")
                #    promote_new_model = True
                #    break

                promote_weight = float(self.model_settings.get(m,0.0))
                newly_trained_weighted = float(newly_trained - (promote_weight)) # 0.2 meaning, new trained model must be 0.2 better...to "win". AUC=0.8  0.8 - (-0.1) = 0.9

                print("Metric weight: {} is {:5.4f}".format(m,promote_weight))
                print("Metric VALUE (incl. weight) {:5.4f} (without weight:  {:5.4f})".format(newly_trained_weighted,newly_trained))

                if(m in lower_is_better):
                    if (newly_trained_weighted < current_prod):
                        promote_new_model = True
                    else:
                        promote_new_model = False
                        print (" - WORSE: NEW trained model {:.12f} is WORSE than CURRENT model: {:.12f} for metric {}".format(newly_trained_weighted,current_prod,m_map))
                        break # break loop if ANY metric is worse
                else:
                    if (newly_trained_weighted > current_prod):
                        promote_new_model = True
                    else:
                        promote_new_model = False
                        print (" - WORSE: NEW trained model {:.16f} is WORSE than CURRENT model: {:.16f} for metric {}".format(newly_trained_weighted,current_prod,m_map))
                        break # break loop if ANY metric is worse
                print("")

            if(promote_new_model == False):
                print("")
                print("Promote model = False")
                print(" - Not promote, due to metric {}. You can adjust the WEIGHT {} in ESML settings".format(metric_map[latest_metric], latest_metric))
            else:
                print("")
                print("Promote model = True")
        return promote_new_model

    def get_metric_mappings(self):
        metric_map_regression = {
            "RMSE_promote_weight": "normalized_root_mean_squared_error",
            "R2_promote_weight": "r2_score",
            "MAPE_promote_weight": "mean_absolute_percentage_error",
            "MAE_promote_weight": "normalized_mean_absolute_error",
            "Spearman_promote_weight": "spearman_correlation"
        }

        metric_map_classification = {
            "AUC_promote_weight": "AUC_weighted",
            "Accuracy_promote_weight": "accuracy",
            "Precision_promote_weight": "precision_score_weighted",
            "Recall_promote_weight": "recall_score_weighted",
            "F1_promote_weight": "f1_score_weighted",
            "Log_loss_weight":"log_loss",
            "Matthews_promote_weight": "matthews_correlation"
        }
        return metric_map_regression, metric_map_classification

    # https://docs.microsoft.com/en-us/python/api/azureml-core/azureml.core.model.model?view=azure-ml-py
    #def register_model_in_other_ws(self,target_ws, newtrained_modelname,newtrained_run_id,description_in=None,pkl_name_in=None):
    def register_model_in_correct_ws(self,target_dev_test_prod=None,new_model=None, description_in=None,pkl_name_in=None):
        pkl_name = "outputs" # "model.pkl"
        current_env = self.project.dev_test_prod
        current_ws_name = self.project.ws.name

        if (pkl_name_in is not None):
            pkl_name = pkl_name_in

        # GET AML MODEL
        m = None
        temp_dir = tempfile.gettempdir()
        if(new_model is None):
            model_ph = self.project.get_best_model_via_experiment_name(self.project.ws)
            if(model_ph is None):
                print("Could not fetch BEST MODEL from Azure ML Studo - remotely.This might be the first time training model. \n - Now trying with local cache model.")
                model_ph =  self.project.BestModel
        else:
            model_ph = new_model

        # GET PICKLE MODEL
        full_local_path = os.path.join(temp_dir, "esml",self.project.project_folder_name,self.project.ModelAlias)
        full_local_path = os.path.join(full_local_path, pkl_name)
        m = model_ph.download(target_dir=full_local_path, exist_ok=True)
       
        model_name = model_ph.tags["model_name"]
        run_id = model_ph.tags["run_id"]

        tags = model_ph.tags
        tags["trained_in_environment"] = current_env
        tags["trained_in_workspace"] = current_ws_name
        print("run_id {}".format(run_id))
        tags["run_id"] = run_id

        if("test_set_ROC_AUC" in model_ph.tags):
            tags["test_set_Accuracy"] = model_ph.tags["test_set_Accuracy"]
            tags["test_set_ROC_AUC"] = model_ph.tags["test_set_ROC_AUC"]
            tags["test_set_Precision"] = model_ph.tags["test_set_Precision"]
            tags["test_set_Recall"] = model_ph.tags["test_set_Recall"]
            tags["test_set_F1_Score"] = model_ph.tags["test_set_F1_Score"]
            tags["test_set_Matthews_Correlation"] = model_ph.tags["test_set_Matthews_Correlation"]
            tags["test_set_CM"] = model_ph.tags["test_set_CM"]
        if("test_set_RMSE" in model_ph.tags):
            tags["test_set_RMSE"] = model_ph.tags["test_set_RMSE"]
            tags["test_set_R2"] = model_ph.tags["test_set_R2"]
            tags["test_set_MAPE"] = model_ph.tags["test_set_MAPE"]
            tags["test_set_Spearman_Correlation"] = model_ph.tags["test_set_Spearman_Correlation"]

        #tags = {"run_id": run_id, "model_name": model_name, "trained_in_environment": self.project.dev_test_prod, 
        #"trained_in_workspace": self.project.ws.name, "experiment_name": self.project.model_folder_name}

        # CONNECT to target Workspace
        target_ws = self.connect_to_target_workspace(target_dev_test_prod)
        print("Register in workspace:", target_ws.name)
        #print("temp-files: ", full_local_path)
        #model_name = self.project.experiment_name
        #print("ExperimentName as Modelname {}".format(model_name))

        # REGISTER aml MODEL in new workspace
        model = Model.register(model_path=full_local_path, # Local file to upload and register as a model.
                        model_name=model_name,
                        model_framework=Model.Framework.SCIKITLEARN,  # Framework used to create the model.
                        model_framework_version=sklearn.__version__,  # Version of scikit-learn used to create the model.
                        #sample_input_dataset=self.project.GoldTest,  #sample_input_data=sample_input_dataset_id
                        #sample_output_dataset=self.project.GoldTest,
                        resource_configuration=ResourceConfiguration(cpu=1, memory_in_gb=0.5),
                        tags=tags,
                        description=description_in,
                        workspace=target_ws)
        #input_dataset = Dataset.Tabular.from_delimited_files(path=[(datastore, 'sklearn_regression/features.csv')])
        #output_dataset = Dataset.Tabular.from_delimited_files(path=[(datastore, 'sklearn_regression/labels.csv')])
        # FINALLY....
        self.project.dev_test_prod = current_env # flip back to ORIGINAL environment

        return model, model_ph
        
    #def register_active_model_in_ws(self, target_workspace, target_env):
    #    self.LoadConfiguration(target_env,self.project.override_enterprise_settings_with_model_specific)
    #    return self._register_model(target_env,target_workspace.name, target_workspace,self.model_name_automl, target_env, self.project.GoldTrain)

    def register_active_model(self,target_env, source_model_4_tags=None):

        p = self.project
        if(p.dev_test_prod != target_env):
            raise UserErrorException("User the PRIVATE PREVIEW function 'register_model_in_correct_ws' to register on OTHER workspace. \n - This method 'register_active_model' can only register a model in same azure ml workspace (test->test), then you need to retrain in new workspace if going from dev->test")

        self.LoadConfiguration(target_env,p.override_enterprise_settings_with_model_specific)
        
        source_env = p.dev_test_prod
        source_ws_name = p.ws.name #target_workspace.name
        if (source_env == "prod"):
            target_workspace = p.ws # Last stop. Prod->Prod
        else:
            target_workspace = p.get_other_workspace(target_env)

        return self._register_model(source_env,source_ws_name, target_workspace,self.model_name_automl, target_env, p.override_enterprise_settings_with_model_specific,p.GoldTrain,source_model_4_tags)

    def _get_active_model_run_and_experiment(self, target_workspace, target_env, override_enterprise_settings_with_model_specific, pipeline_run=False):
        self.LoadConfiguration(target_env, override_enterprise_settings_with_model_specific)
        
        run_id = self.active_model_config["run_id"]
        if (not run_id):
            print("Run ID is not a Guid, or not set -> No new model to register, as TARGET model perform better")
            return None
        experiment_name = self.active_model_config["experiment_name"]
        experiment = Experiment(workspace=target_workspace, name=experiment_name)

        remote_run = None
        if(pipeline_run == True):
            remote_run = PipelineRun(experiment=experiment, run_id=run_id)
        remote_run = AutoMLRun(experiment=experiment, run_id=run_id)
        return remote_run, experiment

    def _register_model(self,source_env,source_ws_name, target_workspace,model_name, target_env, override_enterprise_settings_with_model_specific, train_dataset=None,model_ph=None):
        remote_run, experiment = self._get_active_model_run_and_experiment(target_workspace,target_env, override_enterprise_settings_with_model_specific)
        #  # 2022-05-02: best_run.run_id -> AttributeError: 'Run' object has no attribute 'run_id'

        run_id = remote_run.id # TODO does .run_id exists in PipelineRun? (.id) It does in a ScriptRun.
        tags = {"run_id": run_id, "model_name": model_name, "trained_in_environment": source_env, 
        "trained_in_workspace": source_ws_name, "experiment_name": experiment.name}

        if(model_ph is not None):
            if("test_set_ROC_AUC" in model_ph.tags):
                tags["test_set_Accuracy"] = model_ph.tags["test_set_Accuracy"]
                tags["test_set_ROC_AUC"] = model_ph.tags["test_set_ROC_AUC"]
                tags["test_set_Precision"] = model_ph.tags["test_set_Precision"]
                tags["test_set_Recall"] = model_ph.tags["test_set_Recall"]
                tags["test_set_F1_Score"] = model_ph.tags["test_set_F1_Score"]
                tags["test_set_Matthews_Correlation"] = model_ph.tags["test_set_Matthews_Correlation"]
                tags["test_set_CM"] = model_ph.tags["test_set_CM"]
            if("test_set_RMSE" in model_ph.tags):
                tags["test_set_RMSE"] = model_ph.tags["test_set_RMSE"]
                tags["test_set_R2"] = model_ph.tags["test_set_R2"]
                tags["test_set_MAPE"] = model_ph.tags["test_set_MAPE"]
                tags["test_set_Spearman_Correlation"] = model_ph.tags["test_set_Spearman_Correlation"]

        #properties = {"run_id": run_id, "model_name": model_name, "trained_in_environment": source_env, 
        #"trained_in_workspace": source_ws_name, "experiment_name": experiment.name}
        
        # TypeError: register_model() got an unexpected keyword argument 'datasets'
        #model = remote_run.register_model(model_name=model_name, tags=tags, description="",datasets =[('training data',train_dataset)]) #, properties=properties) # register_model() got an unexpected keyword argument 'properties'
        model = remote_run.register_model(model_name=model_name, tags=tags, description="")
        print("model.version", model.version)

        self.write_run_config(experiment.name, model.name,remote_run.run_id, target_env, model.version)

        # Also TAG Experiemnt with model and version
        tags = {'model_name':model_name, 'best_model_version': str(model.version)}
        experiment.set_tags(tags)

        print("Model name {} is registered.".format(model.name))
        return model
    
    def write_run_config(self,experiment_name, model_name, new_run_id, dev_test_prod, registered_model_version=-1):
        self.active_model_config = {
            "experiment_name": experiment_name,
            "model_name_automl": model_name,
            "run_id": new_run_id,
            "dev_test_prod": dev_test_prod,
            "registered_model_version": registered_model_version
            }

        old_loc = os.getcwd()
        try:
            if(dev_test_prod != "dev" and dev_test_prod != "test" and dev_test_prod != "prod"):
                raise ValueError("dev_test_prod needs to be either: 'dev','test', or 'prod' - but it is={}".format(dev_test_prod))

            os.chdir(os.path.dirname(__file__))

            start_path = "project_specific/model/dev_test_prod"
            user_settings = "../../"

            if(dev_test_prod == "dev"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_dev.json".format(user_settings,start_path), "w") as f:
                    json.dump(self.active_model_config, f)
            if(dev_test_prod == "test"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_test.json".format(user_settings,start_path), "w") as f:
                    json.dump(self.active_model_config, f)
            if(dev_test_prod == "prod"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_prod.json".format(user_settings,start_path), "w") as f:
                    json.dump(self.active_model_config, f)
            
        except Exception as e:
            raise ValueError("AutoMLFactory.write_run_config - could not write .json config file: automl_active_model_envX.json") from e
        finally: 
            os.chdir(old_loc) # Change back working location...

    def regression_print_metrics(self,best_run, model):
        #metrics = best_run.get_metrics()
        metrics = self.get_metrics_regression(best_run,model)

        rmse = metrics.get('normalized_root_mean_squared_error',-999.0)
        r2 = metrics.get('r2_score', -999.0)
        spearman = metrics.get('spearman_correlation', -999.0)
        mape = metrics.get('mean_absolute_percentage_error',-999.0)
        _mae = metrics.get('normalized_mean_absolute_error', -999.0)

        all_metrics = {}
        all_metrics["normalized_root_mean_squared_error"] = rmse
        all_metrics["r2_score"] = r2
        all_metrics["mean_absolute_percentage_error"] = mape
        all_metrics["normalized_mean_absolute_error"] = _mae
        all_metrics["spearman_correlation"] = spearman

        print("RMSE (normalized_root_mean_squared_error): " + str(rmse))
        print("MAPE (Mean average Percentage Error): " + str(mape))
        print("MAE (normalized_mean_absolute_error): " + str(_mae))
        print("R2 (r2_score): " + str(r2))
        print("Spearman (spearman_correlation): " + str(spearman))
        
        return all_metrics

    def classification_print_metrics(self,best_run,model):
        metrics = self.get_metrics_classification(best_run,model)

        auc = metrics.get('AUC_weighted', -1.0)
        accuracy = metrics.get('accuracy', -1.0)
        precision = metrics.get('precision_score_weighted', -1.0)
        precision_avg = metrics.get('average_precision_score_weighted', -1.0) # No Testset scoring
        recall = metrics.get('recall_score_weighted', -1.0)
        f1_score = metrics.get('f1_score_weighted', -1.0)
        log_loss = metrics.get('log_loss', -1.0) # No Testset scoring
        mathews = metrics.get('matthews_correlation', -1.0)

        all_metrics = {}
        all_metrics["AUC_weighted"] = auc
        all_metrics["accuracy"] = accuracy
        all_metrics["precision_score_weighted"] = precision
        all_metrics["average_precision_score_weighted"] = precision_avg
        all_metrics["recall_score_weighted"] = recall
        all_metrics["f1_score_weighted"] = f1_score
        all_metrics["log_loss"] = log_loss
        all_metrics["matthews_correlation"] = mathews

        print("AUC (AUC_weighted): " + str(auc))
        print("Accuracy: " + str(accuracy))
        print("Precision (precision_score_weighted): " + str(precision))
        print("Recall (recall): " + str(recall))
        print("F1 Score (1.0 is good): " + str(f1_score))
        print("Logg loss (0.0 is good): " + str(log_loss))
        print("matthews_correlation (1.0 is good): " + str(mathews))

        return all_metrics

    def get_metrics_classification(self,best_run, model):
        metrics = {}
        if("test_set_Accuracy" in model.tags): # First Try: TEST SET Scoring from TAGS
            print("INFO: Using ESML TEST_SET SCORING, since tagged on MODEL - using this to compare SCORING")
            
            metrics["accuracy"] = model.tags["test_set_Accuracy"]
            metrics["AUC_weighted"] = model.tags["test_set_ROC_AUC"]
            metrics["precision_score_weighted"] = model.tags["test_set_Precision"]
            metrics["recall_score_weighted"] = model.tags["test_set_Recall"]
            metrics["f1_score_weighted"] = model.tags["test_set_F1_Score"]
            metrics["matthews_correlation"] = model.tags["test_set_Matthews_Correlation"]
            # Missing: log_loss, average_precision_score_weighted (same loss for both..)
            metrics["log_loss"] = -1
            metrics["average_precision_score_weighted"] = -1

        elif (best_run is not None):
            print("Warning: Falling back o use AutoML validation scoring when comparing. Run 'ESMLTestScoringFactory(p).get_test_scoring_7_classification()' use TEST_SET SCORING when comparing")
            metrics = best_run.get_metrics() # Backup, use Validation scoring, e.g. no TestSet scoring is calculated&tagged on model
        return metrics

    def get_metrics_regression(self,best_run, model):
        metrics = {}
        if("test_set_Accuracy" in model.tags): # First Try: TEST SET Scoring from TAGS 
            print("INFO: Using ESML TEST_SET SCORING, since tagged on MODEL - using this to compare SCORING")
            
            metrics["normalized_root_mean_squared_error"] = model.tags["test_set_RMSE"]
            metrics["r2_score"] = model.tags["test_set_R2"]
            metrics["mean_absolute_percentage_error"] = model.tags["test_set_MAPE"]
            metrics["spearman_correlation"] = model.tags["test_set_Spearman_Correlation"]
            
            #Missing: normalized_mean_absolute_error
            metrics["normalized_mean_absolute_error"] = -1

        elif (best_run is not None):
            print("Warning: Falling back o use AutoML validation scoring when comparing. Run 'ESMLTestScoringFactory(p).get_test_scoring_4_regression()' to use TEST_SET SCORING when comparing")
            metrics = best_run.get_metrics() # Backup, use Validation scoring, e.g. no TestSet scoring is calculated&tagged on model
        return metrics

# Task_type - https://docs.microsoft.com/en-us/python/api/azureml-automl-core/azureml.automl.core.shared.constants.tasks?view=azure-ml-py
# AutoML Supported value(s): 'accuracy, precision_score_weighted, norm_macro_recall, AUC_weighted, average_precision_score_weighted'. 
class azure_metric_classification():
    AUC = "AUC_weighted"
    Accuracy = "accuracy"
    Precision = "precision_score_weighted"
    Precision_avg = "average_precision_score_weighted"
    Recall = "norm_macro_recall"
    #F1_score = "f1_score_weighted"
    #Log_loss = "log_loss"

# AutoML Supported value(s):  'normalized_mean_absolute_error, normalized_root_mean_squared_error, spearman_correlation, r2_score'
class azure_metric_regression():
    MAE = "normalized_mean_absolute_error"
    RMSE = "normalized_root_mean_squared_error"
    R2 = "r2_score"
    Spearman = "spearman_correlation"
    #MAPE = "mean_absolute_percentage_error"  # Not supported in AutoML training as
    #R2oob = "explained_variance"
    #Recall = "recall"
