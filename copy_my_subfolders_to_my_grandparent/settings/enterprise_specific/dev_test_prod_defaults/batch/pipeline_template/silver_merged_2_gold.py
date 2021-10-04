import argparse
import os
import datetime
import numpy as np
import pandas as pd
from azureml.core import Run
from azureml.core import Dataset
from azureml.data.dataset_factory import FileDatasetFactory
from your_code.your_custom_code import In2GoldProcessor,M01In2GoldProcessor

parser = argparse.ArgumentParser("gold")
parser.add_argument('--target_column_name', dest='target_column_name',type=str, help="Target Label - column to add", required=True)
#parser.add_argument('--output_to_score_gold', dest='output_to_score_gold',help='OutputFileDatasetConfig GOLD',required=True)

parser.add_argument('--par_esml_scoring_date', dest='par_esml_scoring_date',help='Date_folder in lake  to score',required=True)
parser.add_argument('--par_esml_model_version', dest='par_esml_model_version',help='Model version to score with 1,2,3',required=True)
parser.add_argument('--esml_output_lake_template', dest='esml_output_lake_template',help='Template path with plae holders to write GOLD_TO_SCORE',required=True)
parser.add_argument('--par_esml_env', type=str, help='ESML environment: dev,test,prod', required=False)
parser.add_argument('--azure_dataset_names', nargs='+',type=str, help='List of SILVER Azure dataset names', required=False)
args, remaining_names = parser.parse_known_args()

run = Run.get_context()
ws = run.experiment.workspace
datastore = ws.get_default_datastore()

# INPUT DATASETS # key is input-name of Dataset. value is target path when mode is download or mount, or the actual Dataset object if mode is DIRECT (adls gen2).
ds = None
combined_df = None

################################# EDIT BELOW - DEMO Example below just "merges all silver datasets", and also samples 10% to_score

for aname in args.azure_dataset_names:
    print("ESML test print azure_dataset_name: {}".format(aname))

# CUSTOM parameters, sent in the  pipeline_step
parser.add_argument('--esml_optional_unique_scoring_folder', dest='my_custom_parameter', required=False)
args_again = parser.parse_args()
print("My custom ArgumentParser parameter {}".format(args_again.my_custom_parameter))

LOOP_ALL_SILVERS = False
if (LOOP_ALL_SILVERS): # Alt 1 DEMO) Loop datasets (MERGE silvers to GOLD)
    for ds_name in run.input_datasets: # Dictionary
        print(ds_name) # M11_ds01_diabetes_inference_SILVER

        ############ Option 1: Do your MERGE logic here ############
        if (ds is not None): # 2nd time, merge with 1st dataset
            df = run.input_datasets[ds_name].to_pandas_dataframe()
            combined_df = combined_df.append(df, ignore_index=True)
        else:
            ds = run.input_datasets[ds_name] # Fetch dataset
            combined_df = ds.to_pandas_dataframe()

############ Option 2: Do your MERGE logic as below, instead of a loop... ############
aml_ds = next(iter(run.input_datasets.items()))[1] # Get 1st DATASET
df = aml_ds.to_pandas_dataframe()

aml_ds2 = next(iter(run.input_datasets.items()))[1] # Get 2nd DATASET
df2 = aml_ds2.to_pandas_dataframe()
combined_df = M01In2GoldProcessor.M01_merge_silvers(df,df2)

'''
# Alt2 a) Direct access to Dataset ( DEMO purpose only)
ds01 = run.input_datasets[args.azure_dataset_names[0]] # Alt 1) Get via input_datastes array (just demo purpose, to use same way makes mor sense)
ds01_df = ds01.to_pandas_dataframe()

# Alt2b) Direct access to registered Dataset ( DEMO purpose only)
ds02 = Dataset.get_by_name(workspace=ws, name=args.azure_dataset_names[1],  version='latest') # Alt 2) Get via workspace (just demo purpose, use this for all)
ds02_df = ds02.to_pandas_dataframe() 
'''

################################# EDIT ABOVE - Create your "GOLD_TO_SCORE" from 1-M Silver datasets

combined_df.reset_index(inplace=True, drop=True)
output_to_score_gold_name =  next(iter(run.output_datasets)) # Get 1st key in dictionary
output_to_score_gold = run.output_datasets[output_to_score_gold_name]

if not (output_to_score_gold is None):
    os.makedirs(output_to_score_gold, exist_ok=True)
    print("%s created" % output_to_score_gold)
    path = output_to_score_gold + "/gold_to_score.parquet"
    
    # 1) Save/Overwrite "latest" data: 'projects/project002/11_diabetes_model_reg/inference/0/gold/dev/', for SCORE_GOLD step to read
    write_df = combined_df.to_parquet(path,engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)
    
    # Copy also to a "date_folder", for history in the lake
    date_infolder = datetime.datetime.strptime(args.par_esml_scoring_date, '%Y-%m-%d %H:%M:%S.%f')
    esml_scoring_date_out = date_infolder.strftime('%Y/%m/%d') #  Save scoring same date as IN-data 'in/2020/01/01' for 'gold_scored/2020/01/01'

    # 2) Save historic data, with runtime parameters 'projects/project002/11_diabetes_model_reg/inference/{model_version}/gold/dev/{date_folder}/{id_folder}/'
    print("Step run.run_id {}".format(run.id))
    print("Piepline run.parent.id {}".format(run.id))
    run_id = run.parent.id #run.id
    
    new_path = args.esml_output_lake_template.format(model_version = args.par_esml_model_version, date_folder = esml_scoring_date_out,id_folder= run_id)
    FileDatasetFactory.upload_directory(src_dir=output_to_score_gold, target=(datastore, new_path), pattern=None, overwrite=True, show_progress=False)