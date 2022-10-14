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
from your_custom_code import M12_In2GoldProcessor

print("SDK Version:", azureml.core.VERSION)

p = ESMLProject.get_project_from_env_command_line()
p.describe()

cli_auth = AzureCliAuthentication() 
ws = p.get_workspace_from_config(cli_auth) # Reads the current environment (dev,test, prod)config.json | Use CLI auth if MLOps
p.inference_mode = False # We want "TRAIN" mode
p.init(ws) # Automapping from datalake to Azure ML datasets, prints status

print("FEATURE ENGINEERING - Bronze 2 Gold - working with Azure ML Datasets with Bronze, Silver, Gold concept")

esml_dataset = p.DatasetByName("ds01_vw") # Get dataset
df_bronze = esml_dataset.Bronze.to_pandas_dataframe()
df1_silver = M12_In2GoldProcessor.ds01_process_in2silver(df_bronze) # df[df.mileage < 10000]
p.save_silver(esml_dataset,df1_silver) #Bronze -> Silver

esml_dataset2 = p.DatasetByName("ds02_audi") # Get AUDI
df_bronze2 = esml_dataset2.Bronze.to_pandas_dataframe()
df2_silver= M12_In2GoldProcessor.ds02_process_in2silver(df_bronze2) # df[df.mileage < 10000]
p.save_silver(esml_dataset,df2_silver) #Bronze -> Silver

esml_dataset3 = p.DatasetByName("ds03_bmw") # Get BMW
df_bronze3 = esml_dataset3.Bronze.to_pandas_dataframe()
df3_silver= M12_In2GoldProcessor.ds03_process_in2silver(df_bronze3) # df[df.mileage < 10000]
p.save_silver(esml_dataset,df3_silver) #Bronze -> Silver

merged = M12_In2GoldProcessor.merge_silvers(df1_silver,df2_silver,df3_silver)
gold = p.save_gold(merged)  #Silver -> Gold