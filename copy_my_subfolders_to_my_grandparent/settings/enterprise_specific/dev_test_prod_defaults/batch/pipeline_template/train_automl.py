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

from your_code.your_custom_code import In2GoldProcessor,Trainer

try: # not needed, but since AutoML scoring script copied, we'll keep this logging.
    log_server.enable_telemetry(INSTRUMENTATION_KEY)
    log_server.set_verbosity('INFO')
    logger = logging.getLogger('azureml.automl.core.scoring_script')
except:
    pass

def init():
    global prev_model,train_ds,validate_ds,test_ds, last_gold_training_run,datastore,historic_path,run_id,active_folder,date_in,model_version_in,esml_env,esml_model_alias,esml_modelname,aml_model_name

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

        logger.info("Loading model version {} from path: model.pkl to compare the future trained model with (version 0 if first time)".format(model_version_in))
        try:
            #prev_model = joblib.load("model.pkl")
            logger.info("Loading previous registered (current winning model) - success - model.pkl")
        except:
            pass

        run = Run.get_context()
        ws = run.experiment.workspace
        datastore = ws.get_default_datastore()

        # INPUT:
        train_ds = next(iter(run.input_datasets.items()))[1] # Get 1st DATASET
        #train_df = train_ds.to_pandas_dataframe()

        validate_ds = next(iter(run.input_datasets.items()))[1] # Get 2nd DATASET
        #validate_df = validate_ds.to_pandas_dataframe()

        test_ds = next(iter(run.input_datasets.items()))[1] # Get 3rd DATASET
        #test_df = validate_ds.to_pandas_dataframe()

        logger.info("Azure ML Dataset Train, Validate, Test loaded successfully. {}, {}, {}".format(train_ds.name,validate_ds.name,test_ds.name))
        
        # OUTPUT: PATHS
        # 1) Save META data: "WHAT data was used, when did the training occur in time, etc "  (train_gold path, run_id, pipeline_id )
        it = iter(run.output_datasets)
        last_gold_training_run_name =  next(it) # Get 1st key in dictionary
        last_gold_training_run = run.output_datasets[last_gold_training_run_name]

        # 2) Save TRAINING in lake also (besides in Azure ML as experiment), with parameter in real time: DATE_FOLDER, MODEL_VERSION from calling applicatiom (Data factory)
        date_in = args.par_esml_training_date
        date_infolder = datetime.datetime.strptime(date_in, '%Y-%m-%d %H:%M:%S.%f') # UTC string to DateTime object
        esml_scoring_date_out = date_infolder.strftime('%Y/%m/%d') #  Save scoring same date as IN data 'in/2020/01/01' and 'gold_scored/2020/01/01' (but can be different, depends on choice of meta)
        run_id = run.parent.id #run.id
        historic_path = args.esml_train_lake_template.format(date_folder = esml_scoring_date_out,id_folder= run_id)
        # Example: 'projects/project002/11_diabetes_model_reg/inference/{model_version}/gold/[dev]/{date_folder}/{id_folder}/'  ...where [dev] is set during [CREATION] not {RUNTIME} parameter.
        # Example: projects/project002/11_diabetes_model_reg/train/gold/dev/{id_folder}/

        logger.info("train_gold.py.init() success: Fetched INPUT and OUTPUT datasets - now lets TRAIN in the train() method")

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

def train(train_ds,validate_ds,test_ds):
    try:
        logger.info("train() started...")

        # ###############  Custom code below - TRAIN model,e.g. implement the Trainer class 3 methods
        ml_type = "regression"

        aml_model_name, current_leader_model, current_leader_scoring = get_aml_model_and_scoring()
        custom_code = Trainer(aml_model_name,esml_modelname,esml_model_alias, esml_env, ml_type,train_ds,validate_ds,test_ds)
        custom_code.train()
        custom_code.calculate_test_set_scoring()

        promote = custom_code.compare_scoring_current_vs_new_model(current_leader_model,current_leader_scoring)
        # ###############  Custom code above  #####################

        if (promote == True):
            register_model_in_correct_workspace()

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

def save_results():
    try:
        logger.info("Saving training metadata: scoring etc to dataset")
        last_gold_run_filename = "last_train_run.csv"
        if not (last_gold_training_run is None):
            os.makedirs(last_gold_training_run, exist_ok=True)
            print("%s created" % last_gold_training_run)
            path_last_gold_run = last_gold_training_run + "/"+last_gold_run_filename
            logger.info("Saving last_gold_run.csv at: {}".format(path_last_gold_run))

            # create the pandasd dataframe with meta, save to .csv for "Azure datafactory WriteBack pipeline/step" to use
            date_now_str = str(datetime.datetime.now())

            model_version_new = (model_version_in+1)
            last_gold_run_data = [[run_id, historic_path,date_in,date_now_str,model_version_in,model_version_new]]
            df2 = pd.DataFrame(last_gold_run_data, columns = ['pipeline_run_id', 'training_data_used', 'training_data_source_date', 'date_at_pipeline_run','model_version_current','model_version_newly_trained'])
            written_df2 = df2.to_csv(path_last_gold_run, encoding='utf-8',index=False)
            print("Pipeline ID (Steps runcontext.parent.id) {}".format(run_id))

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise
def get_aml_model_and_scoring():# Find MODEL and SCORING based on 'esml_model_alias' and 'esml_modelname' 
    model_name = aml_model_name # Set global var, which can be None
    leader_model = None 
    leader_scoring = None

    if(model_name is not None):
        pass # fetch models

    return model_name, leader_model, leader_scoring 

def register_model_in_correct_workspace():
    pass

if __name__ == "__main__":
    init()
    train(train_ds,validate_ds,test_ds)
    save_results()