import numpy as np
import pandas as pd
import sys
sys.path.append("..")
from esmlrt.interfaces.iESMLTrainer import IESMLTrainer
from esmlrt.interfaces.iESMLSplitter import IESMLSplitter # Just for reference to see where the abstract class exists
from esmlrt.runtime.ESMLSplitter import ESMLSplitter1 # Point at your own code/class here instead..that needst to implement the IESMLSplitter class

from azureml.train.automl import AutoMLConfig

class Trainer(IESMLTrainer):
    _scoring_dictionary = {}
    
    def __init__(self, aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df, other_df=None):
        super().__init__(aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df, other_df=None)

    @staticmethod
    def split_gold(azure_ml_gold_dataset, train_percentage=0.6, label=None,stratified=False,seed=42):
        my_IESMLSplitter = ESMLSplitter1() # Provides a consistent way of spli logic - from pipeline or from notebook - using same Splitter.
        df = azure_ml_gold_dataset.to_pandas_dataframe()
        train,train_percentage,validate,validate_percentage,test,test_percentage = my_IESMLSplitter.split(df,label,train_percentage,seed,stratified)
        return train,validate,test

    # https://github.com/CESARDELATORRE/Easy-AutoML-MLOps/blob/master/notebooks/4-automlstep-pipeline-run/automlstep-pipeline-run-safe-driver-classifier.ipynb
    def train(self,train_aml_ds, validate_aml_ds):
        train_run = None
        aml_model = None
        fitted_model = None
        
        if(self._esml_model_alias == "M10"): # For demo purposes only...you should only have one Trainer instance, per model. Not handle multiple.
            pass
        elif(self._esml_model_alias == "M11"):
            pass

        return train_run, aml_model,fitted_model

    
    ##
    # If you want to use AutoML, and not AutoMLStep via ESML and IN_2_GOLD_TRAIN_AUTOML_PIPELINE
    # Then you can override 100% and implement your own AutoML. Example for Image classification, or NLP
    ##
    def automl_training(self,train_aml_ds, ws,amlcompute_cluster_name):

        train_run, aml_model,fitted_model = None,None,None # Needs to return this
        ####################### Pseudo code below ############ 

        automl_performance_config = {'enable_voting_ensemble': True,
        'enable_stack_ensemble': False,
        'model_explainability': True,
        'experiment_timeout_hours': 0.75,
        'iteration_timeout_minutes': 5,
        'n_cross_validations': 3,
        'enable_early_stopping': False,
        'iterations': 21,
        'max_cores_per_iteration': -1,
        'allowed_models': ['LightGBM', 'RandomForest', 'Xgboost'],
        'path': '.',
        'debug_log': 'azure_automl_debug_dev.log'}

        compute_target = None
        runconfig = None
        label = None
        #compute_target = ComputeTarget(workspace=ws, name=amlcompute_cluster_name)
        automl_config = AutoMLConfig(task = 'regression',  #TODO: move as a parameter in get_automl_performance_config()
                            primary_metric = 'normalized_mean_absolute_error', #TODO: move as a parameter in get_automl_performance_config()
                            compute_target = self,
                            run_configuration = runconfig,
                            training_data = train_aml_ds, # p.GoldTrain, 
                            experiment_exit_score = '0.308', # DEMO purpose #TODO: pass as a parameter "DEMO"
                            label_column_name = label,
                            **automl_performance_config
                        )
        #experiment = Experiment(ws, experiment_name)
        #remote_run = experiment.submit(automl_config, show_output = True)

        #remote_run.wait_for_completion()
        #best_run, fitted_model = remote_run.get_output()
        return  train_run, aml_model,fitted_model # Needs to return this