import os
import pandas as pd
import argparse
from azureml.core import Run
from azureml.data.dataset_factory import FileDatasetFactory
import datetime
from esmlrt.interfaces.iESMLController import IESMLController
from esmlrt.interfaces.iESMLModelCompare import IESMLModelCompare
from esmlrt.interfaces.iESMLTestScoringFactory import IESMLTestScoringFactory
from esmlrt.interfaces.iESMLTrainer import IESMLTrainer

from esmlrt.runtime.ESMLController import ESMLController
from esmlrt.runtime.ESMLModelCompare2 import ESMLModelCompare
from esmlrt.runtime.ESMLTestScoringFactory2 import ESMLTestScoringFactory
from your_code.your_train_code import Trainer
from azureml.core import Dataset

from azureml.core.run import _OfflineRun
from azureml.core import Workspace
from azureml.pipeline.core import PipelineRun
from azureml.core.model import Model
#from azureml.pipeline.steps import AutoMLStep # ModuleNotFoundError: No module named 'azureml.pipeline.steps'
from azureml.train.automl.run import AutoMLRun

def init():
    global prev_model,test_ds, last_gold_training_run,datastore,historic_path,run,run_id,active_folder,date_in,model_version_in,esml_env,esml_model_alias,esml_modelname,aml_model_name,target_column_name,ws,model_path,model_name
    global project_number,ml_type,secret_name_tenant,secret_name_sp_id,secret_name_sp_secret
    global dev_resourcegroup_id,dev_workspace_name,dev_subscription_id,test_resourcegroup_id,test_workspace_name,test_subscription_id,prod_resourcegroup_id,prod_workspace_name,prod_subscription_id

    parser = argparse.ArgumentParser("Split the GOLD and Train the model")
    parser.add_argument('--target_column_name', dest="target_column_name", type=str, required=True)
    parser.add_argument('--par_esml_training_date', dest="par_esml_training_date", required=True)
    parser.add_argument('--par_esml_model_version', dest="par_esml_model_version", required=True)
    parser.add_argument('--esml_train_lake_template', dest="esml_train_lake_template", required=True)
    parser.add_argument('--par_esml_inference_mode', dest='par_esml_inference_mode', type=int, required=True)
    
    parser.add_argument('--par_esml_model_alias', dest='par_esml_model_alias', type=str, required=True)
    parser.add_argument('--par_esml_model_name', dest='par_esml_model_name', type=str, required=True)
    parser.add_argument('--par_aml_model_name', dest='par_aml_model_name', type=str, required=False)
    parser.add_argument('--par_esml_env', type=str, help='ESML environment: dev,test,prod', required=True)
    
    parser.add_argument('--model_name', dest='model_name', type=str, required=True)
    parser.add_argument('--model_path', dest='model_path', type=str, required=True)

    parser.add_argument('--project_number', dest='project_number', type=str, required=True)
    parser.add_argument('--ml_type', dest='ml_type', type=str, required=True)
    parser.add_argument('--secret_name_tenant', dest='secret_name_tenant', type=str, required=True)
    parser.add_argument('--secret_name_sp_id', dest='secret_name_sp_id', type=str, required=True)
    parser.add_argument('--secret_name_sp_secret', dest='secret_name_sp_secret', type=str, required=True)

    # envs
    parser.add_argument('--dev_resourcegroup_id', dest='dev_resourcegroup_id', type=str, required=True)
    parser.add_argument('--dev_workspace_name', dest='dev_workspace_name', type=str, required=True)
    parser.add_argument('--dev_subscription_id', dest='dev_subscription_id', type=str, required=True)

    parser.add_argument('--test_resourcegroup_id', dest='test_resourcegroup_id', type=str, required=True)
    parser.add_argument('--test_workspace_name', dest='test_workspace_name', type=str, required=True)
    parser.add_argument('--test_subscription_id', dest='test_subscription_id', type=str, required=True)

    parser.add_argument('--prod_resourcegroup_id', dest='prod_resourcegroup_id', type=str, required=True)
    parser.add_argument('--prod_workspace_name', dest='prod_workspace_name', type=str, required=True)
    parser.add_argument('--prod_subscription_id', dest='prod_subscription_id', type=str, required=True)

    #parser.add_argument('--metrics_data', dest='metrics_data', type=str, required=True)
    
    
    args = parser.parse_args()
    print("init() started - train_post_automl_step...")

    try:
        model_version_in = int(args.par_esml_model_version) # Model version to compare scoring with (MLOps INNER LOOOP)
        esml_inference_mode = bool(args.par_esml_inference_mode) # Verify, should be False
        esml_env = args.par_esml_env
        # model info
        esml_model_alias = args.par_esml_model_alias
        esml_modelname = args.par_esml_model_name
        aml_model_name = args.par_aml_model_name
        target_column_name = args.target_column_name
        model_path = args.model_path
        model_name = args.model_name

        #project info & security
        project_number = args.project_number
        ml_type = args.ml_type

        secret_name_tenant = args.secret_name_tenant
        secret_name_sp_id = args.secret_name_sp_id
        secret_name_sp_secret = args.secret_name_sp_secret

        #envs
        dev_subscription_id = args.dev_subscription_id
        test_subscription_id = args.test_subscription_id
        prod_subscription_id = args.prod_subscription_id

        dev_resourcegroup_id = args.dev_resourcegroup_id
        test_resourcegroup_id = args.test_resourcegroup_id
        prod_resourcegroup_id = args.prod_resourcegroup_id

        dev_workspace_name = args.dev_workspace_name
        test_workspace_name = args.test_workspace_name
        prod_workspace_name = args.prod_workspace_name

        #metrics_data = args.metrics_data
        #print(metrics_data)

        if_user_implmeneted_model_compare = False
        if(if_user_implmeneted_model_compare):
            print("Loading model version {} from path: model.pkl to compare the future trained model with (version 0 if first time)".format(model_version_in))
            try:
                # ###############  Custom code below - Load model. Tip: Look at how ESML loads model with AutoML automatically
                #prev_model = joblib.load("model.pkl")
                print("Loading previous registered (current winning model) - success - model.pkl")
                # ###############  Custom code below -  Load model
            except:
                pass

        run = Run.get_context()
        ws = run.experiment.workspace
        ws = Workspace.from_config() if type(run) == _OfflineRun else run.experiment.workspace
        datastore = ws.get_default_datastore()

        # INPUT:
        it1 = iter(run.input_datasets.items())
        #train_ds = next(it1)[1] 
        #validate_ds = next(it1)[1] # Get 2nd DATASET: GOLD_VALIDATE

        test_ds = next(it1)[1] # Get 3rd DATASET: GOLD_TEST
        print("Azure ML Dataset Test loaded successfully. {}".format(test_ds.name))

        # OUTPUT: PATHS
        # 1) Save META data: "WHAT data was used, when did the training occur in time, etc "  (train_gold path, run_id, pipeline_id )
        it = iter(run.output_datasets)
        last_gold_training_run_name =next(it) # Get 1st key in dictionary
        last_gold_training_run = run.output_datasets[last_gold_training_run_name]

        # 2) Save TRAINING in lake also (besides in Azure ML as experiment), with parameter in real time: DATE_FOLDER, MODEL_VERSION from calling applicatiom (Data factory)
        date_in = args.par_esml_training_date
        date_infolder = datetime.datetime.strptime(date_in, '%Y-%m-%d %H:%M:%S.%f') # UTC string to DateTime object
        esml_training_day_date_out = date_infolder.strftime('%Y/%m/%d')
        run_id = run.parent.id #run.id
        
        # Example: projects/project002/11_diabetes_model_reg/train/gold/dev/Train/{"2020/01/01"}/{id}/
        historic_path = args.esml_train_lake_template.format(id_folder=run_id)

        print("train_post_automl_step.py.init() success: Fetched INPUT and OUTPUT datasets - now lets COMPARE in the compare(test_ds) method, and then INNER / OUTER LOOP")

    except Exception as e:
        raise

def compare(test_ds):
    try:
        print("compare() started...")
        test_scoring = None # IESMLTestScoringFactory
        comparer = None # IESMLModelCompare
        #trainer = None # IESMLTrainer

        # Optional CUSTOMIZATION ############### Optional: You can CUSTOMIZE, by implementing your own CLASS that supports interfaces/abstract classes: IESMLTestScoringFactory,IESMLModelCompare
        test_scoring = ESMLTestScoringFactory(ml_type) # Optional: IF , you want to have a customized way of calculating Test_set scoring need to implement your own IESMLTestScoringFactory
        comparer = ESMLModelCompare(setting_path = "") # Optional: IF, you want to have a customized way, You need to implement IESMLModelCompare

        # Note: You can get this info in ESML by p.get_all_envs() (where p is ESMLProject)
        all_envs ={'dev': {'subscription_id': dev_subscription_id,'resourcegroup_id': dev_resourcegroup_id,'workspace_name': dev_workspace_name},
        'test': {'subscription_id': test_subscription_id,'resourcegroup_id': test_resourcegroup_id,'workspace_name': test_workspace_name},
        'prod': {'subscription_id': prod_subscription_id,'resourcegroup_id': prod_resourcegroup_id,'workspace_name': prod_workspace_name}}

        # OptionalCUSTOMIZE END ###############

        controller = ESMLController(comparer,test_scoring,project_number,esml_modelname, esml_model_alias,all_envs, secret_name_tenant,secret_name_sp_id,secret_name_sp_secret) # IESMLController: you do not have to change/implemen this class. Dependency injects default or your class.
        calc_test_scoring_compare_register(controller,ws,target_column_name,esml_modelname,esml_model_alias, esml_env, test_ds,ml_type)
        print("compare() - calc_test_scoring_compare_register() - SUCCESS!")
    except Exception as e:
        print(e)
        raise

def calc_test_scoring_compare_register(controller,ws,target_column_name,esml_modelname,esml_model_alias, esml_current_env, test_ds, ml_type):
    test_scoring = controller.ESMLTestScoringFactory # IESMLTestScoringFactory
    comparer = controller.ESMLComparer # IESMLModelCompare
    controller.dev_test_prod = esml_current_env

    ##1 ) Get "current" BEST mpodel 
    current_model,run_id_tag, model_name = "","",""

    current_model,run_id_tag, model_name = IESMLController.get_best_model_via_modeltags_only_DevTestProd(ws,controller.experiment_name)
    if(current_model is None):
        print("No existing model with experiment name {}. The Model name will now be same as experiment name".format(controller.experiment_name))
        current_model = None
        run_id_tag = ""
        model_name = controller.experiment_name
    else:
        print("Current BEST model is: {} from Model registry with experiment_name-TAG {}, run_id-TAG {}  model_name-TAG {}".format(current_model.name,controller.experiment_name,run_id_tag,model_name))
        if ("esml_time_updated" in current_model.tags):
            print("esml_time_updated: {}".format(current_model.tags.get("esml_time_updated")))
        print("status_code : {}".format(current_model.tags.get("status_code")))
        print("model_name  : {}".format(current_model.tags.get("model_name")))
        print("trained_in_workspace   : {}".format(current_model.tags.get("trained_in_workspace")))

    print ("esml_modelname inparameter {} and controller.experiment_name: {} and get_betModel, model_name {} ".format(esml_modelname,controller.experiment_name,model_name))

    ##2) Register NEW TRAINED model, with TAG status_code=esml_new_trained
    time_stamp = str(datetime.datetime.now())
    ml_flow_stage = IESMLController._get_flow_equivalent(IESMLController.esml_status_new)
    tags = {"esml_time_updated": time_stamp,"status_code": IESMLController.esml_status_new,"mflow_stage":ml_flow_stage, "run_id": run_id, "model_name": model_name, "trained_in_environment": esml_current_env, 
        "trained_in_workspace": ws.name, "experiment_name": controller.experiment_name, "trained_with": "AutoMLStep"}

    ##2b) Register NEW model in CURRENT env
    model = controller._register_aml_model(model_path,model_name,tags,ws,"")
    fitted_model_1 = None
    
    #2c) Get fitted_model_1, best_automl_run,model

    '''
    try:
        fitted_model_1 = joblib.load("model.pkl")
        print("load Model with joblib.load, name model.pkl SUCCESS") # SUCCESS!
    except Exception as e:
        print("Cannot load Model with name model.pkl")
    '''

####################### Get AutoMLRun from AutoMLStep and best_trained_model etc #####################
    step_name = "AutoML TRAIN in [{}]".format(esml_current_env)
    print("step_name: {}".format(step_name))


    pipeline_run = PipelineRun(run.experiment, run_id = run.parent.id)
    #2023: does not work anymore  ->> pipeline_run = run.parent # It will return Run() instead of PipelineRun()... Parent is the pipeline run, current is the current step.
    ## ERROR: '_SubmittedRun' object has no attribute 'get_steps'
    ## ERROR: AttributeError: 'Run' object has no attribute 'get_steps' # Need to typecast, or just reydrate PipelineRun from run.id

    try:
        step_list = list(pipeline_run.get_steps())
        print("INFO: pipeline_run = run.parent")
    except:
        print("Error: ESML info: This should not happen, since Pipleine with AutoMLStep")
        pipeline_run = PipelineRun(run.experiment, run_id = run.id)
        step_list = list(pipeline_run.get_steps())
        print("INFO: pipeline_run = run")

    step_len = len(step_list) # 6
    automl_step_id = 1 #  The second last step. This current step, is the last step with index 0

    automl_run_step_by_index = step_list[automl_step_id]
    print("automl_run_step_by_index: {} and type {}".format(automl_run_step_by_index.id,type(automl_run_step_by_index)))
    automl_step_run_id = automl_run_step_by_index.id
    print("automl_step_run_id:{} which is 'new_run_id' in comparer.compare_scoring_current_vs_new_model".format(automl_step_run_id))
    
    experiment_run = ws.experiments[controller.experiment_name] # Get the experiment. Alternatively: Experiment(workspace=source_workspace, name=experiment_name)
    automl_step_run = AutoMLRun(experiment_run, run_id = automl_step_run_id)
    best_run, fitted_model_1 = automl_step_run.get_output()
    #automl_step_run.register_model()

####################################
    print("Registered version {0} of model {1}".format(model.version, model.name))
    print("model_path: {}".format(model_path))
    print("model_name: {}".format(model_name))
    print("Model returned after Model.register of type {}".format(type(model)))
    #print("Model")
    #print(model)

    #3) Calculate Testset scoring on NEW model
    model, rmse, r2, mean_abs_percent_error,mae,spearman_correlation,plt, class_matthews,class_plt = test_scoring.get_test_scoring_8(ws,target_column_name,test_ds,fitted_model_1,best_run,model)
    print("Scoring for NEW model is: {},{},{},{}, {}".format(rmse,r2,mean_abs_percent_error,mae,spearman_correlation))
    a_scoring = ""
    if (controller.ESMLTestScoringFactory.ml_type == "regression"):
        a_scoring = model.tags.get("test_set_R2")
    elif (controller.ESMLTestScoringFactory.ml_type == "classification"):
        a_scoring = model.tags.get("test_set_Accuracy")
    print("Verifying that at least 1 scoring exists in TAGS on model: {}".format(a_scoring))

    ## 4) COMPARE if NEW model is better, than all else:
    next_environment = controller.get_next_environment()
    target_ws = controller.get_target_workspace(current_environment = esml_current_env, current_ws = ws, target_environment = esml_current_env)

    promote_new_model,source_model_name,source_run_id,source_best_run,source_model,leading_model = comparer.compare_scoring_current_vs_new_model(
        new_run_id =automl_step_run_id, # pipeline_run_id, #main_run.id,
        current_ws = ws,
        current_environment = esml_current_env,
        target_environment = esml_current_env,
        target_workspace = target_ws,
        experiment_name = controller.experiment_name)

    print("INNER LOOP (dev->dev) - PROMOTE?")
    if (promote_new_model == True): # Better than all in DEV?! (Dev or Test,  is usually current_env) - model or current_model
        print("Promoted model! in environment {}".format(esml_current_env))
        model_registered_in_target = controller.register_model(source_ws=ws, target_env=esml_current_env, source_model=model, run=automl_step_run,esml_status=IESMLController.esml_status_promoted_2_dev) 
        print("Promoted model! in environment {}".format(esml_current_env))

        # Better than all in DEV, Lets check if its better than all in TEST? (or prod)
        next_environment = controller.get_next_environment() # Test, or PROD
        print("OUTER LOOP(dev-test): Now trying to compare with models in environment: {}".format(next_environment))
        try:
            promote_new_model,source_model_name,source_run_id,source_best_run,source_model,leading_model = comparer.compare_scoring_current_vs_new_model(
                new_run_id = automl_step_run_id,
                current_ws = ws,
                current_environment = esml_current_env,
                target_environment = next_environment,
                target_workspace = target_ws,
                experiment_name = controller.experiment_name)

            print("OUTER LOOP (dev-test): Compared 2nd time - Outer loop: Success comparing, promote_model is: {}".format(promote_new_model))

            if (promote_new_model == True):
                print("Now registering model in TARGET environment {}".format(next_environment))
                #model_registered_in_target = controller.register_model(source_ws=ws, target_env="test", source_model=model,run=None,esml_status=IESMLController.esml_status_promoted_2_test)
                model_registered_in_target = controller.register_model(source_ws=ws, target_env=next_environment, source_model=model,run=None)
                print("Registered model {} with version {} in TEST".format(model_registered_in_target.name,model_registered_in_target.version))

        except Exception as e1:
            print("Error/Warning: OUTER loop. Maybe you don't have a TEST and PROD environment setup? Are you running in DEMO-mode with only DEV environment")
            print(e1)

    print("Done: INNER and OUTER loop to Test is done automatically. See human approval gate in Azure Devops staging to get TEST to PROD")

def save_results():
    try:
        print("Saving training metadata: scoring etc to dataset")
        last_gold_run_filename = "last_train_run.csv"
        if not (last_gold_training_run is None):
            os.makedirs(last_gold_training_run, exist_ok=True)
            print("%s created" % last_gold_training_run)
            path_last_gold_run = last_gold_training_run + "/"+last_gold_run_filename
            print("Saving last_gold_run.csv at: {}".format(path_last_gold_run))

            # create the Pandas dataframe with meta, save to .csv for "Azure datafactory WriteBack pipeline/step" to use
            date_now_str = str(datetime.datetime.now())

            model_version_new = (model_version_in+1)
            last_gold_run_data = [[run_id, historic_path,date_in,date_now_str,model_version_in,model_version_new]]
            df2 = pd.DataFrame(last_gold_run_data, columns = ['pipeline_run_id', 'training_data_used', 'training_data_source_date', 'date_at_pipeline_run','model_version_current','model_version_newly_trained'])
            written_df2 = df2.to_csv(path_last_gold_run, encoding='utf-8',index=False)
            print("Pipeline ID (Steps runcontext.parent.id) {}".format(run_id))

    except Exception as e:
        raise

if __name__ == "__main__":
    init()
    compare(test_ds)
    save_results()