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
print("SDK Version:", azureml.core.VERSION)

p,esml_date_utc,esml_model_number,esml_model_version_int = ESMLProject.get_project_from_env_command_line() # Alt A)
if(p is None): # Alt B) Just for DEMO purpose..its never None
    p = ESMLProject() #  B)= Reads from CONFIG instead - To control this, use GIT-branching and  .gitignore on "active_dev_test_prod.json" for each environment

ws = p.ws
print(ws.name, ws.resource_group, ws.location, ws.subscription_id, sep="\n")
print("Project number: {}".format(p.project_folder_name))
print("Model number (MXX): {} , esml_date_utc: {} model_version_int: {}".format(esml_model_number, esml_date_utc,str(esml_model_version_int)))
