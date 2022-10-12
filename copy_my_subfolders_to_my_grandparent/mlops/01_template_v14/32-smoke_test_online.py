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
#from azureml.core.authentication import AzureCliAuthentication
from azureml.core.authentication import ServicePrincipalAuthentication
import argparse
from esml import ESMLProject
from baselayer_azure_ml_pipeline import esml_pipeline_types
from baselayer_azure_ml_pipeline import ESMLPipelineFactory
print("SDK Version:", azureml.core.VERSION)

p,scoring_date,model_number = ESMLProject.get_project_from_env_command_line() # self-aware about its config sources
p.describe()

p.inference_mode = True # We want "INFERENCE" mode, when calling AKS cluster
p.connect_to_lake() # Connect to lake...to be able to also SAVE SCORING

print("Environment:")
print(p.dev_test_prod,p.ws.name)

# TEST webservice!
X_test, y_test, tags = p.get_gold_validate_Xy() # Get the X_test data |  ESML knows the SPLIT and LABEL already (due to training)
print(tags)

#inference_config, model, best_run = p.get_active_model_inference_config(ws) # Get Model to call other pecific MODEL version, than latest |

caller_user_id = '81965d9c-40ca-4e47-9723-5a608a32a0e4' # Optional: Connect scoring to a caller/user | globally for all rows
df = p.call_webservice(p.ws, X_test,caller_user_id, False) # Call and save results to version-folder | Auto-fetch key, model_version from keyvault | #  (p.ws, X_test,caller_user_id, False, model.version)
print(df.head())
