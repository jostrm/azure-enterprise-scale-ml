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
import os
sys.path.insert(0, "../../azure-enterprise-scale-ml/esml/common/")
import azureml.core
#from azureml.core.authentication import AzureCliAuthentication
from azureml.core.authentication import ServicePrincipalAuthentication
import argparse
from esml import ESMLProject
from baselayer_azure_ml_pipeline import esml_pipeline_types
from baselayer_azure_ml_pipeline import ESMLPipelineFactory

advanced_mode = False # ADVANCDE MODE (DatabricksSteps also) + Manual ML (or AutoML if defined in Databricks notebook)
use_automl = True # SIMPLE MODE + AutoMLStep (if True)Manual ML Step (if False)

if advanced_mode:
    sys.path.insert(0, "../../azure-enterprise-scale-ml/")
    from esmlrt.interfaces.iESMLPipelineStepMap import IESMLPipelineStepMap
    sys.path.insert(0, "../../pipelines/M11/your_code/") # Advanced Mode. TODO 4 you - edit M11 in path below
    from ESMLPipelineStepMap import ESMLPipelineStepMap

print("SDK Version:", azureml.core.VERSION)

# IN PARAMETERS
esml_date_utc = '1000-01-01 10:35:01.243860' # In parameter: You can override what training data to use. 
esml_model_number = 11

p,esml_date_utc,esml_model_number,esml_model_version_int = ESMLProject.get_project_from_env_command_line() # Alt A)
if(p is None): # Alt B) Just for DEMO purpose..its never None
    p = ESMLProject() #  B)= Reads from CONFIG instead - To control this, use GIT-branching and  .gitignore on "active_dev_test_prod.json" for each environment

ws = p.ws
print(ws.name, ws.resource_group, ws.location, ws.subscription_id, sep="\n")
print("Project number: {}".format(p.project_folder_name))
print("Model number: {} , esml_date_utc: {}".format(esml_model_number, esml_date_utc))

p.inference_mode = False
p.active_model = int(esml_model_number)

p_factory = ESMLPipelineFactory(p)
p_factory.batch_pipeline_parameters[0].default_value = 0 # Will override active_in_folder.json.model.version = 0 meaning that ESML will find LATEST PROMOTED, and not use a specific Model.version.
p_factory.batch_pipeline_parameters[1].default_value = esml_date_utc # overrides ESMLProject.date_scoring_folder.
p_factory.describe()

## Optional - Advanced mode: If DatabricksSteps in pipeline
if(advanced_mode):
    map = ESMLPipelineStepMap()
    p_factory.use_advanced_compute_settings(map)
    print ("Building pipeline - ADVANCED MODE (Mixed compute: Databricks/Spark, AML CPU, GPU)")
    print (" - Needs Databricks snapshot folder with ESML Databricks notebook templates + ESMLPipelineStepMap with your defined mappings.")
    batch_pipeline = p_factory.create_batch_pipeline(esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL) # Training: Databricks notebooks
else:
    ## BUILD
    print ("Building pipeline - SIMPLE MODE")
    if(use_automl):
        batch_pipeline = p_factory.create_batch_pipeline(esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML) # Training: AutoMLStep or ManualMLStep
    else:
        batch_pipeline = p_factory.create_batch_pipeline(esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL) # Training: AutoMLStep or ManualMLStep

## RUN training
print ("Running pipeline (estimated time: 10-XXX min)")
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
print(published_pipeline.id)