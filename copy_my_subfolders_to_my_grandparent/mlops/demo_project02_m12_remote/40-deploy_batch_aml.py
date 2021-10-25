"""
Copyright (C) Microsoft Corporation. All rights reserved.​
 ​
Microsoft Corporation (“Microsoft”) grants you a nonexclusive, perpetual,
royalty-free right to use, copy, and modify the software code provided by us
("Software Code"). You may not sublicense the Software Code or any use of it
(except to your affiliates and to vendors to perform work on your behalf)
through distribution, network access, service agreement, lease, rental, or
otherwise. This license does not purport to express any claim of ownership over
data you may have shared with Microsoft in the creation of the Software Code.
Unless applicable law gives you more rights, Microsoft reserves all other
rights not expressly granted herein, whether by implication, estoppel or
otherwise. ​
 ​
THE SOFTWARE CODE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
MICROSOFT OR ITS LICENSORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THE SOFTWARE CODE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""
import repackage
repackage.add("../../azure-enterprise-scale-ml/esml/common/")
repackage.add("../../2_A_aml_pipeline/4_inference/batch/M12/your_code/")
import azureml.core
from azureml.core.authentication import AzureCliAuthentication
from esml import ESMLProject
from baselayer_azure_ml_pipeline import ESMLPipelineFactory, esml_pipeline_types

# region(collapsed) Only needed for USAGE INSTRUCTIONS at the end
from azureml.core.dataset import Dataset
from azureml.core import Experiment
from azureml.pipeline.core import PipelineRun
# endregion Only needed for USAGE INSTRUCTIONS at the end

print("SDK Version:", azureml.core.VERSION)

p = ESMLProject.get_project_from_env_command_line()
p.inference_mode = True
p.active_model = 12 # Y=11, price=12
p.describe()

# Get workspace
cli_auth = AzureCliAuthentication() 
ws = p.get_workspace_from_config(cli_auth) # Reads the current environment (dev,test, prod)config.json | Use CLI auth if MLOps
p.init(ws) # Automapping from datalake to Azure ML datasets, prints status
print("Environment:")
print(p.dev_test_prod,ws.name)

print("FEATURE ENGINEERING - Bronze 2 Gold - working with Azure ML Datasets with Bronze, Silver, Gold concept")

## BUILD IN_2_GOLD_SCORING

### CREATE - IN_2_GOLD
p_factory = ESMLPipelineFactory(p)
p_factory.create_dataset_scripts_from_template(overwrite_if_exists=False) 
batch_pipeline = p_factory.create_batch_pipeline(esml_pipeline_types.IN_2_GOLD) # Prepare data for training: Either with AutoMLStep or ManualMLStep

### RUN pipeline - Fire & Forget....just to see if it has errors or not? 
pipeline_run = p_factory.execute_pipeline(batch_pipeline)
pipeline_run.wait_for_completion(show_output=False)

#region(collapsed) - USAGE print out
print("Pipeline OK - lets publish this, to get an endpoint to use...from Azure Datafactory or via REST from external system")
published_pipeline, endpoint = p_factory.publish_pipeline(batch_pipeline) # "_4" is optional    to create a NEW pipeline with 0 history, not ADD version to existing pipe & endpoint

print("")
print("USAGE INSTRUCTION 1: Azure Datafactory: Below needed for PIPELINE activity to be called (Pipeline OR Endpoint. Choose the latter") 
print ("- Endpoint ID")
print("Endpoint ID:  {}".format(endpoint.id))
print("Endpoint Name:  {}".format(endpoint.name))
print("Experiment name:  {}".format(p_factory.experiment_name))

print("")

print("USAGE INSTRUCTION 2: Azure Datafactory: 2 parameters is needed to be set to call PIPELINE activity in ESML template ADF-pipeline")
print("")
print("esml_inference_model_version=0 ")
print(" - 0 means use latest registered model version, but you can pick whatever version in the DROPDOWN in Azure data factory you want")
print("esml_scoring_folder_date='2021-06-08 15:35:01.243860'")
print(" - DateTime in UTC format. Example: For daily scoring 'datetime.datetime.now()'")

print("")
print("USAGE INSTRUCTION 3")

# 1st you need a "Post scoring" activity, to get metadata of "scored_gold_path" from "last_gold_run.csv"
ds1 = Dataset.get_by_name(workspace = p.ws, name =  p.dataset_gold_scored_runinfo_name_azure)
run_id = ds1.to_pandas_dataframe().iloc[0]["pipeline_run_id"] # ['pipeline_run_id', 'scored_gold_path', 'date_in_parameter', 'date_at_pipeline_run','model_version'])
scored_gold_path = ds1.to_pandas_dataframe().iloc[0]["scored_gold_path"]

print("Read this meta-dataset from ADF: {}/last_gold_run.csv".format(p.path_inference_gold_scored_runinfo))
print("- To get the column 'scored_gold_path' which points to the scored-data:")
print("{}*.parquet".format(scored_gold_path))

# endregion

