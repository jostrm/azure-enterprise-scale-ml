import os
import json
from azureml.core import Experiment
from azureml.core import Model
from azureml.train.automl.run import AutoMLRun
from azureml.pipeline.core import PipelineRun
from azureml.telemetry import UserErrorException

#import sys
#sys.path.append(os.path.abspath(".."))  # NOQA: E402
from ..interfaces.iESMLModelCompare import IESMLModelCompare
from ..interfaces.iESMLController import IESMLController

class ESMLModelCompare(IESMLModelCompare):

    model_settings = None
    metrics_output_name = 'metrics_output' # PipelineRun
    best_model_output_name = 'best_model_output'
    
    def __init__(self, setting_path = ""):
        super().__init__(setting_path)
        self.load_config_modelsettings()

    def load_config_modelsettings(self):
        old_loc = os.getcwd()
        
        try:
            os.chdir(os.path.dirname(__file__))
            automl_active_path = "project_specific/model/dev_test_prod"
          
            # Model specific settings - for all environments
            with open("{}../settings/project_specific/model/model_settings.json".format(self._setting_path,automl_active_path)) as f:
                self.model_settings = json.load(f)

        except Exception as e:
            raise ValueError("ESMLModelCompare - load_config_modelsettings - could not open .json config files: model_settings.json") from e
        finally: 
            os.chdir(old_loc) # Change back working location...

    
    def get_task_type(self, target_run):
        my_dictionary = target_run.get_properties()
        j_str = my_dictionary['AMLSettingsJsonString']
        j_dic = json.loads(j_str)
        task_type = j_dic['task_type']
        return task_type
    
    '''
     if (target_environment == "dev" & p.dev_test_prod = "dev") -> compare againt  stage "dev" -> INNER LOOP MLOps
     if (target_environment== "test" & p.dev_test_prod = "dev") -> compare againt next stage "test" -> OUTER LOOP MLOps
     if (target_environment == "prod" & & p.dev_test_prod = "test") -> compare "test" againt next stage "prod"  -> OUTER LOOP MLOps
     if (target_environment == "prod" & & p.dev_test_prod = "dev") -> Exception! Should always use corret staging cycle. Not "jump over"
    '''
    ###
    #returns: promote_new_model,source_model_name,new_run_id,target_model_name, target_best_run_id,target_workspace,source_model
    ##
    def compare_scoring_current_vs_new_model(self, current_ws,current_environment, target_environment,target_workspace, experiment_name, new_model=None, new_run_id=None, model_name=None):
        self.load_config_modelsettings()
        p = self._esml_controller
        
        debug_print=True
        source_workspace = current_ws
        experiment_name = experiment_name #self.project.model_folder_name such as "11_diabetes_model"
        promote_new_model = False
 
        # SOURCE (latest registered) vs TARGET (latest registered)
        task_type = p.ESMLTestScoringFactory.ml_type
        source_hydrate_dev_run = True

        # SOURCE
        source_model_name = ""
        source_best_run = None
        source_run_id = None
        source_model = None
       
        # TARGET
        target_model_name = ""
        target_run_id = None
        target_best_run = None
        target_model = None
        

        # INNER LOOP: DEV-DEV or OUTER LOOP: dev->test
        if(current_environment == "dev"):
            # 1a) NEW_MODEL: Get NEW model or LEADING model in DEV
            if (new_model is None):# DEV-TEST
                if(new_run_id is not None):
                    print("ESML INFO:ModelCompare: new_model is None, but new_run_id is set - trying to fetch model via hydrating RUN and model_name property")
                    print("SOURCE: Trying to hydrate RUN, since DEV environment.")
                    try:
                        source_run_id = IESMLController.get_safe_automl_parent_run_id(new_run_id)
                        run,best_run,fitted_model = IESMLController.init_run(source_workspace,experiment_name, source_run_id)
                        print("Run, best_run, fitted_model is now hydrated:")
                        if (best_run is not None):
                            print("ESML: best_run.id {}".format(best_run.id))
                        if(run is not None):
                            print("ESML: run.id {}".format(run.id))
                        
                        source_best_run = run
                         # Not: not bset_run , we need parent run, that has AMLSettings in properties
                        #source_model_name_from_prop = best_run.properties['model_name'] # ESML Note:001: Hydration did not work. We can manage without it. Errormessage:")
                        #print("ESML Sanitycheck: Model from RUN.properties {}".format(source_model_name_from_prop))

                        if (model_name is not None):
                            test_model = Model(source_workspace, name=model_name) # Will have LATEST verion model. Maybe Not desired behaviour...
                            print("ESML test_model NAME: {}".format(test_model.name))
                            print("ESML test_model NAME: {}".format(test_model.version))

                    except Exception as e:
                        print("ESML Note:001: Hydration did not work. We can manage without it. Errormessage:")
                        print(e)

                #source_model, source_run_id_tag 
                source_model,source_run_id,source_best_run_again,source_model_name = IESMLController.get_best_or_challenger_model_with_run_in_dev(experiment_name, source_workspace, get_latest_challenger=True)
                if(source_best_run is None):
                    source_best_run = source_best_run_again

                if (source_model is None):
                    print("Could not find a CHALLENGER model in SOURCE.No model with ESML status_code {}".format("esml_newly_trained"))
                    print("- And no arguments passed: new_model, new run_id). Returning True as promote result")
                    print("- ModelCompare:201:Source: Could not find EXISTING MODEL in SOURCE. in environment: {} and workspace {}, nothing to compare against -> Go ahead and register & deploy new model".format(current_environment,source_workspace.name))
                    promote_new_model = False
                else:
                    if(debug_print):
                        print("- source_model.name:{} and version:{}".format(source_model.name,source_model.version))
                        print("- source_model.tags[status_code] {} ".format(source_model.tags.get("status_code")))

                    if (source_run_id != source_model.tags["run_id"]):
                        print("ESML Note:901:Sanitycheck failed: source_run_id_tag{} != source_model.tags[run_id] {} and source_best_run.id: {} ".format(source_run_id,source_model.tags["run_id"],source_best_run.id))

                    if(debug_print):
                        print("ESML INFO:ModelCompare:201:Source challenging model, name {}".format(source_model_name))
            else:
                source_model = new_model # DEV-DEV
                if(debug_print):
                    print("ESML INFO:ModelCompare:202:Source challenging model, name {}".format(source_model.name))
            
            if (source_model is not None):
                #OPTIONAL: Init/Hydrate run for model:
                if(debug_print):
                    print ("Run ID TAG: source_model.tags[run_id] {}".format(source_model.tags.get("run_id")))
                if(source_hydrate_dev_run and source_best_run is None):
                    print("SOURCE: Trying to hydrate RUN, since DEV environment.")
                    try:
                        if (new_run_id is not None):
                            source_run_id = IESMLController.get_safe_automl_parent_run_id(new_run_id)
                            run,best_run,fitted_model = IESMLController.init_run(source_workspace,experiment_name, source_run_id) # Parameter
                        elif(source_run_id is not None):
                            source_run_id = IESMLController.get_safe_automl_parent_run_id(source_run_id)
                            run,best_run,fitted_model = IESMLController.init_run(source_workspace,experiment_name, source_run_id) # Afte rLookup of model
                        else:
                            source_run_id = IESMLController.get_safe_automl_parent_run_id(source_model.tags.get("run_id"))
                            run,best_run,fitted_model = IESMLController.init_run(source_workspace,experiment_name, source_run_id) # Tag
                        source_best_run = run # Not: not bset_run , we need parent run, that has AMLSettings in properties
                    except Exception as e:
                        print("ESML Note:002: Hydration did not work. We can manage without it. Errormessage:")
                        print(e)

                # 1b)Guard: that TEST_SET SCORING is calculated
                if(p.check_if_test_scoring_exists_as_tags(source_model) == False):
                    raise UserErrorException("ESML Error You need to calculate testset scoring before comparing. ")
        
        else: # OUTER LOOP: TEST->PROD (no RUN associated since source is TEST)
            # 1a) Source LEADING model
            source_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(source_workspace,experiment_name)
            if (source_model is None):
                 print("Could not find a LEADING model in SOURCE in environment {} and source_workspace {}".format(current_environment,source_workspace.name))
                 promote_new_model = False
            else:
                source_run_id = run_id_tag
                source_model_name = model_name_tag
                print("ESML INFO:ModelCompare:203:Source leading model, name {}".format(source_model_name))

                if(p.check_if_test_scoring_exists_as_tags(source_model) == False):
                    raise UserErrorException("ESML Error You need to calculate testset scoring before comparing. No TAG with scoring.")
                    # Note: TEST or PROD model, SHOULD definetely have SCORING calculated...since already compared & promoted.

        ########### GUARD - if no SOURCE model to promote, return FALSE
        if (source_model is None):
            return False,source_model_name,source_run_id,source_best_run,source_model,target_model
        ############# TARGET: either DEV, TEST, PROD ##############

        # INNER LOOP Target: is DEV - a run may be associated
        if(target_environment == "dev"): #OPTIONAL: Init/Hydrate run for model:
            target_model,target_run_id,target_best_run,target_model_name = IESMLController.get_best_or_challenger_model_with_run_in_dev(experiment_name, target_workspace,get_latest_challenger=False)
            if (target_run_id != target_model.tags["run_id"]):
                print("ESML Note:902:Sanitycheck failed: target_run_id {} != target_model.tags[run_id] {}".format(target_run_id,target_model.tags["run_id"]))

            print("ESML INFO:ModelCompare:202:Target challenging model, name {}".format(target_model_name))
            if (target_model is None):
                promote_new_model = True
                print("ESML INFO:ModelCompare:203:Target: Could not find EXISTING MODEL in TARGET. This is the first model to be trained in environment: {} and workspace {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment,source_workspace.name))
            elif(source_hydrate_dev_run and target_best_run is None):
                print("ESML INFO:102:TARGET: Trying to hydrate RUN, since DEV environment is TARGET. INNER LOOP")
                try:
                    target_run_id = IESMLController.get_safe_automl_parent_run_id(target_run_id)
                    run,best_run,fitted_model = p.init_run(target_workspace,experiment_name, target_run_id) # target_run_id from "Lookup of model"
                    target_best_run = run # Note: run, not best_run
                except Exception as e:
                    print("...Hydration did not work. No big deal. We can manage without")
                    print(e)
        else: #OUTER LOOP Target: (no RUN associated since source is TEST or PROD)
            leading_model,leading_run_id_tag, leading_model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(target_workspace,experiment_name)
            target_model = leading_model
            target_run_id = IESMLController.get_safe_automl_parent_run_id(leading_run_id_tag)
            target_model_name = leading_model_name_tag

            if (target_model is None):
                promote_new_model = True
                print("ESML INFO:ModelCompare:204:Target: Could not find EXISTING MODEL in TARGET. This is the first model to be trained in environment: {} and workspace {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment,target_workspace.name))
            
            print ("ESML INFO:RunId TAG: Target leading_model_name_tag {}".format(leading_model_name_tag))
            print ("ESML INFO:RunId TAG: Target leading_model.name {}".format(target_model.name))
           
         # IF we have a target to compare with
        if (promote_new_model == False):
            promote_new_model = self.promote_model(source_best_run,target_best_run,task_type,source_model,target_model)
        # END, IF we have a target to compare with
        
        #return promote_new_model,model_name_tag,new_run_id,target_model_name, target_workspace,source_model
        return promote_new_model,source_model_name,source_run_id,source_best_run,source_model,target_model



    # https://docs.microsoft.com/en-us/python/api/azureml-automl-core/azureml.automl.core.shared.constants.tasks?view=azure-ml-py
    def promote_model(self, source_best_run,target_best_run, task_type, source_model, target_model):
        if (self._debug_always_promote_model==True): # Guard
            print("OBS! 'debug_always_promote_model=TRUE' - will not perform scoring-comparison, nor look into scoring-WEIGHTs in `settings/project_specific/model/model_settings.json")
            return True

        if(source_best_run is not None):
            print("New trained model source run_id: {}".format(source_best_run.id))

        reg_map, cl_map = self.get_metric_mappings()
        promote_new_model = False

        try: 
            print("")
            print("Q: Do we have SCORING DRIFT / CONCEPT DRIFT? - Is a model trained on NEW data better? = the one in production degraded?") # not fit for the data it scores - real world changed, other CONCEPT)"
            print("")

            if(task_type == "classification"):
                print("New trained model: model id {}".format(source_model.id))
                source_metrics = self.classification_print_metrics(source_best_run,source_model)
                print("")
                print("Target model, to compare with, model id {}".format(target_model.id))
                target_metrics = self.classification_print_metrics(target_best_run,target_model)
                print("")

                selected_metric_array = self.model_settings['classification_compare_metrics']

                lower_is_better = ["Log_loss_weight"]
                promote_new_model = self.compare_metrics(cl_map, source_metrics, target_metrics,selected_metric_array,lower_is_better)

            elif (task_type == "regression" or task_type == "forecasting"):
                print("New trained model: model id {}".format(source_model.id))
                source_metrics = self.regression_print_metrics(source_best_run,source_model)
                print("")
                print("Target model, to compare with. model id {}".format(target_model.id))
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

        ############################## OLD ##############
    def compare_scoring_current_vs_new_model_old(self, new_run_id, current_ws,current_environment, target_environment,target_workspace, experiment_name):
        self.load_config_modelsettings()
        p = self._esml_controller
        
        source_workspace = current_ws
        current_env = current_environment
        experiment_name = experiment_name #self.project.model_folder_name
        promote_new_model = False

        # SOURCE (latest registered) vs TARGET (latest registered)
        source_model_name = ""
        source_metrics = None
        source_task_type = p.ESMLTestScoringFactory.ml_type
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
        else: # Probably source = DEV andtarget = TEST
            source_model_name = None
            source_best_run_id = None

            #try: # GET source from saved new RUN_ID
            if (target_environment != current_env): # If REGISTER model in other WORKSPACE, no Run or Experiment exists in TARGET
                source_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(source_workspace,experiment_name) # 2022-08-08: != IESMLController.esml_status_new
                
                try:
                    source_model_name = source_model.name # 2022-08-08, test if this is possible...model may not have a Run associated with it. Hence use TAGS instead
                    source_best_run_id2 = source_model.run.id # 2022-08-08
                    print ("Model source_model.name {}".format(source_model_name))
                    print ("Run ID 1: source_model.run.id: {}".format(source_best_run_id2)) # eef9793a-b684-4f24-888e-f795280b6e1f_0
                    print ("Run ID 2: get_best_model_and_run_id_tag: {} = ACTIVE".format(run_id_tag)) # eef9793a-b684-4f24-888e-f795280b6e1f
                    print ("-Run ID 3: source_model.tags[run_id] {}".format(source_model.tags["run_id"])) # eef9793a-b684-4f24-888e-f795280b6e1f
                    print("Run ID 4:IN parameter: new_run_id {}".format(new_run_id))
                except Exception as e5:
                    print("INFO: Could not get source_model.name or source_model.run.id, when target_environment != current_env {}".format(e5))

                #2022-10-20 source_exp = Experiment(workspace=source_workspace, name=experiment_name) # Fetch the OLD run from SOURCE () TODO: What if TEST->PROD and both are just "registered" from DEV?)
                source_best_run_id = source_model.tags["run_id"] # 2022-10-19 changed run_id to fix correct behaviour
                source_best_run_id = run_id_tag # 2010-19 test 1. WORKS! run_id_tag
                #source_best_run_id = new_run_id # 2010-19 test 2
                try:
                    print("source_best_run_id viasource_model.tags[run_id]  {}".format(source_best_run_id))
                    #2022-10-20  source_run = AutoMLRun(experiment=source_exp, run_id=source_best_run_id)
                    
                    #2022-10-20 source_best_run, source_fitted_model = source_run.get_output()
                    #2022-10-20 source_task_type = self.get_task_type(source_run)
                    
                    #2022-10-20 source_model_name_from_properties = source_best_run.properties['model_name'] #2022-10-19 wrong modelname 
                    #2022-10-20 if(source_model_name_from_properties != source_model_name):  # 2022-08-08 Added this check
                        #2022-10-20 print("WARNING! source_best_run.properties['model_name'] {} != source_model.name {}".format(source_model_name_from_properties,source_model.name))
                        #2022-10-20 print("- INFO: Chosing source_model.name from IESMLController.get_best_model")
                        
                    print("Model name for initating Model() is source_model_name2: {}".format(source_model_name)) # 2022-10-19 WORKS!source_model_name
                    source_model = Model(source_workspace, name=source_model_name) # 2022-08-08 source_model  is already fetched...2022-10-19 crashed here. changed run_id to fix correct behaviour
                except Exception as e2:
                    print("INFO: 100: source!=target: Could not initiate source_run or Model with source_best_run_id = {} and Model name {}".format(source_best_run_id,source_model_name))
                    print(e2)
                    # source_task_type = self.get_task_type(source_model.run) # Can throw an errror
                    source_model_name = source_model.name
                    print("101: 'model.run.id = '{}".format(source_model.run.id))

            else: # PROBABLY DEV to DEV (may be 1st time of model. may be from notebook, may be from pipeline run)
                source_exp = Experiment(workspace=source_workspace, name=experiment_name)
                try: # Try as Run first
                    source_run = AutoMLRun(experiment=source_exp, run_id=new_run_id)  # just retrained model: == IESMLController.esml_status_new

                    source_best_run, source_fitted_model = source_run.get_output()
                    source_model_name = source_best_run.properties['model_name']
                    print("source_best_run.properties['model_name'] is: {}".format(source_model_name))
                    
                    source_task_type = self.get_task_type(source_run)
                except Exception as e2:
                    print("ESML INFO 101: source=target: Could not initiate, source_run, as AutoMLRun, now trying as other Run(), PipelineRun() from model.run with: 'new_run_id' = {}".format(new_run_id))
                    source_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(source_workspace,experiment_name)
                    source_task_type = self.get_task_type(source_model.run)
                    source_model_name = source_model.name

                    print("source_model.name is: {}".format(source_model_name))
                    print("101: 'model.run.id = '{}".format(source_model.run.id))
                    print(e2)
                
                try: # model_name should be something like 'AutoML7e64144860' if AutoMLRun fro notebook, but if AutoMLStep/AutoMLRun then it is a weird model_name='8b7c996f69374470'
                    source_model = Model(source_workspace, name=source_model_name) 
                except: 
                    try:
                        source_model = Model(source_workspace, name=experiment_name) # Try with model_name=exp_name if PipelineRun() 
                    except Exception as e3:
                        promote_new_model = True
                        print("ESML INFO: Could not find EXISTING MODEL in workspace {} and source_model_name {} with same experiment name = No TARGET run. This might be the first model to be trained in target_environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(source_workspace.name,experiment_name,target_environment))
                        print(e3)

        try: # Compare latest SOURCE_MODEL with TARGET_MODEL
            if(target_workspace == source_workspace): # dev->dev, or test->test, or prod->prod
                print("TARGET is in the same Azure ML Studio workspace as SOURCE, comparing with latest registered model...")
            
            #target_model, target_best_run_id = AutoMLFactory(p).get_latest_model(target_workspace)
            #target_model, target_best_run_id = AutoMLFactory(p).get_latest_model_from_experiment_name(target_workspace,experiment_name)
            target_exp, model,target_run, target_best_run,target_model = None,None,None,None,None
            try:
                
                target_model,target_best_run_id, target_model_name = IESMLController.get_best_model_via_modeltags_only_DevTestProd(target_workspace,experiment_name) # != IESMLController.esml_status_new
                if(target_model is None):
                    promote_new_model = True
                    print("ESML INFO 200 - Could not find EXISTING MODEL in TARGET. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
                else:
                    source_exp = Experiment(workspace=source_workspace, name=experiment_name) # Fetch the OLD run from SOURCE () TODO: What if TEST->PROD and both are just "registered" from DEV?)
                    target_best_run_id = target_model.tags["run_id"]

                    try:
                        target_run = AutoMLRun(experiment=source_exp, run_id=target_best_run_id)
                        target_best_run, fitted_model = source_run.get_output()
                        target_best_model_version = target_model.version
                    except Exception as e2:
                        print("ESML INFO 100: Could not initiate, source_run, as AutoMLRun, now trying as other Run() with run_id{}".format(target_best_run_id))
                        print(e2)

                #if (target_environment != current_env): # If REGISTER model in other WORKSPACE, no Run or Experiment exists
                #    target_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(target_workspace,experiment_name) # != IESMLController.esml_status_new
                #    source_exp = Experiment(workspace=source_workspace, name=experiment_name) # Fetch the OLD run from SOURCE () TODO: What if TEST->PROD and both are just "registered" from DEV?)
                #    target_best_run_id = target_model.tags["run_id"]
                #    target_run = AutoMLRun(experiment=source_exp, run_id=target_best_run_id)
                #    target_best_run, fitted_model = source_run.get_output()
                #else:
                #    target_exp, target_model,target_run, target_best_run,fitted_model = IESMLController.get_best_model_run_fitted_model_Dev(target_workspace,experiment_name) # 2022-08-08

            except Exception as e1:
                #print(e1)
                promote_new_model = True
                print("200 - )Could not find EXISTING MODEL with same experiment name = No TARGET run. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
                                
            if(target_model is not None):
                if(target_environment != current_env):
                    target_task_type = source_task_type # Assume same type, if REGISTER model in other WORKSPACE
                else:
                    print("target_best_run_id", target_best_run_id)

                    if (target_best_run_id is not None): 
                        try:
                            target_task_type = self.get_task_type(target_run)
                        except:
                            target_task_type = source_task_type # Assume same type, if REGISTER model in other WORKSPACE
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
        
        return promote_new_model,source_model_name,new_run_id,target_model_name, target_best_run_id,target_workspace,source_model