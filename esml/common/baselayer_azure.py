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
from azure.keyvault.secrets import SecretClient
from azure.identity import ClientSecretCredential
from azure.storage.filedatalake import DataLakeServiceClient

"""
COMMON - Keyvault access
"""
class AzureBase(object):

    @staticmethod
    def get_external_keyvault(ws,sp_id_key, sp_secret_key, tenant_key,external_keyvault_url):
        keyvault = ws.get_default_keyvault()
        tenantId = keyvault.get_secret(name=tenant_key)
        credential = ClientSecretCredential(tenantId, keyvault.get_secret(name=sp_id_key), keyvault.get_secret(name=sp_secret_key))
        client = SecretClient(external_keyvault_url, credential)    
        return client, tenantId

        
    
    # GEN 2 https://docs.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-directory-file-acl-python

    @staticmethod
    def initialize_storage_account_ad(storage_account_name, client_id, client_secret, tenant_id):
        try:  
            global service_client
            credential = ClientSecretCredential(tenant_id, client_id, client_secret)

            service_client = DataLakeServiceClient(account_url="{}://{}.dfs.core.windows.net".format(
                "https", storage_account_name), credential=credential)
            return service_client
        except Exception as e:
            print(e)

    @staticmethod
    def upload_file_to_directory_bulk(service_client_in,filesystem,target_file_name, local_file_fullpath, bronze_silver_gold_target_path,overwrite=True):
        try:

            file_system_client = service_client_in.get_file_system_client(file_system=filesystem)
            directory_client = file_system_client.get_directory_client(bronze_silver_gold_target_path)
            file_client = directory_client.get_file_client(target_file_name)
            local_file = open(local_file_fullpath,'rb')  # b = Binary needs to be added - otherwise "char errror"
            file_contents = local_file.read()
            file_client.upload_data(file_contents, overwrite=overwrite)
        except Exception as e:
            print(e)
    
    @staticmethod
    def upload_file_to_directory(service_client_in,filesystem,target_file_name, local_file_fullpath, bronze_silver_gold_target_path,overwrite=True):
        try:
            file_system_client = service_client_in.get_file_system_client(file_system=filesystem)
            directory_client = file_system_client.get_directory_client(bronze_silver_gold_target_path)
            file_client = directory_client.create_file(target_file_name)
            local_file = open(local_file_fullpath,'rb') # b = Binary needs to be added
            file_contents = local_file.read()
            file_client.append_data(data=file_contents, offset=0, length=len(file_contents))
            file_client.flush_data(len(file_contents))

        except Exception as e:
            print(e)
