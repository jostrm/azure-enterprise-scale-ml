import sys
import os
import tempfile
import sklearn
from azureml.core import Model
from azureml.core.resource_configuration import ResourceConfiguration

#sys.path.append(os.path.abspath(".."))  # NOQA: E402
from ..interfaces.iESMLController import IESMLController

class ESMLController(IESMLController):
    
    def __init__(self,modelCompare,testScoringFactory,esml_project_folder_name, esml_model_name, esml_model_alias, secret_name_tenant = None,secret_name_project_sp_id= None,secret_name_project_sp_secret = None):
        super().__init__(modelCompare,testScoringFactory,esml_project_folder_name,esml_model_name, esml_model_alias, secret_name_tenant,secret_name_project_sp_id,secret_name_project_sp_secret)

    def get_best_model(self, ws):
        return IESMLController.get_best_model_run_fitted_model_Dev(ws,self.experiment_name)

    def get_target_workspace(self, current_environment, current_ws, target_environment):

        #raise UserErrorException("You must set a TARGET environement. It can be same as SOURCE. 'dev' to 'dev' is OK, or 'dev' -> 'test', 'text'->'prod'")

        if (target_environment== "prod" and current_environment=="test"): # target=PROD -> compare against previous models in PROD...highest level
            print ("Connect from TEST to PROD ( if you want to compare TEST-model with latest registered in PROD subscription/workspace")
            print("")
            try:
                #p.dev_test_prod = "prod" # get settings for target
                #auth = AzureCliAuthentication()
                ##target_workspace = Workspace.get(name = p.workspace_name,subscription_id = p.subscription_id,resource_group = p.resource_group,auth=cli_auth)
                target_workspace = self.get_other_workspace(current_ws,target_environment)
            finally:
                pass
                #p.dev_test_prod = current_env # flip back to TEST
        elif (target_environment == "test" and current_environment == "dev"): # target=test -> compare againt previous stage "dev"
            print ("Connect from DEV to TEST subscription/workspace  ( if you want to compare TEST-model with latest registered in PROD")
            print("")
            try:
                target_workspace = self.get_other_workspace(current_ws,target_environment)
            finally:
                pass
                #p.dev_test_prod = current_env # flip back to DEV
        elif (target_environment == current_environment ): # -> compare againt previous model in same "dev" workspace
            print ("target=source environement. Compare model version in DEV/TEST/PROD with latest registered in same DEV/TEST/PROD workspace (same workspace & subscriptiom comparison)")
            print("")
            target_workspace = current_ws
        
        return target_workspace

    ### Internal method of ESML, use PUBLIC method register_model() instead. But here you can affect the logic how to register a model in correct dev_test_prod workspace
    # Readmore: https://docs.microsoft.com/en-us/python/api/azureml-core/azureml.core.model.model?view=azure-ml-py
    # Implements: iESMLController _register_model_in_correct_workspace(self,current_ws, target_environment,new_model=None, description_in=None,pkl_name_in=None):
    ###
    def _register_model_in_correct_workspace(self,current_environment, current_ws, target_environment,new_model=None, description_in=None,pkl_name_in=None, esml_status=IESMLController.esml_status_not_new):
        pkl_name = "outputs" # "model.pkl"
        current_ws_name = current_ws.name

        if (pkl_name_in is not None):
            pkl_name = pkl_name_in

        # GET AML MODEL if not passed as arg
        m = None
        model_source = None
        temp_dir = tempfile.gettempdir()
        if(new_model is None): # luxuary function: not needing to pass Model, instead lookup model
            if(current_environment == "dev"):
                experiment, model_source,main_run, best_automl_run,fitted_model = IESMLController.get_best_model_run_fitted_model_Dev(current_ws,self.experiment_name)
            if(current_environment == "test" or current_environment == "prod"):
                model_source,run_id_tag, model_name_tag = IESMLController.get_best_model_via_modeltags_only_DevTestProd(current_ws,self.experiment_name)

            if(model_source is None):
                Exception("ESML:Could not lookup BEST MODEL from CURRENT environment in Azure ML Studio remotely.This might be the first time training model. \n - You need to pass a model as argument")
        else:
            model_source = new_model

        # GET PICKLE MODEL
        full_local_path = os.path.join(temp_dir, "esml",self._esml_project_folder_name,self._esml_model_alias)
        full_local_path = os.path.join(full_local_path, pkl_name)
        m = model_source.download(target_dir=full_local_path, exist_ok=True)
    
        model_name = model_source.tags["model_name"]
        run_id = model_source.tags["run_id"]

        tags = model_source.tags
        tags["trained_in_environment"] = current_environment
        tags["trained_in_workspace"] = current_ws_name
        tags["trained_in_workspace"] = current_ws_name

        tags["run_id"] = run_id
        tags["status_code"] = esml_status # Overwrite status_

        if("test_set_ROC_AUC" in model_source.tags):
            tags["test_set_Accuracy"] = model_source.tags["test_set_Accuracy"]
            tags["test_set_ROC_AUC"] = model_source.tags["test_set_ROC_AUC"]
            tags["test_set_Precision"] = model_source.tags["test_set_Precision"]
            tags["test_set_Recall"] = model_source.tags["test_set_Recall"]
            tags["test_set_F1_Score"] = model_source.tags["test_set_F1_Score"]
            tags["test_set_Matthews_Correlation"] = model_source.tags["test_set_Matthews_Correlation"]
            tags["test_set_CM"] = model_source.tags["test_set_CM"]
        if("test_set_RMSE" in model_source.tags):
            tags["test_set_RMSE"] = model_source.tags["test_set_RMSE"]
            tags["test_set_R2"] = model_source.tags["test_set_R2"]
            tags["test_set_MAPE"] = model_source.tags["test_set_MAPE"]
            tags["test_set_Spearman_Correlation"] = model_source.tags["test_set_Spearman_Correlation"]
        if("esml_time_updated " in model_source.tags):
            tags["esml_time_updated"] = model_source.tags["esml_time_updated"]
        
        try: # CONNECT to target Workspace
            target_ws = self.get_target_workspace(current_environment, current_ws, target_environment)
            print("Register in workspace:", target_ws.name)
            model_registered_in_target = self._register_aml_model(full_local_path,model_name,tags,target_ws,description_in)
        finally:
            self.dev_test_prod = current_environment # flip back to ORIGINAL environment

        return model_registered_in_target, model_source

    def _register_aml_model(self,full_local_path,model_name,tags,target_ws,description_in):
        full_local_path = "."
        if(full_local_path is None):
            full_local_path = self.get_default_localPath()

        model = Model.register(model_path=full_local_path, # Local file to upload and register as a model.
                        model_name=model_name,
                        model_framework=Model.Framework.SCIKITLEARN,  # Framework used to create the model.
                        model_framework_version=sklearn.__version__,  # Version of scikit-learn used to create the model.
                        #sample_input_dataset=self.project.GoldTest,  #sample_input_data=sample_input_dataset_id
                        #sample_output_dataset=self.project.GoldTest,
                        resource_configuration= self._resource_configuration, # ESML-Default: ResourceConfiguration(cpu=1, memory_in_gb=0.5)
                        tags=tags,
                        properties=tags,
                        description=description_in,
                        workspace=target_ws)
            #input_dataset = Dataset.Tabular.from_delimited_files(path=[(datastore, 'sklearn_regression/features.csv')])
            #output_dataset = Dataset.Tabular.from_delimited_files(path=[(datastore, 'sklearn_regression/labels.csv')])
        return model

    def get_default_localPath(self):
        pkl_name = "outputs" # "model.pkl"
        temp_dir = tempfile.gettempdir()
        full_local_path = os.path.join(temp_dir, "esml",self._esml_project_folder_name,self._esml_model_alias)
        full_local_path = os.path.join(full_local_path, pkl_name)
        return full_local_path