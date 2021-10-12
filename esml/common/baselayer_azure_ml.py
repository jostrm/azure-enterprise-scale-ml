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
import os
import json
import datetime
from re import M
import time
from types import TracebackType
import uuid

#pipeline & read model inference
import pickle
from azureml.core.webservice.webservice import Webservice
from azureml.pipeline.core import PipelineData, TrainingOutput
from azureml.pipeline.core import Pipeline
from azureml.pipeline.steps import AutoMLStep
from azureml.pipeline.core import PipelineRun
from azureml.core.runconfig import RunConfiguration
from azureml.widgets import RunDetails

#Compute Train & batch scoring
from azureml.core.compute import ComputeTarget
from azureml.core.compute import AmlCompute
from azureml.core.compute_target import ComputeTargetException
from azureml.telemetry import UserErrorException

#Compute - online AKS webservice
from azureml.core.webservice import AksWebservice
from azureml.core.compute import AksCompute
from azureml.core.model import InferenceConfig, Model
from azureml.core.webservice import AksEndpoint
#from azureml.exceptions import WebserviceNotFound

# Aks call
import requests
import ast
import ssl
import pandas as pd
        
class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


# https://pymotw.com/3/abc/
import abc
from azureml.train.automl import AutoMLConfig
class AutoMLTrainBase(metaclass=abc.ABCMeta):
    _name = ""
    _project = None
    def __init__(self,exp_name, esml_project):
        self._name = exp_name
        self._project = esml_project

    @abc.abstractmethod
    def split_train_test_and_return_label(self, Gold):
        """Retrieve data from the input source and return an object.
        """
        pass
    @abc.abstractmethod
    def train_model(self, aml_compute,gold_train, AutoMLConfig):
        pass

"""
COMMON - Azure ML compute etc
"""
#class ComputeFactory(metaclass=Singleton):
class ComputeFactory():
   
    ws = None
    config = None
    aks_config = None
    dev_test_prod = "dev"

    # TRAIN - AML defaults
    aml_cluster_name = None
    vm_size = "STANDARD_D3_V2"
    vm_prio = "dedicated"
    vm_maxnodes=4
    min_nodes = 0
    idle_seconds_before_scaledown = 120

    # INFERENCE - Online
    aks_config = None
    aks_name = None
    aks_service_name = None
    image_name = None
    aks_api_url = None
    kv_aks_api_secret = None
    kv_aks_model_version = None
    #AKS - autoscale
    aks_dev_test = True
    cluster_purpose = "DevTest" # 1 node. FastProd=3 nodes default
    autoscale_enabled = False

    vnet_resourcegroup_name="MSFT-WEU-EAP_CMN_AI-DEV-RG"
    vnet_name = "msft-weu-dev-cmnai-vnet"
    subnet_name = "msft-weu-dev-cmnai-sn-aml"
    project = None

    def __init__(self,project,ws,dev_test_prod, override_enterprise_settings_with_model_specific=False,projNr="000", modelNr="00"):
        self.ws = ws
        self.project = project
        self.LoadConfiguration(project, dev_test_prod,override_enterprise_settings_with_model_specific,projNr,modelNr)

    def LoadConfiguration(self, project,dev_test_prod, override_enterprise_settings_with_model_specific=False,projNr="000", modelNr="00"):
        old_loc = os.getcwd()
        try:
            if(dev_test_prod != "dev" and dev_test_prod != "test" and dev_test_prod != "prod"):
                raise ValueError("dev_test_prod needs to be either: 'dev','test', or 'prod' - but it is={}".format(dev_test_prod))
            
            self.dev_test_prod = dev_test_prod
            os.chdir(os.path.dirname(__file__))

            user_settings = ""
            if(project.demo_mode == False):
                user_settings = "../../"

            start_path = "enterprise_specific/dev_test_prod_defaults"
            if (override_enterprise_settings_with_model_specific):
                #print(".....")
                print("Note: OVERRIDING enterprise performance settings with project specifics. (to change, set flag in 'dev_test_prod_settings.json' -> override_enterprise_settings_with_model_specific=False)")
                start_path = "project_specific/model/dev_test_prod_override"
            else:
                print("Note: USING enterprise performance settings. (This can be overridden in 'dev_test_prod_settings.json' -> override_enterprise_settings_with_model_specific=True")

            if(self.dev_test_prod == "dev"): 
                with open("{}../settings/{}/train/aml_compute_dev.json".format(user_settings,start_path)) as f:
                    self.config = json.load(f)
                with open("{}../settings/{}/online/aks_config_dev.json".format(user_settings,start_path)) as f:
                    self.aks_config = json.load(f)
            if(self.dev_test_prod == "test"): 
                with open("{}../settings/{}/train/aml_compute_test.json".format(user_settings,start_path)) as f:
                    self.config = json.load(f)
                with open("{}../settings/{}/online/aks_config_test.json".format(user_settings,start_path)) as f:
                    self.aks_config = json.load(f)
            if(self.dev_test_prod == "prod"): 
                with open("{}../settings/{}/train/aml_compute_prod.json".format(user_settings,start_path)) as f:
                    self.config = json.load(f)
                with open("{}../settings/{}/online/aks_config_prod.json".format(user_settings,start_path)) as f:
                   self.aks_config = json.load(f)

            self.parseTrainConfig(self.config, projNr,modelNr)
            self.parseAKSConfig(self.aks_config,projNr,modelNr)
        except Exception as e:
            raise Exception("ComputeFactory.LoadConfiguration - could not open .json config files: aml_compute_x.json") from e
        finally: 
            os.chdir(old_loc) # Change back to working location...
     
    def parseAKSConfig(self, config, projNr,modelNr):
        self.aks_config = config
        self.aks_name = config['aks_name'].format(projNr)
        self.aks_service_name = config['aks_service_name'].format(projNr,modelNr)
        self.image_name = config['image_name'].format(projNr,modelNr)

        self.aks_api_url = config['aks_api_url'].format(projNr,modelNr)
        self.kv_aks_api_secret = config['kv_aks_api_secret'].format(projNr,modelNr)
        self.kv_aks_model_version = config['kv_aks_model_version'].format(projNr,modelNr)
        self.aks_endpoint_ab = config['aks_endpoint_ab'].format(projNr,modelNr)  # esmldevp{02}m{01}aksendpoint

        self.aks_dev_test= self.aks_config['aks_dev_test']
        
        if(self.aks_dev_test == True):
            self.cluster_purpose = AksCompute.ClusterPurpose.DEV_TEST
            self.autoscale_enabled = False
        else:
            self.cluster_purpose = AksCompute.ClusterPurpose.FAST_PROD
            self.autoscale_enabled = config['autoscale_enabled']

        if((len(config['aks_name_override']) > 0)):  # ('aks_name_override' in config)
            self.aks_name = config['aks_name_override']
  
    def parseTrainConfig(self, config,projNr, modelNr):
        self.aml_cluster_name = config['aml_cluster_name'].format(projNr,modelNr) # max 16 chars [prj002-m03-dev,prj002-m03-test,prj002-m03-prod]
        self.vm_size = config['aml_training_vm_size']
        self.vm_prio = config['vm_priority']
        self.vm_maxnodes = int(config['aml_training_nodes'])
        self.min_nodes = int(config['min_nodes'])

        if(self.min_nodes > 0):
            print("WARNING - This cluster will not autoscale down, since you override 'min_nodes' to"\
                "be greater than 0. Contact your IT / Core team to validate that it is OK with cost of {} min_nodes".format(self.min_nodes))

        self.idle_seconds_before_scaledown = int(config['idle_seconds_before_scaledown'])


    @staticmethod
    def allowSelfSignedHttps(allowed):
        # bypass the server certificate verification on client side
        if allowed and not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None):
            ssl._create_default_https_context = ssl._create_unverified_context

# -> AKS TEST CALL
    @staticmethod    
    def call_webservice_static(pandas_dataframe, api_uri,api_key,firstRowOnly=True):
        ComputeFactory.allowSelfSignedHttps(True)

        if(firstRowOnly==True):
            rows = pandas_dataframe.iloc[[0]]
        else:
            rows = pandas_dataframe
        X_test_json_works = json.dumps({'data': rows.to_dict(orient='records')}) #WORKS:  to_dict(orient='records') -> accesses the NumPy array df.values
        print ("Relying on you having the keys...")

        headers = {'Content-Type':'application/json', 'Authorization': 'Bearer ' + api_key}
        resp = requests.post(api_uri, X_test_json_works , headers=headers)
        #res_dict = json.loads(resp.text)
        #res_dict_ast = ast.literal_eval(res_dict)
        #return pd.read_json(res_dict) # to pandas
        
        return resp # json

    def call_webservice(self, X_test, firstRowOnly=True,pandas_result=True, api_uri=None,api_key="auto from keyvault"):
        ComputeFactory.allowSelfSignedHttps(True) # this line is needed if you use self-signed certificate in your scoring service.

        if(firstRowOnly==True):
            rows = X_test.iloc[[0]]
        else:
            rows = X_test

        X_test_json_works = json.dumps({'data': rows.to_dict(orient='records')}) #WORKS:  to_dict(orient='records') -> accesses the NumPy array df.values
        model_version = 1
        if(api_uri is None): # Fetch keys automatically
            print ("Note: Fetching keys automatically via workspace keyvault.")  #, {} and {} ".format(self.aks_api_url,self.kv_aks_api_secret))
            keyvault = self.ws.get_default_keyvault()
            api_uri = keyvault.get_secret(name=self.aks_api_url)
            api_key = keyvault.get_secret(name=self.kv_aks_api_secret)
            try:
                model_version = keyvault.get_secret(name=self.kv_aks_model_version)
            except:
                pass
        else: # Assume, own credentials
            print ("Relying on you having the keys ...")

        headers = {'Content-Type':'application/json', 'Authorization': 'Bearer ' + api_key}
        resp = requests.post(api_uri, X_test_json_works , headers=headers)
        if(resp.text == "Not found"):
            raise UserErrorException("No webservice found at {}.\n"\
                "Make sure you have deployd the model to a webservice in Azure ML Studio, and that the API URL in keyvault matches this webservice.".format(api_uri))

        res_dict = json.loads(resp.text)
        
        
        if (pandas_result):
            df_results = pd.read_json(res_dict) # to pandas
        else:
            #res_dict_ast = ast.literal_eval(res_dict)
            #print("result", res_dict_ast['result'])
            df_results = res_dict

        return df_results,int(model_version) #, res_dict_ast

# //END - AKS TEST CALL  

    # Meompry optimizes in DEV, since 1 node only: Standard_DS13-2_v2 (8 cores, 56GB RAM, 112GB storage)
    # DNS. Networking. Self-scaler in non DEV_TEST (Azure ML router (azureml-fe) is deployed into the AKS cluster)
    #https://docs.microsoft.com/en-us/azure/machine-learning/how-to-deploy-azure-kubernetes-service?tabs=python
    #https://github.com/Azure/MachineLearningNotebooks/blob/bda592a236eaf2dbc54b394e1fa1b539e0297908/how-to-use-azureml/deployment/production-deploy-to-aks/production-deploy-to-aks.ipynb

    def deploy_online_on_aks(self,esml_project,model,inference_config, target_dev_test_prod,deployment_config, override_enterprise_settings_with_model_specific, projNr="000", modelNr="00"):
        self.LoadConfiguration(esml_project,target_dev_test_prod,override_enterprise_settings_with_model_specific, projNr, modelNr)

        target_workspace = esml_project.get_other_workspace(target_dev_test_prod) # 1) get WS
        aks_target = self._get_aks_cluster(target_workspace)  # 2) Provision CLUSTER if not exists, with PROVISION config

        aks_deploy_config = None
        if (deployment_config is not None):
            print("Using injected deployment_config, instead of reading directly from settings folder")
            aks_deploy_config = deployment_config
        else: # Fetch from internal .json
            model_tag = esml_project.model_folder_name
            aks_deploy_config = self._get_deploy_config(target_dev_test_prod,model_tag) #3) Get DEPLOY CONFIG, for webservice
        
        # DEPLOY model  (If AKS DevTest, ensure cores and memory to handle this deployment. Note that memory is also used by things such as dependencies and AML component)
        service = Model.deploy(target_workspace, self.aks_service_name, [model], inference_config, aks_deploy_config, aks_target, True)
        service.wait_for_deployment(show_output = True)
        print(service.state)
        print(service.get_logs())

        # 4) Retrieve the scoring URI, and API key - Save "aks_url" and "api_key" to keyvault in WORKSPACE for environment

        api_key, api_key_secondary = service.get_keys()
        api_uri = service.scoring_uri
        
        years_3_from_now = datetime.datetime.now() - datetime.timedelta(days=3*365)
        expires_on_utc_date = years_3_from_now.date()

        #https://github.com/Azure/azure-sdk-for-python/tree/master/sdk/keyvault/azure-keyvault-secrets
        keyvault = target_workspace.get_default_keyvault() # TARGET workspace
        keyvault.set_secret(name=self.aks_api_url, value = api_uri), # expires_on=expires_on_utc_date,content_type="esml generated.AKS URL")
        keyvault.set_secret(name=self.kv_aks_api_secret, value = api_key) #,expires_on=expires_on_utc_date, content_type="esml generated.AKS secret") # GET -> ws.get_default_keyvault().get_secret(name="secret-name")
        keyvault.set_secret(name=self.kv_aks_model_version, value = model.version) #,expires_on=expires_on_utc_date, content_type="esml generated. Model verision used in AKS webservice.")

        print("Deployed AKS Webservice: {} \nWebservice Uri: {} "\
            "\nWebservice API_Secret are stored in keyvault with name: {} "\
            "\nWebservice API_URI are stored in keyvault with name: {} "\
            "\nWebservice Swagger Uri: {}".format(service.name, service.scoring_uri, self.kv_aks_api_secret,self.aks_api_url, service.swagger_uri))
        return service,api_uri, self.kv_aks_api_secret

    def get_deploy_config(self,esml_project,override_enterprise_settings_with_model_specific, projNr, modelNr):
        self.LoadConfiguration(esml_project,esml_project.dev_test_prod,override_enterprise_settings_with_model_specific, projNr, modelNr)
        return self._get_deploy_config(esml_project.dev_test_prod,esml_project.model_folder_name)

    def _get_deploy_config(self, target_dev_test_prod, model_tag = "model tags"):
        aks_deploy_config = None

        aks_tags = {'esml_model':model_tag, "esml_environment": target_dev_test_prod}

        #if(target_dev_test_prod != "dev"): # auto scale
            #print("Note: Since target environment is not DEV, it is OK to have autoscaling settings")
        if(self.aks_config["aks_dev_test"] == False and self.autoscale_enabled == True): # auto scale
            print("Note: Since aks_dev_test=False in config for environment {}, it is OK to have autoscaling settings".format(target_dev_test_prod))

            aks_deploy_config = AksWebservice.deploy_configuration(
                autoscale_enabled=self.autoscale_enabled, 
                autoscale_target_utilization=self.aks_config['autoscale_target_utilization'], #default=70%
                autoscale_min_replicas=self.aks_config['autoscale_min_replicas'], #default=1
                autoscale_max_replicas=self.aks_config['autoscale_max_replicas'], # default=10
                autoscale_refresh_seconds = self.aks_config['autoscale_refresh_seconds'], #default=1 second
                token_auth_enabled=self.aks_config['token_auth_enabled'], 
                auth_enabled=self.aks_config['key_auth_enabled'],
                cpu_cores=self.aks_config['aks_cpu_cores'],  # to allocate for the web service. Can be a decimal. Defaults to 0.1. ( 6 cores - can deploy 6 services with 1 core)
                memory_gb=self.aks_config['aks_memory_gb'],  # Defaults to 0.5. Example: 1GB file.csv can be 10GM in RAM as a Pandas dataframe, hence 20GB is recommended.
                tags=aks_tags, # eval(self.aks_config['tags']),
                description=self.aks_config['description'],
                enable_app_insights=self.aks_config['enable_app_insights'],
                collect_model_data=self.aks_config['collect_model_data'] 
                #,scoring_timeout_ms # default: 60 000ms = 1minut
                #,replica_max_concurrent_requests #  default=1, maximum concurrent  per node to allow for the web service.  my_dict.get(some_key, 0)
                ,scoring_timeout_ms=self.aks_config.get('scoring_timeout_ms',300000), # default: 60 000ms = 1min, ESML default = 5min, 300 000ms(is max)
                max_request_wait_time=self.aks_config.get('max_request_wait_time',5000), # default: 500ms = 0.5s,  ESML default = 10s
                timeout_seconds=self.aks_config.get('timeout_seconds',1) # default: 1 second
                )
        else:
            print("Note: Autoscale_enabled=False, or since aks_dev_test=True in config, autoscaling is automatically shut off, e.g. overridden in config (since not supported) for environment {}".format(target_dev_test_prod))

            #token_auth_enabled=eval(config['token_auth_enabled']),  https://www.programiz.com/python-programming/methods/built-in/eval
            #auth_enabled=eval(config['key_auth_enabled']),
            # Warnings when using eval() - Inject code in LINUX! using eval(input()), the user may issue commands to change file or even delete all the files using the command: os.system('rm -rf *').
            aks_deploy_config = AksWebservice.deploy_configuration(
                 num_replicas = self.aks_config['num_replicas'], # If this parameter is not set then the autoscaler is enabled by default.
                 autoscale_enabled=self.autoscale_enabled, # If TRUE enable autoscaling for the web service. Defaults to TRUE if num_replicas = NULL.
                 token_auth_enabled=self.aks_config['token_auth_enabled'], 
                 auth_enabled=self.aks_config['key_auth_enabled'],
                 cpu_cores=self.aks_config['aks_cpu_cores'],   # 6 cores - can deploy 6 webservices with 1 core
                 memory_gb=self.aks_config['aks_memory_gb'],  # 10 GB ( 1GB .csv file is 20GB pandas RAM)
                 tags=aks_tags, # eval(self.aks_config['tags']),
                 description=self.aks_config['description'],
                 enable_app_insights=self.aks_config['enable_app_insights'],
                 collect_model_data=self.aks_config['collect_model_data']
                 #, namespace #  Kubernetes namespace in which to deploy the web service: up to 63 lowercase alphanumeric ('a'-'z', '0'-'9') and hyphen ('-') 
                ,scoring_timeout_ms=self.aks_config.get('scoring_timeout_ms',300000), # default: 60 000ms = 1min, 300 000ms(is max) = 5min 
                max_request_wait_time=self.aks_config.get('max_request_wait_time',10000), # default: 500ms = 0.5s, ESML default=10s
                timeout_seconds=self.aks_config.get('timeout_seconds',1) # default: 1 second
                 )
        return aks_deploy_config


    def _get_aks_cluster(self,target_workspace):
        aks_target = None
        first_time_bug_string = "ServicePrincipalNotFound"
        try:

            if (self.aks_name not in target_workspace.compute_targets):
                #aks_target = AksCompute(target_workspace,self.aks_name)
                
                print('Creating AKS cluster {} in aks-mode DevTest={}'.format(self.aks_name ,self.aks_dev_test))

                prov_config = AksCompute.provisioning_configuration(
                            cluster_purpose=self.cluster_purpose, # AksCompute.ClusterPurpose.DEV_TEST
                            vm_size=self.aks_config['aks_vm_size'],
                            agent_count=self.aks_config['aks_agent_count'],
                            location=self.aks_config['location']
                        )
                rg_name, vnet_name, subnet_name = self.project.vNetForActiveEnvironment()
                if((len(subnet_name) > 0)):
                    prov_config.vnet_resourcegroup_name = rg_name
                    prov_config.vnet_name = vnet_name
                    prov_config.subnet_name = subnet_name
                    prov_config.service_cidr = self.aks_config['service_cidr']
                    prov_config.dns_service_ip = self.aks_config['dns_service_ip']
                    prov_config.docker_bridge_cidr = self.aks_config['docker_bridge_cidr']
                
                prov_config.enable_ssl(leaf_domain_label=self.aks_config['leaf_domain_label'])
                aks_target = ComputeTarget.create(workspace=target_workspace, name=self.aks_name, provisioning_configuration=prov_config)
                aks_target.wait_for_completion(show_output=True)
                print(aks_target.provisioning_state)
                print(aks_target.provisioning_errors)
            else: # Get existing
                aks_target = ComputeTarget(target_workspace, self.aks_name)
                print('Found existing cluster, {}, using it.'.format(self.aks_name))

            if aks_target.get_status() != "Succeeded":
                aks_target.wait_for_completion(show_output=True)
            return aks_target
        except Exception as e:
            if (first_time_bug_string in e.message):
                custom_help = "Looks like this is the 1st AKS-cluster in this workpsace. There is a 1st time BUG, see errormessage about {}."\
                    "\n - Solution: Create a dummy cluster via Azure portal UI, then this works".format(first_time_bug_string)
                raise Exception(custom_help) from e


    def _get_aks_cluster_error(self,target_workspace):
        aks_target = None
        try:
            aks_target = ComputeTarget(target_workspace, self.aks_name)
            print('Found existing cluster, {}, using it.'.format(self.aks_name))
        except Exception: #ComputeTargetException:
            #aks_target = AksCompute(target_workspace,self.aks_service_name)
            prov_config = AksCompute.provisioning_configuration(
                    cluster_purpose=self.cluster_purpose, # AksCompute.ClusterPurpose.DEV_TEST
                    vm_size=self.aks_config['aks_vm_size'],
                    agent_count=self.aks_config['aks_agent_count'],
                    location=self.aks_config['location']
                )
            
            prov_config.enable_ssl(leaf_domain_label=self.aks_config['leaf_domain_label'])
            aks_target = ComputeTarget.create(workspace=target_workspace, name=self.aks_name, provisioning_configuration=prov_config)
            aks_target.wait_for_completion(show_output=True)
            print(aks_target.provisioning_state)
            print(aks_target.provisioning_errors)

        if aks_target.get_status() != "Succeeded":
            aks_target.wait_for_completion(show_output=True)
        return aks_target
        
    def _aks_create_ab_endpoints(self, target_workspace, model_a, model_b, inference_config,aks_target, traffic_percentile_A = 70, traffic_percentile_B=30):
        # define the endpoint and version name 
        endpoint_name = self.aks_config['aks_endpoint_ab'] + "ab"  #"mynewendpoint" 
        version_name= "version_"+str(traffic_percentile_A)
        # create the deployment config and define the scoring traffic percentile for the first deployment

        # initial endpoint version to handle 60% of the traffic. Since this is the first endpoint, it's also the default version. 
        # IF we don't have any other versions for the other 40% of traffic, it is routed to the default as well. 
        # Until other versions that take a percentage of traffic are deployed, this one effectively receives 100% of the traffic.
        endpoint_deployment_config = AksEndpoint.deploy_configuration(cpu_cores = 0.1, memory_gb = 0.2,
                                                                    enable_app_insights = True,
                                                                    tags = {'sckitlearn':'demo'},
                                                                    description = "testing versions",
                                                                    version_name = version_name,
                                                                    traffic_percentile = traffic_percentile_A)
        # deploy the model and endpoint
        endpoint = Model.deploy(target_workspace, endpoint_name, [model_a], inference_config, endpoint_deployment_config, aks_target)
        endpoint.wait_for_deployment(True) # Wait for he process to complete
        print("endpoint verison A {}".format(endpoint))

        if (traffic_percentile_B > 0 and model_b is not None): # add another model deployment to the same endpoint as above
            version_name_add = "version_"+str(traffic_percentile_B)
            endpoint.create_version(version_name = version_name_add,
                                inference_config=inference_config,
                                models=[model_b],
                                tags = {'modelVersion':'b'},
                                description = "my second version",
                                traffic_percentile = traffic_percentile_B)

            endpoint.wait_for_deployment(True)
            print("endpoint verison B {}".format(endpoint))
        return endpoint

    # TODO - not finished
    def _update_ab_endpoint(self,endpoint, old_traffic_percentile, new_traffic_percentile):
        AksEndpoint
        old_version_name= "version_"+str(old_traffic_percentile)
        new_version_name= "version_"+str(new_traffic_percentile)

        # update the version's scoring traffic percentage and if it is a default or control type
        endpoint.update_version(version_name=endpoint.versions[old_version_name].name,
                            description="my second version update",
                            traffic_percentile=new_traffic_percentile, # 40
                            is_default=True,
                            is_control_version_type=True)
        # Wait for the process to complete before deleting
        endpoint.wait_for_deployment(True)
        # delete a version in an endpoint
        #endpoint.delete_version(version_name=old_version_name)

    def _aks_auto_scale(self, test_prod, autoscale_target_utilization=70):
        if(test_prod == "dev"):
            raise UserErrorException("You should not use auto-scaling in DEV. You should use AKS DEV_TEST flag to run cheap in 1 node")

        autoscale_min_replicas=self.aks_config['autoscale_min_replicas'], # ESML default=1
        autoscale_max_replicas=self.aks_config['autoscale_max_replicas'], # ESML default=4
        aks_config = AksWebservice.deploy_configuration(autoscale_enabled=True, 
                                                    autoscale_target_utilization=autoscale_target_utilization,
                                                    autoscale_min_replicas=autoscale_min_replicas, # Azure default: 1
                                                    autoscale_max_replicas=autoscale_max_replicas) # Azure default: 10


    def get_secret(self, p, target_environment,override_enterprise_settings_with_model_specific=False, projNr="000", modelNr="00"):
        self.LoadConfiguration(p,target_environment,override_enterprise_settings_with_model_specific, projNr, modelNr)
        return p.get_other_workspace(target_environment).get_default_keyvault().get_secret(name=self.kv_aks_api_secret)

    def get_secret_from_run(self, azure_ml_run, target_environment,override_enterprise_settings_with_model_specific=False, projNr="000", modelNr="00"):
        self.LoadConfiguration(self.project,target_environment,override_enterprise_settings_with_model_specific, projNr, modelNr)
        #Note: To get secret in Keyvault during "batch run. The method gives you a simple shortcut: the Run instance is aware of its Workspace and Keyvault,
        #https://github.com/Azure/MachineLearningNotebooks/blob/master/how-to-use-azureml/manage-azureml-service/authentication-in-azureml/authentication-in-azureml.ipynb
        return azure_ml_run.get_secret(name=self.kv_aks_api_secret) #azure_ml_run = Run.get_context()

    def get_training_aml_compute(self,dev_test_prod,override_enterprise_settings_with_model_specific=False, projNr="000", modelNr="00", create_cluster_with_suffix=None):
        self.LoadConfiguration(self.project,dev_test_prod,override_enterprise_settings_with_model_specific, projNr, modelNr)

        try:
            name = None
            if (create_cluster_with_suffix is not None):
                name = self.aml_cluster_name + "-"+create_cluster_with_suffix
                cpu_cluster = AmlCompute(workspace=self.ws, name=name)
            else:
                name = self.aml_cluster_name
                cpu_cluster = AmlCompute(workspace=self.ws, name=self.aml_cluster_name)
            print('Found existing cluster {} for project and environment, using it.'.format(name))
        except ComputeTargetException:
            print('Creating new cluster - ' + name)

            rg_name, vnet_name, subnet_name = self.project.vNetForActiveEnvironment()

            if((len(subnet_name) > 0)):
                compute_config = AmlCompute.provisioning_configuration(vm_size=self.vm_size,
                                                                        vm_priority=self.vm_prio,  # 'dedicated', 'lowpriority'
                                                                        min_nodes=self.min_nodes,
                                                                        max_nodes=self.vm_maxnodes,
                                                                        vnet_resourcegroup_name=rg_name,
                                                                        vnet_name=vnet_name,
                                                                        subnet_name=subnet_name)
            else:
                compute_config = AmlCompute.provisioning_configuration(vm_size=self.vm_size,
                                                                    vm_priority=self.vm_prio,  # 'dedicated', 'lowpriority'
                                                                    min_nodes=self.min_nodes,
                                                                    max_nodes=self.vm_maxnodes)

            cpu_cluster = ComputeTarget.create(self.ws, name, compute_config)

        # Can poll for a minimum number of nodes and for a specific timeout.
        # If min_node_count=None is provided, it will use the scale settings for the cluster instead
        cpu_cluster.wait_for_completion(show_output=True, min_node_count=None, timeout_in_minutes=30)
        return cpu_cluster, name

# DELETE

    def delete_aks_endpoint(self,ws):
        try:
            aks_ws = AksWebservice(workspace=ws, name=self.aks_service_name)
            print('Found existing AksWebservice endpoint, deleting it, since overwrite=True')
            aks_ws.delete()
            time.sleep(8) # To get memory/CPU back...
        except Exception:
            pass

    def delete_aml_compute_by_custom_name(self,ws, name):
        try:
            cpu_cluster = AmlCompute(workspace=ws, name=name)
            print('Found existing cluster, deleting it.')
            cpu_cluster.delete()
            time.sleep(8) # To get memory/CPU back...
        except ComputeTargetException:
            print('Not found cluster - {}'.format(name))

    def delete_aml_compute(self,ws):
        if(self.aml_cluster_name is None):
            raise Exception("You need to LoadConfiguration(), before deleting, or use delete_aml_compute_by_custom_name()")
        try:
            cpu_cluster = AmlCompute(workspace=ws, name=self.aml_cluster_name)
            print('Found existing cluster, deleting it.')
            cpu_cluster.delete() 
        except ComputeTargetException:
            print('Not found cluster - {}'.format(self.aml_cluster_name))
#PUBLIC END

#OLD
#Logic in PipelineFactory, lazy load PipelineFactory

    def batch_score(self, datefolder_or_uniquesubfolder, file_or_filetype="*.parquet" ,firstRowOnly=False):
        # 1) creates a batch-scoring pipeline "if not exists"
            #self.get_or_create_aml_batch_pipeline()
        # 2a) scores data, and saves it to lake directly VS
        # Fire and forget VS return "sample" of scoring
        #return df_result,model_version 
        pass

    def get_or_create_aml_batch_pipeline(self,esml_project,model,inference_config, target_dev_test_prod,override_enterprise_settings_with_model_specific=False, projNr="000", modelNr="00"):
        # 1) Get suitable compute: 
        self.get_batch_compute(self)
        
        # 2) Lazy-load PipelineFactory
        pass # TODO: return pipeline

    def get_batch_compute(self):
        pass
#Logic in  PipelineFactory

#OLD

# START - PIPELINES - SCORING & TRAINING & INFERENCE
from azureml.core import Run
from azureml.core import Workspace
from azureml.core.model import Model as AMLModel
class ESMLRunHelper(metaclass=Singleton):
    @staticmethod
    def get_current_workspace() -> Workspace:
        run = Run.get_context(allow_offline=False)
        experiment = run.experiment
        return experiment.workspace

    @staticmethod
    def get_model_offline(p, model_version: int = None) -> AMLModel:
        model = None
        if model_version is not None:
            # TODO(tcare): Finding a specific version currently expects exceptions
            # to propagate in the case we can't find the model. This call may
            # result in a WebserviceException that may or may not be due to the
            # model not existing.
            model = AMLModel(
                p.ws,
                name=model_name,
                version=model_version,
                tags=tags)
        else:
            models = AMLModel.list(
                aml_workspace, name=model_name, tags=tags, latest=True)
            if len(models) == 1:
                model = models[0]
            elif len(models) > 1:
                raise Exception("Expected only one model")


    @staticmethod
    def get_model(
        model_name: str,
        model_version: int = None,  # If none, return latest model
        tag_name: str = None,
        tag_value: str = None,
        aml_workspace: Workspace = None) -> AMLModel:
        """
        Retrieves and returns a model from the workspace by its name
        and (optional) tag.
        Parameters:
        aml_workspace (Workspace): aml.core Workspace that the model lives.
        model_name (str): name of the model we are looking for
        (optional) model_version (str): model version. Latest if not provided.
        (optional) tag (str): the tag value & name the model was registered under.
        Return:
        A single aml model from the workspace that matches the name and tag, or
        None.
        """
        if aml_workspace is None:
            print("No workspace defined - using current experiment workspace.")
            aml_workspace = ESMLRunHelper().get_current_workspace()

        tags = None
        if tag_name is not None or tag_value is not None:
            # Both a name and value must be specified to use tags.
            if tag_name is None or tag_value is None:
                raise ValueError(
                    "model_tag_name and model_tag_value should both be supplied"
                    + "or excluded"  # NOQA: E501
                )
            tags = [[tag_name, tag_value]]

        model = None
        if model_version is not None:
            # TODO(tcare): Finding a specific version currently expects exceptions
            # to propagate in the case we can't find the model. This call may
            # result in a WebserviceException that may or may not be due to the
            # model not existing.
            model = AMLModel(
                aml_workspace,
                name=model_name,
                version=model_version,
                tags=tags)
        else:
            models = AMLModel.list(
                aml_workspace, name=model_name, tags=tags, latest=True)
            if len(models) == 1:
                model = models[0]
            elif len(models) > 1:
                raise Exception("Expected only one model")

        return model

import sys
import os
sys.path.append(os.path.abspath("."))  # NOQA: E402
from baselayer_ml import get_4_regression_metrics,get_7_classification_metrics
class ESMLTestScoringFactory(metaclass=Singleton):
    project = None

    def __init__(self,project):
        self.project = project

    def get_test_scoring_4_regression(self, label,run=None, fitted_model=None):
        p = self.project
        if(run is not None):
            source_best_run = run
            model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
            model = Model(p.ws, model_name)
            fitted_model = fitted_model
        else:
            experiment, model,source_best_run, best_run,fitted_model = p.get_best_model_and_run_via_experiment_name() # Looks at Azure

        test_set_pd =  p.GoldTest.to_pandas_dataframe()
        rmse, r2, mean_abs_percent_error,mae, spearman_correlation,plt = get_4_regression_metrics(test_set_pd, label,fitted_model)

        p.GoldTest.tags["RMSE"] = "{:.6f}".format(rmse)
        p.GoldTest.tags["R2"] = "{:.6f}".format(r2)
        p.GoldTest.tags["MAPE"] = "{:.6f}".format(mean_abs_percent_error)
        p.GoldTest.tags["Spearman_Correlation"] = "{:.6f}".format(spearman_correlation)
        ds = p.GoldTest.add_tags(tags = p.GoldTest.tags)

        #model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
        #model = Model(p.ws, model_name)
        model.tags["test_set_RMSE"] = "{:.6f}".format(rmse)
        model.tags["test_set_R2"] = "{:.6f}".format(r2)
        model.tags["test_set_MAPE"] = "{:.6f}".format(mean_abs_percent_error)
        model.tags["test_set_Spearman_Correlation"] = "{:.6f}".format(spearman_correlation)

        model.add_tags(tags = model.tags)
        
        #source_best_run.tag("ESML TEST_SET Scoring", "Yes, including plot: Actual VS Predicted")
        source_best_run.log_image("ESML_GOLD_TestSet_AcutalPredicted", plot=plt)

        return rmse, r2, mean_abs_percent_error,mae,spearman_correlation,plt
    
    def get_test_scoring_7_classification(self, label,multiclass=None,positive_label=None, run=None, fitted_model=None):
        p = self.project

        if(run is not None):
            source_best_run = run
            model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
            model = Model(p.ws, model_name)
            fitted_model = fitted_model
        else:
            experiment, model,source_best_run, best_run,fitted_model = p.get_best_model_and_run_via_experiment_name() # Looks at Azure
            #source_best_run, fitted_model, experiment = p.get_best_model(p.ws)  # Old, stale ...since local agent metadata of "last run"

        test_set_pd =  p.GoldTest.to_pandas_dataframe()
        auc,accuracy,f1, precision,recall,matrix,matthews, plt = get_7_classification_metrics(test_set_pd, label,fitted_model,multiclass,positive_label)

        # 1) Log on the TEST_SET used
        if(auc is not None):
            p.GoldTest.tags["ROC_AUC"] = "{:.6f}".format(auc)

        p.GoldTest.tags["Accuracy"] = "{:.6f}".format(accuracy)

        f1_str = None
        prec_str = None
        rec_str = None
        if(multiclass is not None):
            f1_str = list(map('{:.6f}'.format,f1))
            prec_str = list(map('{:.6f}'.format,precision))
            rec_str = list(map('{:.6f}'.format,recall))
        else:
            f1_str = "{:.6f}".format(f1)
            prec_str = "{:.6f}".format(precision)
            rec_str = "{:.6f}".format(recall)

        if(f1_str is None):
            f1_str = ""
        if(prec_str is None):
            prec_str = ""
        if(rec_str is None):
            rec_str = ""
        p.GoldTest.tags["F1_Score"] = f1_str
        p.GoldTest.tags["Precision"] = prec_str
        p.GoldTest.tags["Recall"] = rec_str
        p.GoldTest.tags["Matthews_Correlation"] = "{:.6f}".format(matthews)
        p.GoldTest.tags["Confusion_Matrix"] = str(matrix)

        #2) Also, log on MODEL
        #model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
        #model = Model(p.ws, model_name)
        if(auc is not None):
            model.tags["test_set_ROC_AUC"] =  "{:.6f}".format(auc)
        model.tags["test_set_Accuracy"] =  "{:.6f}".format(accuracy)
        model.tags["test_set_F1_Score"] =  f1_str
        model.tags["test_set_Precision"] =  prec_str
        model.tags["test_set_Recall"] =  rec_str
        model.tags["test_set_Matthews_Correlation"] =  "{:.6f}".format(matthews)
        model.tags["test_set_CM"] =  str(matrix)

        model.add_tags(tags = model.tags)
        ds = p.GoldTest.add_tags(tags = p.GoldTest.tags)
        

        # 3) Also, log on RUN
        #source_best_run.tag("ESML TEST_SET Scoring", "Yes, including plot: ROC")
        if(plt is not None):
            source_best_run.log_image("ESML_GOLD_TestSet_ROC", plot=plt)

        return auc,accuracy, f1, precision,recall,matrix,matthews, plt

from azureml.core import Experiment
from azureml.core import Model
from azureml.train.automl.run import AutoMLRun
class AutoMLFactory(metaclass=Singleton):
   
    ws = None
    config = None
    dev_test_prod = "dev"

    enable_voting_ensemble = False
    enable_stack_ensemble = False
    model_explainability = False
    experiment_timeout_hours = 1
    iteration_timeout_minutes = 61
    n_cross_validations = 2
    enable_early_stopping = True
    allowed_models = []
    blocked_models = []
    run_id = -1
    model_name_automl = "AutoML_Generated_Name"
    active_model_config = None
    model_settings = None
    debug_always_promote_model = False
    max_cores_per_iteration = -1

    #Pipeline Run
    metrics_output_name = 'metrics_output'
    best_model_output_name = 'best_model_output'
    project = None

    def __init__(self,project):
        self.project = project

    def LoadConfiguration(self, dev_test_prod, override_enterprise_settings_with_model_specific):
        old_loc = os.getcwd()
        
        try:
            if(dev_test_prod != "dev" and dev_test_prod != "test" and dev_test_prod != "prod"):
                raise ValueError("dev_test_prod needs to be either: 'dev','test', or 'prod' - but it is={}".format(dev_test_prod))
            self.dev_test_prod = dev_test_prod

            os.chdir(os.path.dirname(__file__))

            user_settings = "../../"
            start_path = "enterprise_specific/dev_test_prod_defaults"
            if (override_enterprise_settings_with_model_specific):
                start_path = "project_specific/model/dev_test_prod_override"
            automl_active_path = "project_specific/model/dev_test_prod"

            if(self.dev_test_prod == "dev"): 
                with open("{}../settings/{}/train/automl/automl_dev.json".format(user_settings,start_path)) as f:
                    self.config = json.load(f)
                with open("{}../settings/{}/train/automl/active/automl_active_model_dev.json".format(user_settings,automl_active_path)) as f:
                    self.active_model_config = json.load(f)
            if(self.dev_test_prod == "test"): 
                with open("{}../settings/{}/train/automl/automl_test.json".format(user_settings,start_path)) as f:
                    self.config = json.load(f)
                with open("{}../settings/{}/train/automl/active/automl_active_model_test.json".format(user_settings,automl_active_path)) as f:
                    self.active_model_config = json.load(f)
            if(self.dev_test_prod == "prod"): 
                with open("{}../settings/{}/train/automl/automl_prod.json".format(user_settings,start_path)) as f:
                    self.config = json.load(f)
                with open("{}../settings/{}/train/automl/active/automl_active_model_prod.json".format(user_settings,automl_active_path)) as f:
                    self.active_model_config = json.load(f)

            # Model specific settings - for all environments
            with open("{}../settings/project_specific/model/model_settings.json".format(user_settings,automl_active_path)) as f:
                self.model_settings = json.load(f)
            
            self.parseActiveModel(self.active_model_config)
            self.parseConfig(self.config)
        except Exception as e:
            raise ValueError("AutoMLFactory.LoadConfiguration - could not open .json config files: automl_env.json") from e
        finally: 
            os.chdir(old_loc) # Change back working location...

    def parseActiveModel(self, config):
        self.run_id = config['run_id']
        self.model_name_automl = config['model_name_automl']

    def parseConfig(self, config):
        print("Loading AutoML config settings from: {}".format(self.dev_test_prod))

        self.enable_voting_ensemble = config['enable_voting_ensemble'] #true-> True
        self.enable_stack_ensemble = config['enable_stack_ensemble'] #true-> True
        self.model_explainability = config['model_explainability'] #true-> True
        self.experiment_timeout_hours = config['experiment_timeout_hours'] # float
        self.iteration_timeout_minutes = int(config['iteration_timeout_minutes'])
        self.n_cross_validations = int(config['n_cross_validations']) 
        self.enable_early_stopping = config['enable_early_stopping'] #true-> True
        self.iterations = config['iterations'] # 1000 is default
        self.allowed_models = config['allowed_models']
        self.blocked_models = config['blocked_models']
        # just used internally in this Class
        self.debug_always_promote_model = config['debug_always_promote_model']
        self.automl_log_location = config['debug_log']
        self.automl_path = config['path']

        if('max_cores_per_iteration' in config):
            self.max_cores_per_iteration = int(config['max_cores_per_iteration'])
        else:
            self.max_cores_per_iteration = -1

    def get_automl_performance_config(self,dev_test_prod, use_black_or_allow_list_from_config=True, override_enterprise_settings_with_model_specific=False):

        self.LoadConfiguration(dev_test_prod,override_enterprise_settings_with_model_specific)
        automl_performance_settings = {
            'enable_voting_ensemble':self.enable_voting_ensemble 
            ,'enable_stack_ensemble':self.enable_stack_ensemble 
            ,'model_explainability': self.model_explainability  # Default=True
            ,'experiment_timeout_hours':self.experiment_timeout_hours  # Default=6 days. Example: "0.25 representing 15 minutes"
            ,'iteration_timeout_minutes':self.iteration_timeout_minutes # Default=one month=43200 minutes
            ,'n_cross_validations':self.n_cross_validations  #Minimum=2
            ,'enable_early_stopping':  self.enable_early_stopping  #Default=False....early? No early stopping for first 20 iterations (landmarks). looks every 10th iteration.
            ,'iterations': self.iterations
            ,'max_cores_per_iteration': self.max_cores_per_iteration # Equal to 1, the default. if equal to -1, which means to use all the possible cores per iteration per child-run.
        }

        if(use_black_or_allow_list_from_config): #LOGIC: Allowed - Blocked
            #['LightGBM','ElasticNet','GradientBoosting','XGBoostRegressor','ExtremeRandomTrees','LassoLars','RandomForest','ElasticNet', 'AutoArima', 'RandomForest','DecisionTree','Prophet']
            if(len(self.allowed_models) > 0):
                automl_performance_settings["allowed_models"] = self.allowed_models
            if(len(self.blocked_models) > 0):
                automl_performance_settings["blocked_models"] = self.blocked_models

        # debug_log = 'automl_errors.log',
        # path = ".",
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            automl_log_location_abs = "." # os.path.abspath(self.automl_path) # ./logs/
            automl_performance_settings["path"] = automl_log_location_abs
        except Exception as e:
            raise e
        finally:
            os.chdir(old_loc)

        automl_performance_settings["debug_log"] = self.automl_log_location # self.automl_log_location

        return automl_performance_settings

    def create_automl_step(self,datastore,experiment_name,automl_config, allow_reuse=True):
        out_metrics_data = PipelineData(name='metrics_data',
                            datastore=datastore,
                            pipeline_output_name=self.metrics_output_name,
                            training_output=TrainingOutput(type='Metrics'))
        out_model_data = PipelineData(name='model_data',
                                datastore=datastore,
                                pipeline_output_name=self.best_model_output_name,
                                training_output=TrainingOutput(type='Model'))
        step = AutoMLStep(
            name=experiment_name+"_train",
            automl_config=automl_config,
            outputs=[out_metrics_data, out_model_data],
            allow_reuse=allow_reuse)

        return step

    # new: https://github.com/Azure/MachineLearningNotebooks/blob/master/how-to-use-azureml/machine-learning-pipelines/intro-to-pipelines/aml-pipelines-with-automated-machine-learning-step.ipynb
    #obsolete: https://docs.microsoft.com/en-us/azure/machine-learning/how-to-use-automlstep-in-pipelines
    #https://github.com/Azure/MachineLearningNotebooks/blob/master/how-to-use-azureml/machine-learning-pipelines/intro-to-pipelines/aml-pipelines-with-automated-machine-learning-step.ipynb
    def train_pipeline(self,automl_config,allow_reuse=True):
        p = self.project
        experiment_name= p.experiment_name
        target_dev_test_prod = p.dev_test_prod
        print("Experiment name: {}".format(experiment_name))
        print("Azure ML Studio Workspace: {}".format(p.ws.name))
        print("Start training pipeline...")

        # ....Lets see if a manual RunConfiguration will solve the WEIRDNESS - no stopping?
        #aml_run_config = RunConfiguration()
        #aml_run_config.target = p.get_training_aml_compute(p.ws)
        #automl_config.run_configuration  = aml_run_config

        # ..Nope...save effect. 

        pipeline = Pipeline(description="{}".format(experiment_name),workspace=p.ws,
            steps=[self.create_automl_step(p.Lakestore,experiment_name, automl_config, allow_reuse)])

        # https://docs.microsoft.com/en-us/python/api/azureml-pipeline-core/azureml.pipeline.core.pipeline.pipeline?view=azure-ml-py
        experiment = Experiment(p.ws, experiment_name)
        pipeline_run = experiment.submit(pipeline, show_output=True)
        #RunDetails(pipeline_run).show()
        status = pipeline_run.wait_for_completion()

        if(status == "Running"):
            print("Weird - pipeline is still in Running state...even though finished. Manually cancelling Run now.")
            pipeline_run.cancel()

        best_model_output, fitted_model = self.get_pipeline_output_and_best_model(pipeline_run)
         #Save RUN to .json
        source_model_name = pipeline_run.properties['model_name']
        print("AutoML Model name: {}".format(source_model_name))

        self.write_run_config(pipeline_run.experiment.name, source_model_name,pipeline_run.id, target_dev_test_prod)

        return best_model_output, fitted_model, experiment

    def train_as_run(self, automl_config, test_set = None):

        # Typically, you will not create a RunConfiguration object directly but get one from a method that returns it, such as the submit method of the Experiment class.

        #aml_run_config = RunConfiguration()
        #aml_run_config.target = p.get_training_aml_compute(p.ws)
        #automl_config.run_configuration  = aml_run_config
        p = self.project

        return self.train(self.project.ws,automl_config,p.experiment_name,p.dev_test_prod, p)

    def train(self,ws,automl_config,experiment_name,dev_test_prod, p, test_set=None):

        print("Experiment name: {}".format(experiment_name))
        print("Azure ML Studio Workspace: {}".format(ws.name))
        print("Start training run...")

        label = automl_config.user_settings['label_column_name']
        is_classification = True
        is_regression = False

        if (p.multi_output is not None): # Multi output support.
            if (len(p.multi_output) > 0):
                name = experiment_name +"_"+ label
            else:
                name = experiment_name
            experiment = Experiment(ws, name)
        else:
            experiment = Experiment(ws, experiment_name)

        remote_run = experiment.submit(automl_config, show_output = True)

        remote_run.wait_for_completion()
        best_run, fitted_model = remote_run.get_output()
        print(best_run)
        print(fitted_model)

        if(test_set is not None):
            if(is_classification):
                auc,accuracy,f1, precision,recall,matrix,matthews, plt = ESMLTestScoringFactory(p).get_test_scoring_7_classification(label,best_run,fitted_model)
                best_run.log(name="test_set_AUC", value = auc)
                best_run.log(name="test_set_Accuracy", value = accuracy)
                best_run.log(name="test_set_F1_Score", value = f1)
                best_run.log(name="test_set_Precision", value = precision)
                best_run.log(name="test_set_Recall", value = recall)
                best_run.log(name="test_set_Matthews_Correlation", value = matthews)
                #best_run.log(name="test_set CM matrix", value = matrix)
                best_run.log_image("ESML_GOLD_TestSet_ROC",  plot=plt)
            if(is_regression):
                rmse, r2, mean_abs_percent_error,mae,spearman_corr,plt = ESMLTestScoringFactory(p).get_test_scoring_4_regression(label,best_run,fitted_model)
                best_run.log(name="test_set_RMSE", value = rmse)
                best_run.log(name="test_set_R2", value = r2)
                best_run.log(name="test_set_MAPE", value = mean_abs_percent_error)
                best_run.log(name="test_set_MAE", value = mae)
                best_run.log(name="test_set_Spearman_Correlation", value = spearman_corr)

                best_run.log_image("ESML_GOLD_TestSet_ActualPredicted", plot=plt)

        #Save RUN to .json
        source_model_name = best_run.properties['model_name']
        print("AutoML Model name: {}".format(source_model_name))
        self.write_run_config(remote_run.experiment.name, source_model_name,remote_run.id, dev_test_prod)

        return best_run, fitted_model,experiment

    def get_latest_model_from_experiment_name(self,env_workspace, exp_name):
        try:
            my_tags = {"experiment_name": exp_name} # works
            model_list = Model.list(workspace=env_workspace, latest=False, tags=my_tags)

            production_model = next(
                filter(
                    lambda x: x.created_time == max(
                        model.created_time for model in model_list),
                    model_list,
                )
            )

            production_model_run_id = production_model.tags.get("run_id")
            return production_model, production_model_run_id
        except Exception as e:
            return None, None

    def get_latest_model(self, env_workspace):
        try:
            # Get most recently registered model, we assume that is the model in production. Download this model and compare it with the recently trained model by running test with same data set.
            model_list = Model.list(workspace=env_workspace, latest=True)
            production_model = next(
                filter(
                    lambda x: x.created_time == max(
                        model.created_time for model in model_list),
                    model_list,
                )
            )
            production_model_run_id = production_model.tags.get("run_id")
            
            #print(production_model.experiment_name) #CAnnot rely on thism, only RECENT models, these properties was not available in Azure ML SDK until 1.X
            #print(production_model.run_id) # Use tags instad, 

            return production_model, production_model_run_id
        except Exception as e:
            print("This is the first model to be trained, thus nothing to evaluate for now")
            return None, None
    
    def get_active_model_inference_config(self,target_workspace,target_env, override_enterprise_settings_with_model_specific):
        self.LoadConfiguration(target_env, override_enterprise_settings_with_model_specific)

        #target_run, experiment = self._get_active_model_run_and_experiment(target_workspace,target_env, override_enterprise_settings_with_model_specific)
        #target_best_run, fitted_model = target_run.get_output()

        target_experiment, target_model,target_run, target_best_run,fitted_model = self.project.get_best_model_and_run_via_experiment_name_and_ws(target_workspace)
       
        model_class = None
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            script_file_local = "../../../settings/project_specific/model/dev_test_prod/train/automl/scoring_file_{}.py".format(self.dev_test_prod)
            target_best_run.download_file('outputs/scoring_file_v_1_0_0.py', script_file_local)

            script_file_abs = os.path.abspath(script_file_local)
            inference_config = InferenceConfig(environment=target_best_run.get_environment(), entry_script=script_file_abs)

            #model_name = target_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
            #model_class = Model(target_workspace, model_name)
            model_class = target_model
        except Exception as e:
            raise e
        finally:
             os.chdir(old_loc)

        return inference_config, model_class, target_best_run
    
    # https://github.com/Azure/MachineLearningNotebooks/blob/master/how-to-use-azureml/machine-learning-pipelines/intro-to-pipelines/aml-pipelines-with-automated-machine-learning-step.ipynb
    def get_pipeline_output_and_model(self,target_workspace,target_env, override_enterprise_settings_with_model_specific):
        pipeline_run, experiment = self._get_active_model_run_and_experiment(target_workspace,target_env, override_enterprise_settings_with_model_specific, True)
        return self.get_best_model_from_pipeline_run(pipeline_run)

    def get_pipeline_output_and_best_model(self,pipeline_run):
        best_model = None # Retrieve best model from Pipeline Run
        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            best_model_output = pipeline_run.get_pipeline_output(self.best_model_output_name) # returns PortDataReference, to ge best_pipeline
            num_file_downloaded = best_model_output.download('./temp_data/', show_progress=True) # download to TEMP

            with open(best_model_output._path_on_datastore, "rb" ) as f:   
                best_model = pickle.load(f)

            #2) Return BEST model, 
            steps = best_model.steps
            print("best_model_pipeline.steps", steps)
        finally:
             os.chdir(old_loc)
        
        return best_model_output, best_model # best_model_pipeline.predict(X_test)

    def get_next_environment(p):
        if(p.dev_test_prod == "dev"):
            return "test"
        elif (p.dev_test_prod == "test"):
            return "prod"
        elif(p.dev_test_prod == "prod"):
            return "prod"
    
    def get_task_type(self, target_run):
        my_dictionary = target_run.get_properties()
        j_str = my_dictionary['AMLSettingsJsonString']
        j_dic = json.loads(j_str)
        task_type = j_dic['task_type']
        return task_type

    def get_run_and_task_type(self, run_id=None, ws=None):
        p = self.project
        automl_run_id = "run_id_to_set"
        if(run_id is not None):
            automl_run_id = run_id    
        else: # read from config
            self.LoadConfiguration(p.dev_test_prod, p.override_enterprise_settings_with_model_specific)
            automl_run_id = self.active_model_config["run_id"]

        if (not automl_run_id):
            print("Run ID is not a Guid, or not set -> No modelrun in history, you need to provide run_id as parameter")
            return None

        if(ws is not None): # to support fetching from DEV or TEST or PROD, without flipping flag, p.dev_test_prod="test"
            env_exp = Experiment(workspace=ws, name=p.experiment_name)
        else:
            env_exp = Experiment(workspace=p.ws, name=p.experiment_name)
        remote_run = AutoMLRun(experiment=env_exp, run_id=automl_run_id) # format: "AutoML_1cc989cd-81d3-4693-b5a9-b2ae9188302f"
        return remote_run, self.get_task_type(remote_run)

    def get_best_model(self, p,pipeline_run=False):
        remote_run, experiment = self._get_active_model_run_and_experiment(p.ws, p.dev_test_prod, p.override_enterprise_settings_with_model_specific, pipeline_run)
        best_run, source_fitted_model = remote_run.get_output()
        return best_run, source_fitted_model,experiment

    '''
     if (target_environment == "dev" & p.dev_test_prod = "dev") -> compare againt  stage "dev" -> Should be same if no difference is made
     if (target_environment== "test" & p.dev_test_prod = "dev") -> compare againt next stage "test" -> should always be better in TEST, since longer traininng run
     if (target_environment == "prod" & & p.dev_test_prod = "test") -> compare "test" againt next stage "prod"  -> TEST and PROD might be same
     if (target_environment == "prod" & & p.dev_test_prod = "dev") -> Exception! Should always use corret staging cycle. Not "jump over"
    '''
    def compare_scoring_current_vs_new_model(self, target_environment = None):
        self.LoadConfiguration(self.project.dev_test_prod, self.project.override_enterprise_settings_with_model_specific)
        p = self.project
        source_workspace = p.ws
        target_workspace = None
        experiment_name = self.project.model_folder_name
        promote_new_model = False
        current_env = self.project.dev_test_prod
        
        if (target_environment is None): # if DEV -> then TEST
            target_environment= self.get_next_environment(p)
            #raise UserErrorException("You must set a TARGET environement. It can be same as SOURCE. 'dev' to 'dev' is OK, or 'dev' -> 'test', 'text'->'prod'")
        
        if (target_environment== "prod" and p.dev_test_prod=="test"): # target=PROD -> compare against previous models in PROD...highest level
            print ("Compare model version in TEST with latest registered in PROD subscription/workspace")
            print("")
            try:
                #p.dev_test_prod = "prod" # get settings for target
                #auth = AzureCliAuthentication()
                ##target_workspace = Workspace.get(name = p.workspace_name,subscription_id = p.subscription_id,resource_group = p.resource_group,auth=cli_auth)
                target_workspace = p.get_other_workspace(target_environment)
            finally:
                p.dev_test_prod = current_env # flip back to TEST
        elif (target_environment == "test" and p.dev_test_prod == "dev"): # target=test -> compare againt previous stage "dev"
            print ("Compare model version in DEV with latest registered in TEST subscription/workspace")
            print("")
            try:
                target_workspace = p.get_other_workspace(target_environment)
            finally:
                p.dev_test_prod = current_env # flip back to DEV
        elif (target_environment == p.dev_test_prod ): # -> compare againt previous model in same "dev" workspace
            print ("targe=source environement. Compare model version in DEV/TEST/PROD with latest registered in same DEV/TEST/PROD workspace (same workspace & subscriptiom comparison)")
            print("")
            target_workspace = source_workspace

        
        # NEW model (Not registered) - fetch from json
        new_run_id = self.active_model_config["run_id"] # Should NOT be empty, either -1 or AutoML GUID 
        new_experiment_name = self.active_model_config["experiment_name"]
        new_model_name = self.active_model_config["model_name_automl"]
        new_dev_test_prod = self.active_model_config["dev_test_prod"]

        previous_registered_model_version = self.active_model_config["registered_model_version"] # Can be -1 if never registered
 
         # SOURCE (latest registered) vs TARGET (latest registered)
        source_model_name = ""
        source_metrics = None
        source_task_type = None
        #source_best_run_id = None 

        target_model_name = ""
        target_best_run_id = None
        target_metrics = None
        target_task_type = None

        #if(source_model is None):
        if(not new_run_id):
            print("No run_id for source model. Need to train a model in environment: {}, nothing to evaluate for now. If target exists, its better than nothing.".format(target_environment))
            promote_new_model = False
            return promote_new_model,source_model_name,None,target_model_name, target_best_run_id
        else:
            try: # GET source from saved new RUN_ID
                source_exp = Experiment(workspace=source_workspace, name=experiment_name)
                source_run = AutoMLRun(experiment=source_exp, run_id=new_run_id)
                source_best_run, source_fitted_model = source_run.get_output()
                source_model_name = source_best_run.properties['model_name']
                source_task_type = self.get_task_type(source_run)
            except Exception as e1:
                 raise UserErrorException("Cannot find SOURCE AutoMLRun for model best run id {}, in environment {}. Try register model manually".format(new_run_id, p.dev_test_prod)) from e1

        try: # Compare latest SOURCE_MODEL with TARGET_MODEL
            if(target_workspace == source_workspace): # dev->dev, or test->test, or prod->prod
                 print("TARGET is in the same Azure ML Studio workspace as SOURCE, comparing with latest registered model...")
            
            #target_model, target_best_run_id = AutoMLFactory(p).get_latest_model(target_workspace)
            #target_model, target_best_run_id = AutoMLFactory(p).get_latest_model_from_experiment_name(target_workspace,experiment_name)
            target_exp, model,target_run, target_best_run,target_model = None,None,None,None,None
            try:
                target_exp, target_model,target_run, target_best_run,fitted_model = p.get_best_model_and_run_via_experiment_name_and_ws(target_workspace)
                if(target_model is not None):
                    target_best_run_id = target_model.tags["run_id"] # model.tags.get("run_id") Example: AutoML_08bb87d4-9587-4b99-b781-fe16bd13f140
                    target_model_name = target_model.tags["model_name"]
                    target_best_model_version = target_model.version

                    print("Target found (registered):")
                    print(" Target - best_run_id", target_best_run_id)
                    print(" Target - best_run_id (best run)", target_best_run.id)
                    print(" Target - model_name (from model.tag)",target_model_name)
                    #print("target - model_name (from target_best_run.properties[''model_name'])",target_best_run.properties['model_name'] )
                    print(" Target - model_version",target_best_model_version)
            except Exception as e1:
                print(e1.message)
                promote_new_model = True
                print("get_best_model_and_run_via_experiment_name_and_ws() could not EXISTING MODEL with same experiment name = No TARGET run. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
                                
            if(target_model is not None):
                print("target_best_run_id", target_best_run_id)

                if (target_best_run_id is not None):
                    #target_model_name = target_best_run.properties['model_name'] # model.name
                    target_task_type = self.get_task_type(target_run)
                else: 
                    promote_new_model = True
                    print("No TARGET run_id. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
            else:
                promote_new_model = True
                print("No TARGET MODEL. This is the first model to be trained in environment: {}, nothing to compare against -> Go ahead and register & deploy new model".format(target_environment))
        except Exception as e:
            raise e
            #raise UserErrorException("Unkown error. Cannot load TARGET AutoMLRun for model best run id {}, in environment {}. Try register model manually".format(target_best_run_id, target_environment)) from e
        
        # IF we have a target to compare with
        if (promote_new_model == False):
            promote_new_model = self.promote_model(source_best_run, target_best_run,target_best_run_id,source_task_type, target_task_type)
        # END, IF we have a target to compare with
        
        # Save NEW model (Not registered)
        self.model_name_automl = source_model_name
        if promote_new_model:
            self.write_run_config(new_experiment_name, source_model_name, new_run_id, new_dev_test_prod)
        #else:
        #    self.write_run_config(new_experiment_name, source_model_name, -1, new_dev_test_prod) 

        return promote_new_model,source_model_name,new_run_id,target_model_name, target_best_run_id

    # https://docs.microsoft.com/en-us/python/api/azureml-automl-core/azureml.automl.core.shared.constants.tasks?view=azure-ml-py
    def promote_model(self, source_best_run, target_best_run, target_best_run_id, source_task_type, target_task_type):
        if (self.debug_always_promote_model==True): # Guard
            print("OBS! 'debug_always_promote_model=TRUE' - will not perform scoring-comparison, nor look into scoring-WEIGHTs in `settings/project_specific/model/model_settings.json")
            return True
        #task_type = self.model_settings.get('task_type','regression')

        print("New trained model & cached RUN, has TASK_TYPE: {} and Best_Run_id: {}".format(source_task_type,source_best_run.id))
        print("Target model & RUN, in Azure ML Studio workspace to compare with, has TASK_TYPE: {} and Best_Run_id:{} ".format(target_task_type,target_best_run.id))

        if(target_best_run_id is None): # 1st run, 1st model...just promote
            print("This is the first model. No target to compare with, hence we will PROMOTE")
            return True

        if (source_task_type != target_task_type): 
            print("Error: Cannot compare models of different machine learning task_type: {} != {} , or target_task_type is none (promote_new_model is returned as True)".format(source_task_type,target_task_type))
            print(" - Example: Cannot compare REGRESSION with CLASSIFICATION...")
            return True
        task_type = source_task_type

        reg_map, cl_map = self.get_metric_mappings()
        promote_new_model = False

        try: 
            print("")
            print("Q: Do we have SCORING DRIFT / CONCEPT DRIFT?") 
            print("Q: Is a model trained on NEW data better? Is the one in production degraded? (not fit for the data it scores - real world changed, other CONCEPT)")
            print("A: - Lets check. Instead of DataDrift, lets look at actual SCORING on new data (or same data, other code). See if we should PROMOTE newly trained model...")
            print("")

            if(task_type == "classification"):
                print("New trained model: ")
                source_metrics = self.classification_print_metrics(source_best_run)
                print("")
                print("Target model, to compare with; ")
                target_metrics = self.classification_print_metrics(target_best_run)
                print("")
                                
                selected_metric_array = self.model_settings['classification_compare_metrics']
                lower_is_better = ["TODO_Add_LogLoss"]
                promote_new_model = self.compare_metrics(cl_map, source_metrics, target_metrics,selected_metric_array,lower_is_better)

            elif (task_type == "regression" or task_type == "forecasting"):
                print("New trained model: ")
                source_metrics = self.regression_print_metrics(source_best_run)
                print("")
                print("Target model, to compare with; ")
                target_metrics = self.regression_print_metrics(target_best_run)
                print("")

                selected_metric_array = self.model_settings['regression_compare_metrics']
                lower_is_better = ["RMSE_promote_weight", "MAPE_promote_weight","MAE_promote_weight"] # Else, HIGHER is better ["R2_promote_weight", "Spearman_promote_weight"]
                promote_new_model = self.compare_metrics(reg_map, source_metrics, target_metrics,selected_metric_array,lower_is_better)
                
            elif (task_type in ['image-classification', 'image-multi-labeling', 'image-object-detection', 'image-instance-segmentation']): 
                pass
            elif (task_type == 'text-classification-multilabel'): 
                pass
        except Exception as e3:
            promote_new_model = True
            print("Error: Cannot compare models (promote_new_model is currently=True)")
            print("Inner Exception: ", e3)
        finally: 
            return promote_new_model
            
    def compare_metrics(self, metric_map, source_metrics, target_metrics, selected_metric_array,lower_is_better):
        promote_new_model = False

        if(selected_metric_array is not None and len(selected_metric_array) > 0):
            print("Selected metrics, and weights, to be used when comparing for promotion/scoring drift")
            latest_metric = ""
            
            for m in selected_metric_array:
                latest_metric = m

                newly_trained = float(source_metrics[metric_map[m]])
                current_prod = float(target_metrics[metric_map[m]])

                #if(newly_trained == -1.0 or current_prod == -1.0): # Old model was probably another task_type (cannot compare REGRESSION with CLASSIFICATION -> Just promote..)
                #    print("!Current best model (or newly trained) is of different Machine learning task_types (cannot compare REGRESSION with CLASSIFICATION) promote_new_model is returned as True)")
                #    promote_new_model = True
                #    break

                promote_weight = float(self.model_settings.get(m,0.0))
                newly_trained_weighted = float(newly_trained - (promote_weight)) # 0.2 meaning, new trained model must be 0.2 better...to "win". AUC=0.8  0.8 - (-0.1) = 0.9

                print("Metric weight: {} is {:5.4f}".format(m,promote_weight))
                print("Metric VALUE (incl. weight) {:5.4f} (without weight:  {:5.4f})".format(newly_trained_weighted,newly_trained))

                if(m in lower_is_better):
                    if (newly_trained_weighted < current_prod):
                        promote_new_model = True
                    else:
                        promote_new_model = False
                        print (" - WORSE: NEW trained model {:.12f} is WORSE than CURRENT model: {:.12f} for metric {}".format(newly_trained_weighted,current_prod,metric_map[m]))
                        break # break loop if ANY metric is worse
                else:
                    if (newly_trained_weighted > current_prod):
                        promote_new_model = True
                    else:
                        promote_new_model = False
                        print (" - WORSE: NEW trained model {:.16f} is WORSE than CURRENT model: {:.16f} for metric {}".format(newly_trained_weighted,current_prod,metric_map[m]))
                        break # break loop if ANY metric is worse
                print("")

            if(promote_new_model == False):
                print("")
                print("Promote model = False!")
                print(" - Not promote, due to metric {}. You can adjust the WEIGHT {} in ESML settings".format(metric_map[latest_metric], latest_metric))
            else:
                print("")
                print("Promote model = True")
        return promote_new_model

    def get_metric_mappings(self):
        metric_map_regression = {
            "RMSE_promote_weight": "normalized_root_mean_squared_error",
            "R2_promote_weight": "r2_score",
            "MAPE_promote_weight": "mean_absolute_percentage_error",
            "MAE_promote_weight": "normalized_mean_absolute_error",
            "Spearman_promote_weight": "spearman_correlation"
        }

        metric_map_classification = {
            "AUC_promote_weight": "AUC_weighted",
            "Accuracy_promote_weight": "accuracy",
            "Precision_promote_weight": "precision_score_weighted",
            "Recall_promote_weight": "recall_score_weighted",
            "F1_promote_weight": "f1_score_weighted",
            "Log_loss_weight":"log_loss",
            "Matthews_promote_weight": "matthews_correlation"
        }
        return metric_map_regression, metric_map_classification

    def register_active_model_in_ws(self, target_workspace, target_env):
        self.LoadConfiguration(target_env,self.project.override_enterprise_settings_with_model_specific)
        return self._register_model(target_env,target_workspace.name, target_workspace,self.model_name_automl, target_env, self.project.GoldTrain)

    def register_active_model(self,target_env):

        p = self.project
        if(p.dev_test_prod != target_env):
            raise UserErrorException("Current ESML version can only register a model in same azure ml workspace (test->test), you need to retrain in new workspace if going from dev->test")

        self.LoadConfiguration(target_env,p.override_enterprise_settings_with_model_specific)
        
        source_env = p.dev_test_prod
        source_ws_name = p.ws.name #target_workspace.name
        if (source_env == "prod"):
            target_workspace = p.ws # Last stop. Prod->Prod
        else:
            target_workspace = p.get_other_workspace(target_env)

        return self._register_model(source_env,source_ws_name, target_workspace,self.model_name_automl, target_env, p.override_enterprise_settings_with_model_specific,p.GoldTrain)

    def _get_active_model_run_and_experiment(self, target_workspace, target_env, override_enterprise_settings_with_model_specific, pipeline_run=False):
        self.LoadConfiguration(target_env, override_enterprise_settings_with_model_specific)
        
        run_id = self.active_model_config["run_id"]
        if (not run_id):
            print("Run ID is not a Guid, or not set -> No new model to register, as TARGET model perform better")
            return None
        experiment_name = self.active_model_config["experiment_name"]
        experiment = Experiment(workspace=target_workspace, name=experiment_name)

        remote_run = None
        if(pipeline_run == True):
            remote_run = PipelineRun(experiment=experiment, run_id=run_id)
        remote_run = AutoMLRun(experiment=experiment, run_id=run_id)
        return remote_run, experiment

    def _register_model(self,source_env,source_ws_name, target_workspace,model_name, target_env, override_enterprise_settings_with_model_specific, train_dataset=None):
        remote_run, experiment = self._get_active_model_run_and_experiment(target_workspace,target_env, override_enterprise_settings_with_model_specific)
        run_id = remote_run.run_id # TODO does .run_id exists in PipelineRun? (.id) It does in a ScriptRun.
        tags = {"run_id": run_id, "model_name": model_name, "trained_in_environment": source_env, 
        "trained_in_workspace": source_ws_name, "experiment_name": experiment.name}

        #properties = {"run_id": run_id, "model_name": model_name, "trained_in_environment": source_env, 
        #"trained_in_workspace": source_ws_name, "experiment_name": experiment.name}
        
        # TypeError: register_model() got an unexpected keyword argument 'datasets'
        #model = remote_run.register_model(model_name=model_name, tags=tags, description="",datasets =[('training data',train_dataset)]) #, properties=properties) # register_model() got an unexpected keyword argument 'properties'
        model = remote_run.register_model(model_name=model_name, tags=tags, description="")
        print("model.version", model.version)

        self.write_run_config(experiment.name, model.name,remote_run.run_id, target_env, model.version)

        # Also TAG Experiemnt with model and version
        tags = {'model_name':model_name, 'best_model_version': str(model.version)}
        experiment.set_tags(tags)

        print("Model name {} is registered.".format(model.name))
        return model
    
    def write_run_config(self,experiment_name, model_name, new_run_id, dev_test_prod, registered_model_version=-1):
        self.active_model_config = {
            "experiment_name": experiment_name,
            "model_name_automl": model_name,
            "run_id": new_run_id,
            "dev_test_prod": dev_test_prod,
            "registered_model_version": registered_model_version
            }

        old_loc = os.getcwd()
        try:
            if(dev_test_prod != "dev" and dev_test_prod != "test" and dev_test_prod != "prod"):
                raise ValueError("dev_test_prod needs to be either: 'dev','test', or 'prod' - but it is={}".format(dev_test_prod))

            os.chdir(os.path.dirname(__file__))

            start_path = "project_specific/model/dev_test_prod"

            user_settings = ""
            if(self.project.demo_mode == False):
                user_settings = "../../"

            if(dev_test_prod == "dev"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_dev.json".format(user_settings,start_path), "w") as f:
                    json.dump(self.active_model_config, f)
            if(dev_test_prod == "test"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_test.json".format(user_settings,start_path), "w") as f:
                    json.dump(self.active_model_config, f)
            if(dev_test_prod == "prod"): 
                with open("{}../settings/{}/train/automl/active/automl_active_model_prod.json".format(user_settings,start_path), "w") as f:
                    json.dump(self.active_model_config, f)
            
        except Exception as e:
            raise ValueError("AutoMLFactory.write_run_config - could not write .json config file: automl_active_model_envX.json") from e
        finally: 
            os.chdir(old_loc) # Change back working location...

    def regression_print_metrics(self,best_run):
        metrics = best_run.get_metrics()

        rmse = metrics.get('normalized_root_mean_squared_error',-999.0)
        r2 = metrics.get('r2_score', -999.0)
        spearman = metrics.get('spearman_correlation', -999.0)
        mape = metrics.get('mean_absolute_percentage_error',-999.0)
        _mae = metrics.get('normalized_mean_absolute_error', -999.0)

        all_metrics = {}
        all_metrics["normalized_root_mean_squared_error"] = rmse
        all_metrics["r2_score"] = r2
        all_metrics["mean_absolute_percentage_error"] = mape
        all_metrics["normalized_mean_absolute_error"] = _mae
        all_metrics["spearman_correlation"] = spearman

        print("RMSE (normalized_root_mean_squared_error): " + str(rmse))
        print("MAPE (Mean average Percentage Error): " + str(mape))
        print("MAE (normalized_mean_absolute_error): " + str(_mae))
        print("R2 (r2_score): " + str(r2))
        print("Spearman (spearman_correlation): " + str(spearman))
        
        return all_metrics

    def classification_print_metrics(self,best_run):
        metrics = best_run.get_metrics()

        auc = metrics.get('AUC_weighted', -1.0)
        accuracy = metrics.get('AUC_weighted', -1.0)
        precision = metrics.get('precision_score_weighted', -1.0)
        precision_avg = metrics.get('average_precision_score_weighted', -1.0)
        recall = metrics.get('recall_score_weighted', -1.0)
        f1_score = metrics.get('f1_score_weighted', -1.0)
        log_loss = metrics.get('log_loss', -1.0)

        all_metrics = {}
        all_metrics["AUC_weighted"] = auc
        all_metrics["accuracy"] = accuracy
        all_metrics["precision_score_weighted"] = precision
        all_metrics["average_precision_score_weighted"] = precision_avg
        all_metrics["recall_score_weighted"] = recall
        all_metrics["f1_score_weighted"] = f1_score
        all_metrics["log_loss"] = log_loss

        print("AUC (AUC_weighted): " + str(auc))
        print("Accuracy: " + str(accuracy))
        print("Precision (precision_score_weighted): " + str(precision))
        print("Recall (recall): " + str(recall))
        print("F1 Score (1.0 is good): " + str(f1_score))
        print("Logg loss (0.0 is good): " + str(log_loss))

        return all_metrics

# Task_type - https://docs.microsoft.com/en-us/python/api/azureml-automl-core/azureml.automl.core.shared.constants.tasks?view=azure-ml-py
# AutoML Supported value(s): 'accuracy, precision_score_weighted, norm_macro_recall, AUC_weighted, average_precision_score_weighted'. 
class azure_metric_classification():
    AUC = "AUC_weighted"
    Accuracy = "accuracy"
    Precision = "precision_score_weighted"
    Precision_avg = "average_precision_score_weighted"
    Recall = "norm_macro_recall"
    #F1_score = "f1_score_weighted"
    #Log_loss = "log_loss"

# AutoML Supported value(s):  'normalized_mean_absolute_error, normalized_root_mean_squared_error, spearman_correlation, r2_score'
class azure_metric_regression():
    MAE = "normalized_mean_absolute_error"
    RMSE = "normalized_root_mean_squared_error"
    R2 = "r2_score"
    Spearman = "spearman_correlation"
    #MAPE = "mean_absolute_percentage_error"  # Not supported in AutoML training as
    #R2oob = "explained_variance"
    #Recall = "recall"