from azureml.core import Run
from azureml.core import Dataset
from azureml.telemetry import UserErrorException
import pandas as pd 
import argparse
import os
import datetime
from your_code.your_custom_code import In2GoldProcessor,M01In2GoldProcessor

# IN/OUT folder paths
parser = argparse.ArgumentParser()
parser.add_argument('--esml_input_lake_template', dest='esml_input_lake_template',type=str, required=True)
parser.add_argument('--par_esml_model_version', dest='par_esml_model_version',type=str, required=True)
parser.add_argument('--par_esml_scoring_date', dest='par_esml_scoring_date',type=str, required=True)
parser.add_argument('--par_esml_env', dest='par_esml_env',type=str, required=True)
parser.add_argument('--par_esml_inference_mode', dest='par_esml_inference_mode', type=int, required=True)

args, remaining_names = parser.parse_known_args()

# GENEREATE PATH to data
date_infolder = datetime.datetime.strptime(args.par_esml_scoring_date, '%Y-%m-%d %H:%M:%S.%f')
esml_scoring_date_in = date_infolder.strftime('%Y/%m/%d') #  String to folder structure 2020/01/01
esml_model_version = args.par_esml_model_version
esml_env = args.par_esml_env
esml_inference_mode = bool(args.par_esml_inference_mode)

print("Inference_mode: {}".format(esml_inference_mode))
print("Scoring date IN folder: {}".format(esml_scoring_date_in))

if(esml_inference_mode == True):
    input_path = args.esml_input_lake_template.format(inference_model_version = esml_model_version, dev_test_prod = esml_env, folder_date=esml_scoring_date_in)
else:
    input_path = args.esml_input_lake_template.format(dev_test_prod = esml_env, folder_date=esml_scoring_date_in)
    
input_path_csv = input_path + '*.csv'
input_path_parquet = input_path + '*.parquet'
print("IN Dataset. INPUT full path: {}".format(input_path_csv))

# 1) GET INPUT - Get .CSV or .PARQUET Dataset
run = Run.get_context()
ws = run.experiment.workspace
datastore = ws.get_default_datastore()
aml_dataset_in = None

try:
    aml_dataset_in = Dataset.Tabular.from_delimited_files(path = [(datastore, input_path_csv)]) 
except Exception as e:
    print("Could not load .CSV files from IN dataset. Now trying .PARQUET instead:  {}".format(input_path_parquet))
    aml_dataset_in = Dataset.Tabular.from_parquet_files(path = [(datastore, input_path_parquet)])

################################### 3) EDIT BELOW - feature engieering ########################

# CUSTOM parameters, sent in the  pipeline_step "step_bronze2silver_$dataset_name"
parser.add_argument('--esml_optional_unique_scoring_folder', dest='my_custom_parameter',type=str, required=False)
args_again, remaining_names_again = parser.parse_known_args()
print("My custom ArgumentParser parameter {}".format(args_again.my_custom_parameter))

df = aml_dataset_in.to_pandas_dataframe()
if(df is None):
    raise UserErrorException("df = aml_dataset_in.to_pandas_dataframe() - df is NONE!")
IS_DEMO = True
if (IS_DEMO): # Simulate feature engineering...source system might not know column name for Y, and certainly not values
    custom_code = In2GoldProcessor(df) # Drops columns, rename columns, filter data, interpolate, etc
    df = custom_code.in_to_silver_ds01_M10_M11_DEMO()
else:
    df = M01In2GoldProcessor.M01_ds01_process_in2silver(df) # Here you can add YOUR code

print("df.shape post processing {}".format(df.shape))
################################### EDIT ABOVE - feature engieering ########################

# Save as Dataset
df.reset_index(inplace=True, drop=True)
output_silver_dataset_key1 =  next(iter(run.output_datasets)) # Get 1st key in dictionary
output_silver_dataset = run.output_datasets[output_silver_dataset_key1] # args.output_silver_dataset

if not (output_silver_dataset is None):
    os.makedirs(output_silver_dataset, exist_ok=True)
    print("%s created" % output_silver_dataset)
    path = output_silver_dataset + "/silver.parquet"
    write_df = df.to_parquet(path, engine='pyarrow', index=False,use_deprecated_int96_timestamps=True,allow_truncated_timestamps=False)

print(f"Wrote prepped data to {output_silver_dataset}/silver.parquet")