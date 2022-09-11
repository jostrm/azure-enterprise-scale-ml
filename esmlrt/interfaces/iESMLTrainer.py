from abc import ABCMeta, abstractmethod

class IESMLTrainer:
    __metaclass__ = ABCMeta

    _experiment_name = ""
    _model_name = None
    _esml_model_name = "10_titanic_model_clas"
    _esml_model_alias = "M10"
    _esml_current_env = "dev"
    _ml_type = "classification"

    _df_train = None
    _df_validate = None
    _df_test = None
    _df_other = None
    _scoring_dictionary = {}
    
    def __init__(self, aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df, other_df=None):
        self._model_name = aml_model_name
        self._esml_model_name = esml_model_name
        self._esml_model_alias = esml_model_alias
        self._esml_current_env = esml_current_env
        self._ml_type = ml_type

        self._df_train=train_df
        self._df_validate = validate_df
        self._df_test = test_df
        
        self._df_other = other_df
        self._experiment_name = self._esml_model_name #+ "_TRAIN"

    @classmethod
    def version(self): return "1.4"

    @property
    @abstractmethod
    def experiment_name(self):
        return self._experiment_name

    ###
    # returns: train_run, aml_model,fitted_model
    # Track with MLFlow: https://docs.microsoft.com/en-us/azure/machine-learning/tutorial-train-deploy-notebook
    ###
    @abstractmethod
    def train(self,train_aml_ds, validate_aml_ds):raise NotImplementedError

    #@abstractmethod
    #def compare_scoring_current_vs_new_model(self, target_environment = None): raise NotImplementedError