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
sys.path.insert(0, "../../azure-enterprise-scale-ml/")
from esmlrt.interfaces.iESMLController import IESMLController
#sys.path.insert(0, "../../azure-enterprise-scale-ml/esml/common/")
from esml.common import ESMLProject
import azureml.core
import argparse
print("SDK Version:", azureml.core.VERSION)

p,scoring_date,model_number = ESMLProject.get_project_from_env_command_line() # self-aware about its config sources
p.describe()
p.inference_mode = False # We want "TRAIN" mode when deploying to AKS

print("Environment:")
print(p.dev_test_prod,p.ws.name)
print("Project number: {}".format(p.project_folder_name))
print("Model number: {} , esml_date_utc: {}".format(model_number, scoring_date))

print("DEPLOY model on to a PRIVATE AKS cluster / endpoint...")
inference_config, model, best_run = IESMLController.get_best_model_inference_config(p.ws, p.model_folder_name, p.ModelAlias)
service,api_uri, kv_aks_api_secret= p.deploy_model_as_private_aks_online_endpoint(model,inference_config,overwrite_endpoint=True)

print("Finished!")
