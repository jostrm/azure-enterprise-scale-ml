#import json
import logging
import os
#import pickle
import numpy as np
import pandas as pd
#import joblib
#import azureml.automl.core
from azureml.automl.core.shared import logging_utilities, log_server
from azureml.telemetry import INSTRUMENTATION_KEY
import argparse
from azureml.core import Run
from azureml.data.dataset_factory import FileDatasetFactory
#import datetime
import uuid

from your_code.your_custom_code import In2GoldProcessor

try: # not needed, but since AutoML scoring script copied, we'll keep this logging.
    log_server.enable_telemetry(INSTRUMENTATION_KEY)
    log_server.set_verbosity('INFO')
    logger = logging.getLogger('azureml.automl.core.scoring_script')
except:
    pass

def split():
    global gold_to_split,train,validate,test,datastore,train_ds,validate_ds,test_ds

    parser = argparse.ArgumentParser("Split the GOLD to TRAIN, TEST, VALIDATE and register as AML datasets")
    parser.add_argument('--target_column_name', dest="target_column_name", type=str, required=True)
    parser.add_argument('--par_esml_training_date', dest="par_esml_training_date", required=True)
    parser.add_argument('--par_esml_split_percentage', dest="par_esml_split_percentage",type=float, required=True)
    parser.add_argument('--par_esml_inference_mode', dest='par_esml_inference_mode', type=int, required=True)

    #Optional
    parser.add_argument('--par_esml_env', type=str, help='ESML environment: dev,test,prod', required=False)
        
    args = parser.parse_args()

    try:
        split_percentage = args.par_esml_split_percentage # Split percentage for TRAIN, default 0.6
        esml_inference_mode = bool(args.par_esml_inference_mode) # Verify, should be False

        run = Run.get_context()
        ws = run.experiment.workspace
        datastore = ws.get_default_datastore()

        gold_to_split = next(iter(run.input_datasets.items()))[1] # Get DATASET
        logger.info("Azure Dataset GOLD to SPLIT, loaded successfully. {}".format(gold_to_split.name))
        
        # 1) Register TRAIN df as dataset
        it = iter(run.output_datasets)
        train_ds_name =  next(it)
        train_ds = run.output_datasets[train_ds_name]

        # 2) Register TEST set df as dataset
        validate_ds_name =  next(it)
        validate_ds = run.output_datasets[validate_ds_name]

        # 3) Register VALIDATE df as dataset
        test_ds_name =  next(it)
        test_ds = run.output_datasets[test_ds_name]

        ################### 1) EDIT: SPLIT the GOLD data, as you wish #########################

        train,validate,test = split_gold(gold_to_split, train_percentage=split_percentage, label=args.target_column_name)

        ################### 1) end EDIT: SPLIT the GOLD data, as you wish = Done #########################

        logger.info("SPLIT_GOLD.init() success: Splitted GOLD, and registered Datasets, now lets REGISTER them in the run() method")

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

def register(train,validate,test):
    try:
        logger.info("model.predict with gold_to_score")
        train_df = train.reset_index(drop=True) # Make sure index is gone
        validate_df = validate.reset_index(drop=True) # Make sure index is gone
        test_df = test.reset_index(drop=True) # Make sure index is gone
        
        train_file = 'gold_train.parquet'
        validate_file = 'gold_validate.parquet'
        test_file = 'gold_test.parquet'

        logger.info("Registering TRAIN dataframe as Azure ML Dataset")
        if not (train_ds is None):
            os.makedirs(train_ds, exist_ok=True)
            print("%s created" % train_ds)
            path = train_ds + "/" + train_file
            logger.info("Saving result as PARQUET at: {}".format(path))
            written_df = train_df.to_parquet(path,engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            
            # Copy
            #print("Also save to GUID/Version path, train path is {}".format(train_ds))
            #version_folder = train_ds +"/"+ uuid.uuid4().hex + "/" + train_file
            #FileDatasetFactory.upload_directory(src_dir=train_ds, target=(datastore, version_folder), pattern=None, overwrite=True, show_progress=False)

        logger.info("Registering VALIDATE dataframe as Azure ML Dataset")
        if not (validate_ds is None):
            os.makedirs(validate_ds, exist_ok=True)
            print("%s created" % validate_ds)
            path = train_ds + "/gold_validate.parquet"
            write_df = validate_df.to_parquet(path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            logger.info("Saving result as PARQUET at: {}".format(path))

        logger.info("Registering TEST dataframe as Azure ML Dataset")
        if not (test_ds is None):
            os.makedirs(test_ds, exist_ok=True)
            print("%s created" % test_ds)
            path = train_ds + "/gold_test.parquet"
            write_df = test_df.to_parquet(path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
            logger.info("Saving result as PARQUET at: {}".format(path))

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

def split_gold(azure_ml_gold_dataset, train_percentage=0.6, label=None,stratified=False,seed=42):
    df = azure_ml_gold_dataset.to_pandas_dataframe()
    whats_left_for_both = round(1-train_percentage,1)  # 0.4 ...0.3 if 70%
    left_per_set = round((whats_left_for_both / 2),2) # 0.2  ...0.15
    validate_and_test = round((1-left_per_set),2) # 0.8 ....0.75

    train, validate, test = \
        np.split(df.sample(frac=1, random_state=seed), 
                [int(train_percentage*len(df)), int(validate_and_test*len(df))])

    return train,validate,test

if __name__ == "__main__":
    split()
    register(train,validate,test)