from esmlrt.interfaces.iESMLController import IESMLController
from esmlrt.interfaces.iESMLModelCompare import IESMLModelCompare
from esmlrt.interfaces.iESMLTestScoringFactory import IESMLTestScoringFactory
from esmlrt.interfaces.iESMLTrainer import IESMLTrainer
from esmlrt.runtime.ESMLController import ESMLController
from esmlrt.runtime.ESMLModelCompare2 import ESMLModelCompare
from esmlrt.runtime.ESMLTestScoringFactory2 import ESMLTestScoringFactory

class ESMLFactory:

    @staticmethod
    def get_esml_controller_from_notebook(esml_project):
        project_name = esml_project.project_folder_name
        ws = esml_project.ws
        target_column_name = esml_project.active_model["label"]
        ml_type = esml_project.active_model["ml_type"]

        esml_modelname = esml_project.model_folder_name
        esml_model_alias = esml_project.ModelAlias
        esml_current_env  = esml_project.dev_test_prod
        train_ds = esml_project.GoldTrain
        validate_ds = esml_project.GoldValidate
        test_ds = esml_project.GoldTest
        all_envs = esml_project.get_all_envs()

        secret_name_tenant = esml_project.LakeAccess.storage_config["tenant"]
        secret_name_sp_id =  esml_project.LakeAccess.storage_config["kv-secret-esml-projectXXX-sp-id"]
        secret_name_sp_secret = esml_project.LakeAccess.storage_config["kv-secret-esml-projectXXX-sp-secret"]

        test_scoring = ESMLTestScoringFactory(ml_type) # You need to implement IESMLTestScoringFactory
        comparer = ESMLModelCompare(setting_path = "../../") # You need to implement IESMLModelCompare

        controller = ESMLController(comparer,test_scoring,project_name,esml_modelname, esml_model_alias,all_envs, secret_name_tenant,secret_name_sp_id,secret_name_sp_secret ) # IESMLController: you do not have to change/implemen this class. Dependency injects default or your class.
        controller.dev_test_prod = esml_current_env
        #controller.version()
        return controller