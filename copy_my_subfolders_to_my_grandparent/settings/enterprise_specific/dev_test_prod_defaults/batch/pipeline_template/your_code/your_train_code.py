import numpy as np
import pandas as pd
import sys
sys.path.append("..")
from esmlrt.interfaces.iESMLTrainer import IESMLTrainer
from azureml.train.automl import AutoMLConfig

class Trainer(IESMLTrainer):
    _scoring_dictionary = {}
    
    def __init__(self, aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df, other_df=None):
        super().__init__(aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df, other_df=None)

    @staticmethod
    def split_gold(azure_ml_gold_dataset, train_percentage=0.6, label=None,stratified=False,seed=42):
        df = azure_ml_gold_dataset.to_pandas_dataframe()
        whats_left_for_both = round(1-train_percentage,1)  # 0.4 ...0.3 if 70%
        left_per_set = round((whats_left_for_both / 2),2) # 0.2  ...0.15
        validate_and_test = round((1-left_per_set),2) # 0.8 ....0.75

        train, validate, test = \
            np.split(df.sample(frac=1, random_state=seed), 
                    [int(train_percentage*len(df)), int(validate_and_test*len(df))])
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

    
    def automl_training(self,train_aml_ds, ws,amlcompute_cluster_name, ):

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

        compute_target = ComputeTarget(workspace=ws, name=amlcompute_cluster_name)
        automl_config = AutoMLConfig(task = 'regression',  #TODO: move as a parameter in get_automl_performance_config()
                            primary_metric = 'normalized_mean_absolute_error', #TODO: move as a parameter in get_automl_performance_config()
                            compute_target = self,
                            run_configuration = runconfig,
                            training_data = train_aml_ds, # p.GoldTrain, 
                            experiment_exit_score = '0.308', # DEMO purpose #TODO: pass as a parameter "DEMO"
                            label_column_name = label,
                            **automl_performance_config
                        )
        experiment = Experiment(ws, experiment_name)
        remote_run = experiment.submit(automl_config, show_output = True)

        remote_run.wait_for_completion()
        best_run, fitted_model = remote_run.get_output()
        return  train_run, aml_model,fitted_model