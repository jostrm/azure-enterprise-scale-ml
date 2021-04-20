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
from azureml.core.authentication import AzureCliAuthentication
from esml import ESMLProject
from baselayer_azure_ml import AutoMLFactory

print("SDK Version:", azureml.core.VERSION)

p = ESMLProject.get_project_from_env_command_line() # self-aware about its config sources
p.describe()

cli_auth = AzureCliAuthentication()
ws = p.get_workspace_from_config(cli_auth) # Reads the current environment (dev,test, prod)config.json | Use CLI auth if MLOps
p.init(ws) # Automapping from datalake to Azure ML datasets, prints status

target_env = "dev" # if not set, NEXT environment will be the TARGET automatically
print("Example: If new model scores better in DEV, we can promote this to TEST")

promote, m1_name, r1_id, m2_name, r2_run_id = AutoMLFactory(p).compare_scoring_current_vs_new_model(target_env)

print("Promote model?  {}".format(promote))
print("New Model: {} in environment {}".format(m1_name, p.dev_test_prod))
print("Existing Model: {} in environment {}".format(m2_name,target_env))

if (promote and p.dev_test_prod == target_env):# Can only register a model in same workspace (test->test) - need to retrain if going from dev->test
    AutoMLFactory(p).register_active_model(target_env)
elif (promote):# Can only register a model in same workspace as of now in ESML
    AutoMLFactory(p).register_active_model(p.dev_test_prod)
