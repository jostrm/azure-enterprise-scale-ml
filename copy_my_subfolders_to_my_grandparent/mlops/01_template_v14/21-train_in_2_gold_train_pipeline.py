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
import sys
sys.path.insert(0, "../../azure-enterprise-scale-ml/esml/common/")
import azureml.core
from azureml.core.authentication import AzureCliAuthentication
from esml import ESMLProject
from baselayer_azure_ml_pipeline import ESMLPipelineFactory, esml_pipeline_types

print("SDK Version:", azureml.core.VERSION)

# IN PARAMETERS
training_date = '1000-01-01 10:35:01.243860' # In parameter: You can override what training data to use.
model_number = 11
training_date,model_number = ESMLProject.get_date_utc_and_esml_model_number()

p = ESMLProject.get_project_from_env_command_line()
p.describe()

cli_auth = AzureCliAuthentication() 
ws = p.get_workspace_from_config(cli_auth) # Reads the current environment (dev,test, prod)config.json | Use CLI auth if MLOps
p.inference_mode = False # We want "TRAIN" mode
#p.init(ws) # Automapping from datalake to Azure ML datasets, prints status
p.active_model = model_number
p_factory = ESMLPipelineFactory(p)

print("FEATURE ENGINEERING - Bronze 2 Gold - working with Azure ML Datasets with Bronze, Silver, Gold concept")
print("TRAIN with AutoML")
print("COMPARE: Calculate testset-scoring, and compare INNER and OUTER LOOP MLOps, with ESML")

## Read IN parameter, what data to train on
p_factory.batch_pipeline_parameters[1].default_value = training_date # overrides ESMLProject.date_scoring_folder.
p_factory.describe()

## BUILD
batch_pipeline = p_factory.create_batch_pipeline(esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML) # Training: AutoMLStep or ManualMLStep

## RUN training
pipeline_run = p_factory.execute_pipeline(batch_pipeline)
pipeline_run.wait_for_completion(show_output=False)

# PUBLISH
published_pipeline, endpoint = p_factory.publish_pipeline(batch_pipeline,"_1")

print("2) Below needed for Azure Data factory PIPELINE activity (Pipeline OR Endpoint. Choose the latter") 
print ("- Endpoint ID")
print("Endpoint ID:  {}".format(endpoint.id))
print("Endpoint Name:  {}".format(endpoint.name))
print("Experiment name:  {}".format(p_factory.experiment_name))

print("In AZURE DATA FACTORY - This is the ID you need, if using PRIVATE LINK, private Azure ML workspace.")
print("-You need TRAINING PIPELINE id, not pipeline ENDPOINT ID ( since cannot be chosen in Azure data factory if private Azure ML)")
published_pipeline.id

