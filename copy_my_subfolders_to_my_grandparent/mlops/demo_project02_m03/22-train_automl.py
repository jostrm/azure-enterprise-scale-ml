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
import azureml.core
from azureml.train.automl import AutoMLConfig
from azureml.core.authentication import AzureCliAuthentication
from esml import ESMLProject
from baselayer_azure_ml import AutoMLFactory, azure_metric_regression,azure_metric_classification

print("SDK Version:", azureml.core.VERSION)

p = ESMLProject.get_project_from_env_command_line() # self-aware about its config sources
p.describe()

cli_auth = AzureCliAuthentication()
ws = p.get_workspace_from_config(cli_auth) # Reads the current environment (dev,test, prod)config.json | Use CLI auth if MLOps
p.init(ws) # Automapping from datalake to Azure ML datasets, prints status

# TRAIN MODEL
automl_performance_config = p.get_automl_performance_config() # 1)Get config
aml_compute = p.get_training_aml_compute(ws) # 2)Get compute, for active environment

label = "Y"
train_6, validate_set_2, test_set_2 = p.split_gold_3(0.6,label) # 3) Auto register in Azure (M03_GOLD_TRAIN | M03_GOLD_VALIDATE | M03_GOLD_TEST) 
automl_config = AutoMLConfig(task = 'regression', # 4) 
                            primary_metric = azure_metric_regression.MAE, #Note: !MAPE 
                            experiment_exit_score = '0.208', # DEMO purpose
                            compute_target = aml_compute,
                            training_data = p.GoldTrain, 
                            label_column_name = label,
                            **automl_performance_config
                        )
train_as_pipeline = False
best_run, fitted_model, experiment = None, None, None # Consistent return values from both AutoML ALTERNATIVES

if (train_as_pipeline == True):
    print("train_as_pipeline")
    best_run, fitted_model, experiment = AutoMLFactory(p).train_pipeline(automl_config) #) 5 Train model
else: 
    print("train_as_run")
    best_run, fitted_model, experiment = AutoMLFactory(p).train_as_run(automl_config)