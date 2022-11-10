import numpy as np
import pandas as pd
import sys
from sklearn.linear_model import Ridge
from sklearn import __version__ as sklearnver
from packaging.version import Version
if Version(sklearnver) < Version("0.23.0"):
    from sklearn.externals import joblib
else:
    import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
from azureml.core import Run
import os
import datetime
#import mlflow
#import mlflow.sklearn

sys.path.append("..")
from esmlrt.interfaces.iESMLTrainer import IESMLTrainer
from esmlrt.interfaces.iESMLSplitter import IESMLSplitter # Just for reference to see where the abstract class exists
from esmlrt.runtime.ESMLSplitter import ESMLSplitter1 # Point at your own code/class here instead..that needst to implement the IESMLSplitter class

from azureml.train.automl import AutoMLConfig

# optional: only needed to be implemented/used if not using AutoML
class Trainer(IESMLTrainer):
    _scoring_dictionary = {}
    
    def __init__(self, aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df, target_column_name=None, other_df=None):
        super().__init__(aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df,target_column_name, other_df)

    @staticmethod
    def split_gold(azure_ml_gold_dataset, train_percentage=0.6, label=None,stratified=False,seed=42):

        my_IESMLSplitter = ESMLSplitter1() # Provides a consistent way of spli logic - from pipeline or from notebook - using same Splitter.
        df = azure_ml_gold_dataset.to_pandas_dataframe()
        train,train_percentage,validate,validate_percentage,test,test_percentage = my_IESMLSplitter.split(df,label,train_percentage,seed,stratified)
        return train,validate,test

    # https://github.com/CESARDELATORRE/Easy-AutoML-MLOps/blob/master/notebooks/4-automlstep-pipeline-run/automlstep-pipeline-run-safe-driver-classifier.ipynb
    def train(self,train_aml_ds, validate_aml_ds,target_column_name):
        train_run = None
        aml_model = None
        fitted_model = None
        train_run = Run.get_context()

        if(target_column_name is not None and self._label is not None and self._label != target_column_name):
            print("ESML INFO: Overriding default label for this Trainer. Default is '{}' and new override is: '{}'".format(self._label,target_column_name))

        if(self._esml_model_alias == "M10"): # For demo purposes only...you should only have one Trainer instance, per model. Not handle multiple.
            pass
        elif(self._esml_model_alias == "M11"):

            # LABEL
            label = self._label # Note: self._label may be None, if you did not add in contstructor, since optional
            if(target_column_name is not None):
                label = target_column_name

            # SPLIT 
            df = train_aml_ds.to_pandas_dataframe()
            X = df.drop(label, axis=1)
            y = df.pop(label).to_frame()

            X_train, X_test, y_train, y_test = train_test_split(X, y,test_size=0.2,random_state=0)

            data = {"train": {"X": X_train, "y": y_train},
                    "test": {"X": X_test, "y": y_test}}

            # FIT MODEL
            alphas = np.arange(0.0, 1.0, 0.05) #  list of numbers from 0.0 to 1.0 with a 0.05 interval
            
            latest_mse = None
            best_mse = None
            best_model_file_path = None

            '''
             # Start Logging
            mlflow.start_run()

            # enable autologging
            mlflow.sklearn.autolog()
            
            '''
            for alpha in alphas:
                # Use Ridge algorithm to create a regression model
                reg = Ridge(alpha=alpha)
                reg.fit(data["train"]["X"], data["train"]["y"])

                preds = reg.predict(data["test"]["X"])
                mse = mean_squared_error(preds, data["test"]["y"])
                train_run.log('alpha', alpha)
                train_run.log('mse', mse)
                #mlflow.log_metric("alpha", alpha)
                #mlflow.log_metric("mse", mse)

                model_file_name = 'ridge_{0:.2f}.pkl'.format(alpha)
                # save model in the outputs folder so it automatically get uploaded
                with open(model_file_name, "wb") as file:
                    latest_path = os.path.join('./outputs/',model_file_name)
                    joblib.dump(value=reg, filename=latest_path)

                #print('ESML Manual training: Current alpha is {0:.2f}, and mse is {1:0.2f}'.format(alpha, mse))

                # Keep track on BEST fitting
                if(latest_mse is None):
                    latest_mse = mse
                    best_mse = latest_mse
                    best_model_file_path = latest_path
                elif(best_mse is not None):
                    if(mse <= best_mse):
                        latest_mse = mse
                        best_mse = latest_mse
                        best_model_file_path = latest_path

            print("ESML Manual training: Best fitted model is now: {}, since MSE = {}".format(best_model_file_path,best_mse))
            
            ### Alt A) SAVE model as .pickle (ESML will register model automatically later)
            try:
                fitted_model = joblib.load(best_model_file_path)
                print("ESML Manual training:load Model with joblib.load, name model.pkl SUCCESS for {}".format(best_model_file_path))

            except Exception as e:
                print("ESML Manual training: Cannot load Model with name {}".format(best_model_file_path))

            ### Alt B) save and register model with MLFlow
            '''
            print("Registering the model via MLFlow to workspace")
            mlflow.sklearn.log_model(
                sk_model=clf,
                registered_model_name=args.registered_model_name,
                artifact_path=args.registered_model_name,
            )

            print('Saving the model via mlflow to a file')
            mlflow.sklearn.save_model(
                sk_model=clf,
                path=os.path.join(args.registered_model_name, "trained_model"),
            )
            mlflow.end_run() # Stop Logging
            '''

        return train_run, aml_model,fitted_model,best_model_file_path

    
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