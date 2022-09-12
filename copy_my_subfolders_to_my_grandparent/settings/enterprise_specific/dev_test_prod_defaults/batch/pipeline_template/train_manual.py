from ctypes import wstring_at
import json
import logging
import os
import pickle
import numpy as np
import pandas as pd
import joblib
import azureml.automl.core
from azureml.automl.core.shared import logging_utilities, log_server
from azureml.telemetry import INSTRUMENTATION_KEY
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
import tempfile

try: # not needed, but since AutoML scoring script copied, we'll keep this logging.
    log_server.enable_telemetry(INSTRUMENTATION_KEY)
    log_server.set_verbosity('INFO')
    logger = logging.getLogger('azureml.automl.core.scoring_script')
except:
    pass

def init():
    global prev_model,train_ds,validate_ds,test_ds, last_gold_training_run,datastore,historic_path,run,run_id,active_folder,date_in,model_version_in,esml_env,esml_model_alias,esml_modelname,aml_model_name,target_column_name,ws

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
    
    
    args = parser.parse_args()
    logger.info("init() started...")

    try:
        model_version_in = int(args.par_esml_model_version) # Model version to compare scoring with (MLOps INNER LOOOP)
        esml_inference_mode = bool(args.par_esml_inference_mode) # Verify, should be False
        esml_env = args.par_esml_env
        # model info
        esml_model_alias = args.par_esml_model_alias
        esml_modelname = args.par_esml_model_name
        aml_model_name = args.par_aml_model_name
        target_column_name = args.target_column_name

        if_user_implmeneted_model_compare = False
        if(if_user_implmeneted_model_compare):
            logger.info("Loading model version {} from path: model.pkl to compare the future trained model with (version 0 if first time)".format(model_version_in))
            try:
                # ###############  Custom code below - Load model. Tip: Look at how ESML loads model with AutoML automatically
                #prev_model = joblib.load("model.pkl")
                logger.info("Loading previous registered (current winning model) - success - model.pkl")
                # ###############  Custom code below -  Load model
            except:
                pass

        run = Run.get_context()
        ws = run.experiment.workspace
        datastore = ws.get_default_datastore()

        # INPUT:
        it1 = iter(run.input_datasets.items())
        train_ds = next(it1)[1] 
        #train_ds = next(iter(run.input_datasets.items()))[1] # Get 1st DATASET: GOLD "TRAIN"
        #print("train_ds is = {}".format(train_ds))
        #train_df = train_ds.to_pandas_dataframe()

        validate_ds = next(it1)[1] # Get 2nd DATASET: GOLD_VALIDATE
        #validate_df = validate_ds.to_pandas_dataframe()

        test_ds = next(it1)[1] # Get 3rd DATASET: GOLD_TEST
        #test_df = validate_ds.to_pandas_dataframe()

        logger.info("Azure ML Dataset Train, Validate, Test loaded successfully. {}, {}, {}".format(train_ds,validate_ds,test_ds))
        print("Azure ML Dataset Train, Validate, Test loaded successfully. {}, {}, {}".format(train_ds,validate_ds,test_ds))
        print("Azure ML Dataset Tran is of TYPE: {}".format(type(train_ds)))

        try:
            train_ds2 = Dataset.get_by_name(workspace=ws, name=train_ds,  version='latest')
            print("train_ds2.Azure ML Dataset  is of TYPE: {}".format(type(train_ds2)))
            print("train_ds2.tags = {}".format(train_ds2.tags))
        except: 
            pass
        
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
        #historic_path = args.esml_train_lake_template.format(date_folder = esml_training_day_date_out,id_folder= run_id)
        # Example: projects/project002/11_diabetes_model_reg/train/gold/dev/Train/{"2020/01/01"}/{"8e9792b1f7e84d40b3dd29dbc5a91a37"}/
        historic_path = args.esml_train_lake_template.format(id_folder=run_id)
        # Example: projects/project002/11_diabetes_model_reg/train/gold/dev/Train/{8e9792b1f7e84d40b3dd29dbc5a91a37}/
        

        logger.info("train_gold.py.init() success: Fetched INPUT and OUTPUT datasets - now lets TRAIN in the train() method")

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

def train(train_ds,validate_ds,test_ds):
    try:
        logger.info("train() started...")
        print("train() started...")
        test_scoring = None # IESMLTestScoringFactory
        comparer = None # IESMLModelCompare
        #trainer = None # IESMLTrainer

        # CUSTOMIZE ############### Optional: You can CUSTOMIZE how test_set scoring is calculated, and model comparison is done, by implementing your own CLASS that supports interfaces/abstract classes: IESMLTestScoringFactory,IESMLModelCompare
        project_number = 'project001' # TODO: Look in your lake_settings.json
        ml_type = "regression"
        test_scoring = ESMLTestScoringFactory(ml_type) # IF, you want to have a customized way of calculating Test_set scoring need to implement your own IESMLTestScoringFactory
        comparer = ESMLModelCompare(setting_path = "") # IF, you want to have a customized way, You need to implement IESMLModelCompare

        secret_name_tenant = "esml-tenant-id" # TODO: Look in your security_config.json
        secret_name_sp_id = "esml-project-sp-id" # TODO: Look in your security_config.json
        secret_name_sp_secret = "esml-project-sp-secret" # TODO: Look in your security_config.json

        # # TODO: You can get this info by p.get_all_envs() (where p is ESMLProject) and then just copy and paste the dictionary here:
        all_envs = {
            'dev': {'subscription_id': 'x','resourcegroup_id': 'y', 'workspace_name': 'z'},
            'test': {'subscription_id': 'x','resourcegroup_id': 'y','workspace_name': 'z'},
            'prod': {'subscription_id': 'x','resourcegroup_id': 'y','workspace_name': 'z'}}
        # CUSTOMIZE END ###############
        controller = ESMLController(comparer,test_scoring,project_number,esml_modelname, esml_model_alias,all_envs, secret_name_tenant,secret_name_sp_id,secret_name_sp_secret) # IESMLController: you do not have to change/implemen this class. Dependency injects default or your class.

        train_test_compare_register(controller,ws,target_column_name,esml_modelname,esml_model_alias, esml_env, train_ds,validate_ds,test_ds,ml_type)


    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

def train_test_compare_register(controller,ws,target_column_name,esml_modelname,esml_model_alias, esml_current_env, train_ds,validate_ds,test_ds, ml_type):
    test_scoring = controller.ESMLTestScoringFactory # IESMLTestScoringFactory
    comparer = controller.ESMLComparer # IESMLModelCompare
    trainer = None # IESMLTrainer

    controller.dev_test_prod = esml_current_env
    model_name = None
    main_run = run.parent # Parent is the pipeline run, current 'run' is just the current step in pipeline.

    ##1 ) Get "current" 'last_gold_training_run' [pipeline_run_id, training_data_used]
    current_model,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(ws,controller.experiment_name)
    model_name = model_name_tag

    # CUSTOMIZE ############### If using MANUAL ML you need to implement a Trainer class, that support ITrainer abstract methods/interfaces

    # ITrainer: Defaults to using AutoML. Optionally you can implement this. Else you need to implement ITrainer in 'YourTrainer' class
    trainer = Trainer(model_name,esml_modelname,esml_model_alias, esml_current_env, ml_type,train_ds,validate_ds,test_ds)
    train_run, aml_model,fitted_model_new = trainer.train(train_ds,validate_ds)

    # CUSTOMIZE ###############

    ##2 ) Register NEW TRAINED model, with TAG status_code=esml_new_trained
    tags = {"status_code": IESMLController.esml_status_new, "run_id": run_id, "model_name": model_name, "trained_in_environment": esml_current_env, 
        "trained_in_workspace": ws.name, "experiment_name": controller.experiment_name, "trained_with": "PythonScriptStep-ManualML"}

    ##3) Register NEW model in CURRENT env
    model = controller._register_aml_model(full_local_path=None,model_name=model_name,tags=tags,target_ws=ws,description_in="")

    ##4) Calculate TEST_SET SCORING  on NEW model(label,ws, GoldTest, model, fitted_model, source_best_run/run)
    rmse, r2, mean_abs_percent_error,mae,spearman_correlation,plt, dummy = test_scoring.get_test_scoring_8(ws,target_column_name,test_ds,fitted_model_new,main_run,aml_model)

    next_environment = controller.get_next_environment()

    #  current_ws,current_environment, target_environment,target_workspace, experiment_name)
    target_ws = controller.get_target_workspace(current_environment = esml_current_env, current_ws = ws, target_environment = esml_current_env)

    ## 5) COMPARE if better

    promote_new_model,source_model_name,new_run_id,target_model_name, target_best_run_id,target_workspace,source_model = comparer.compare_scoring_current_vs_new_model(
        new_run_id = main_run.id,
        current_ws = ws,
        current_environment = esml_current_env,
        target_environment = esml_current_env,
        target_workspace = target_ws,
        experiment_name = trainer.experiment_name)

    print("compared once, 1 time, inner loop - Dev")

    ## 6) REGISTER model, if better

    if (promote_new_model == True): # Better than all in DEV?! (Dev or Test,  is usually current_env)
        model_registered_in_target = controller.register_model(source_ws=ws, target_env=esml_current_env, source_model_to_copy_tags_from=aml_model)
        print("registered in {}".format(esml_current_env))

        # Better than all in DEV, Lets check if its better than all in TEST? (or prod)
        next_environment = controller.get_next_environment() # Test, or PROD
        print("OUTER LOOP: Now trying to compare with models in environment: {}".format(next_environment))

        try:
            promote_new_model,source_model_name,new_run_id,target_model_name, target_best_run_id,target_workspace,source_model = comparer.compare_scoring_current_vs_new_model(
                new_run_id = main_run.id,
                current_ws = ws,
                current_environment = esml_current_env,
                target_environment = next_environment,
                target_workspace = target_ws,
                experiment_name = trainer.experiment_name)

            print("Compared 2nd time - Outer loop: Success comparing, promote_model is: {}".format(promote_new_model))
            if (promote_new_model == True):
                model_registered_in_target = controller.register_model(source_ws=ws, target_env=next_environment, source_model_to_copy_tags_from=model) # next_environment should be 'test'
                print("Registered model {} with version {} in {}".format(model_registered_in_target.name,model_registered_in_target.version,next_environment))
        except Exception as e1:
            print("Error/Warning: OUTER loop. Maybe you don't have a TEST and PROD environment setup? Are you running in DEMO-mode with only DEV environment")
            print(e1)

    print("Done: INNER and OUTER loop")

def save_results():
    try:
        logger.info("Saving training metadata: scoring etc to dataset")
        last_gold_run_filename = "last_train_run.csv"
        if not (last_gold_training_run is None):
            os.makedirs(last_gold_training_run, exist_ok=True)
            print("%s created" % last_gold_training_run)
            path_last_gold_run = last_gold_training_run + "/"+last_gold_run_filename
            logger.info("Saving last_gold_run.csv at: {}".format(path_last_gold_run))

            # create the Pandas dataframe with meta, save to .csv for "Azure datafactory WriteBack pipeline/step" to use
            date_now_str = str(datetime.datetime.now())

            model_version_new = (model_version_in+1)
            last_gold_run_data = [[run_id, historic_path,date_in,date_now_str,model_version_in,model_version_new]]
            df2 = pd.DataFrame(last_gold_run_data, columns = ['pipeline_run_id', 'training_data_used', 'training_data_source_date', 'date_at_pipeline_run','model_version_current','model_version_newly_trained'])
            written_df2 = df2.to_csv(path_last_gold_run, encoding='utf-8',index=False)
            print("Pipeline ID (Steps runcontext.parent.id) {}".format(run_id))

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

if __name__ == "__main__":
    init()
    train(train_ds,validate_ds,test_ds)
    save_results()