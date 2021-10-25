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

from your_code.your_custom_code import In2GoldProcessor

try: # not needed, but since AutoML scoring script copied, we'll keep this logging.
    log_server.enable_telemetry(INSTRUMENTATION_KEY)
    log_server.set_verbosity('INFO')
    logger = logging.getLogger('azureml.automl.core.scoring_script')
except:
    pass

def init():
    global model, probabilities, gold_to_score_df, output_scored_gold,datastore,historic_path,last_gold_run,run_id,active_folder,date_in,model_version_in

    parser = argparse.ArgumentParser("Scoring the model")
    #parser.add_argument('--input_gold_name', dest="input_gold_name", type=str, required=True)
    parser.add_argument('--target_column_name', dest="target_column_name", type=str, required=True)
    parser.add_argument('--par_esml_scoring_date', dest="par_esml_scoring_date", required=True)
    parser.add_argument('--par_esml_model_version', dest="par_esml_model_version", required=True)
    parser.add_argument('--esml_output_lake_template', dest="esml_output_lake_template", required=True)
    parser.add_argument('--par_esml_inference_mode', dest='par_esml_inference_mode', type=int, required=True)

    #Optional
    parser.add_argument('--par_esml_env', type=str, help='ESML environment: dev,test,prod', required=False)
    parser.add_argument('--esml_optional_unique_scoring_folder', dest="esml_optional_unique_scoring_folder", required=False)
    
    args = parser.parse_args()

    try:
        model_version_in = args.par_esml_model_version
        esml_inference_mode = bool(args.par_esml_inference_mode)

        logger.info("Loading model version {} from path: model.pkl".format(model_version_in))
        model = joblib.load("model.pkl")
        logger.info("Model loading success - model.pkl")

        run = Run.get_context()
        ws = run.experiment.workspace
        datastore = ws.get_default_datastore()

        gold_to_score = next(iter(run.input_datasets.items()))[1] # Get DATASET
        #gold_to_score = Dataset.get_by_name(workspace=ws, name=args.input_gold_name) # Fetch registered dataset to SCORE
        logger.info("Azure Dataset GOLD to score, loaded successfully. {}".format(gold_to_score.name))
        
        # PATHS - save in 2 places
        # 1) Save LATEST GOLD_SCORED - for Azure Data factory able to know the PATH, since static in time, able to "WriteBack" scored data
        it = iter(run.output_datasets)
        output_scored_gold_name =  next(it) # Get 1st key in dictionary
        output_scored_gold = run.output_datasets[output_scored_gold_name]

        # 2) Save META data:"score_gold path, run_id, pipeline_id etc
        last_gold_run_name =  next(it) # Save meta as dataset also, for visibility in Azure ML Studio
        last_gold_run = run.output_datasets[last_gold_run_name]

        active_folder_name =  next(it) # 3rd item. Good to show where files are LOCATED inlake aslo, for Azure Data factory
        active_folder = run.output_datasets[active_folder_name]

        # 2) Save HISTORIC scoring - with parameter in real time: DATE_FOLDER, MODEL_VERSIOM from calling applicatiom (Data factory)
        date_in = args.par_esml_scoring_date
        date_infolder = datetime.datetime.strptime(date_in, '%Y-%m-%d %H:%M:%S.%f') # UTC string to DateTime object
        esml_scoring_date_out = date_infolder.strftime('%Y/%m/%d') #  Save scoring same date as IN data 'in/2020/01/01' and 'gold_scored/2020/01/01' (but can be different, depends on choice of meta)
        run_id = run.parent.id #run.id
        historic_path = args.esml_output_lake_template.format(model_version = model_version_in, date_folder = esml_scoring_date_out,id_folder= run_id)
        # Example: 'projects/project002/11_diabetes_model_reg/inference/{model_version}/gold/[dev]/{date_folder}/{id_folder}/'  ...where [dev] is set during [CREATION] not {RUNTIME} parameter.

        ################### EDIT optional things to do before scoring #########################

        # Example: Depending on how your scoring data looks like...do some adjustments.
        gold_to_score_df = gold_to_score.to_pandas_dataframe().reset_index(drop=True)
        if args.target_column_name in gold_to_score_df:
            gold_to_score_df.drop(columns=[args.target_column_name], inplace=True)
            print("Dropped target column: {}".format(args.target_column_name))
        
        ################### EDIT optional things to do before scoring END #########################

        logger.info("scoring_gold.py.init() success")

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

def run(gold_to_score_df):
    try:
        logger.info("model.predict with gold_to_score")
        data = gold_to_score_df.reset_index(drop=True) # Make sure index is gone
        result = model.predict(data)

        # predict_proba START: Supports both regression and classification - hence we need to check for .predict_proba existing (classification)
        has_predict_proba = False
        if model is not None and hasattr(model, 'predict_proba') \
                and model.predict_proba is not None and data is not None:
            try: # ADD predict_proba - IF model supports this....need to handle that case
                probability_y = model.predict_proba(data)
                has_predict_proba = True
            except Exception as ex:
                raise ValueError("Model does not support predict_proba method for given dataset \
                    type, inner error: {}".format(ex.message))
        # predict_proba END

        # Format result to a dataframe, join SCORING with its FEATURES
        df_res  = pd.DataFrame(result, columns=['prediction'])
        df_out = gold_to_score_df.join(df_res[['prediction']],how = 'left')

        if (has_predict_proba):
            if(has_iloc(probability_y)):
                df_out['predict_proba_0']  = probability_y.iloc[:,0]
                df_out['predict_proba_1']  = probability_y.iloc[:,1]
            else:
                df_out['predict_proba_0']  = probability_y[:,0]
                df_out['predict_proba_1']  = probability_y[:,1]

        # ###############  Custom code below
        # Example: Post process scored data - able to join back to SQL Database, at WriteBack activity in Azure Data factory (also for DEMO change back scaled values)
        custom_code = In2GoldProcessor(df_out)
        df_out = custom_code.scored_gold_post_process_M11_DEMO()
        # ###############  Custom code above  #####################
        
        logger.info("Saving prediction to GOLD_SCORED dataset")
        if not (output_scored_gold is None):
            os.makedirs(output_scored_gold, exist_ok=True)
            print("%s created" % output_scored_gold)
            path = output_scored_gold + "/gold_scored.parquet"
            logger.info("Saving result as PARQUET at: {}".format(path))
            written_df = df_out.to_parquet(path,engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

            # Alt 2) Note: This can also be done by Azure Data factory instead of this CPU cluster node. In a ADF Copy activity, post this pipeline, using 'latest_batch_score_run.csv file that has the 'historic_path'
            print("Also save to HISTORIC path, output_scored_gold is {}".format(output_scored_gold))
            FileDatasetFactory.upload_directory(src_dir=output_scored_gold, target=(datastore, historic_path), pattern=None, overwrite=True, show_progress=False)

        last_gold_run_filename = "last_gold_run.csv"
        if not (last_gold_run is None):
            os.makedirs(last_gold_run, exist_ok=True)
            print("%s created" % last_gold_run)
            path_last_gold_run = last_gold_run + "/"+last_gold_run_filename
            logger.info("Saving last_gold_run.csv at: {}".format(path_last_gold_run))

            # create the pandasd dataframe with meta, save to .csv for "Azure datafactory WriteBack pipeline/step" to use
            date_now_str = str(datetime.datetime.now())

            last_gold_run_data = [[run_id, historic_path,date_in,date_now_str,model_version_in]]
            df2 = pd.DataFrame(last_gold_run_data, columns = ['pipeline_run_id', 'scored_gold_path', 'date_in_parameter', 'date_at_pipeline_run','model_version'])
            written_df2 = df2.to_csv(path_last_gold_run, encoding='utf-8',index=False)
            print("Pipeline ID (Steps runcontext.parent.id) {}".format(run_id))

            # Also save full FOLDER
        if not (active_folder is None):
            os.makedirs(active_folder, exist_ok=True)
            path_active_folder = active_folder + "/"+last_gold_run_filename
            written_df3 = df2.to_csv(path_active_folder, encoding='utf-8',index=False) # DUMMY 2nd Write needed?

    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise

from scipy.sparse import issparse
def has_iloc(df_series_or_ndarray):
    if issparse(df_series_or_ndarray):
        return True
    if (isinstance(df_series_or_ndarray, pd.DataFrame)):
        return True
    if (isinstance(df_series_or_ndarray, pd.Series)):
        return True
    if (isinstance(df_series_or_ndarray, np.ndarray)):
        return False
    return False

if __name__ == "__main__":
    init()
    run(gold_to_score_df)