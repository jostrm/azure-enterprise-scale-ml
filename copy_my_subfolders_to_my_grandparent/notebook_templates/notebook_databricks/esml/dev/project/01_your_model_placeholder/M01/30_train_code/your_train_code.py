# Databricks notebook source
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
from math import sqrt
from azureml.core import Run
import os
import pickle
from datetime import datetime

# COMMAND ----------

def calculate_test_set_scoring_tags(best_rmse=None):

# TODO 4 YOU Calculate your own Test_set scoring, using self._df_test
# Alternatively - you can use ESMLTestScoringFactory()

  tags = {}
  date_time = datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
  def_value_not_set = -1.0
  matrix = "[[][]]"
  _ml_type = "regression"

# Set default values
  tags["test_set_Accuracy"] ="{:.6}".format(def_value_not_set)
  tags["test_set_ROC_AUC"] = "{:.6}".format(def_value_not_set)
  tags["test_set_Precision"] = "{:.6}".format(def_value_not_set)
  tags["test_set_Recall"] = "{:.6}".format(def_value_not_set)
  tags["test_set_F1_Score"] = "{:.6}".format(def_value_not_set)
  tags["test_set_Matthews_Correlation"] = "{:.6}".format(def_value_not_set)
  tags["test_set_CM"] = str(matrix)
  tags["test_set_RMSE"] = "{:.6}".format(def_value_not_set)
  tags["test_set_R2"] = "{:.6}".format(def_value_not_set)
  tags["test_set_MAPE"] = "{:.6}".format(def_value_not_set)
  tags["test_set_Spearman_Correlation"] = "{:.6}".format(def_value_not_set)
  tags["esml_time_updated"] = str(date_time)
  tags["ml_type"] = _ml_type

# TODO 4 YOU - Add the values you've calculated. Best is to calculate all of them
  if(_ml_type == 'classification'):
    tags["test_set_Accuracy"] ="{:.6}".format(def_value_not_set)
    tags["test_set_ROC_AUC"] = "{:.6}".format(def_value_not_set)
    tags["test_set_Precision"] = "{:.6}".format(def_value_not_set)
    tags["test_set_Recall"] = "{:.6}".format(def_value_not_set)
    tags["test_set_F1_Score"] = "{:.6}".format(def_value_not_set)
    tags["test_set_Matthews_Correlation"] = "{:.6}".format(def_value_not_set)
    tags["test_set_CM"] = str(matrix)
  elif(_ml_type == 'regression'):
    tags["test_set_RMSE"] = "{:.6}".format(best_rmse) # DEMO - setting this
    tags["test_set_R2"] = "{:.6}".format(def_value_not_set)
    tags["test_set_MAPE"] = "{:.6}".format(def_value_not_set)
    tags["test_set_Spearman_Correlation"] = "{:.6}".format(def_value_not_set)
    tags["esml_time_updated"] = str(date_time)

  return tags

# COMMAND ----------

def train_df(df, validate_df,target_column_name,dbfs_model_out_path, use_run_logging=True, train_run = None):
  aml_model = None
  fitted_model = None
  #out_path = '/dbfs/mnt/prj002/11_diabetes_model_reg/train/model/' # /esml/dev/project/11_diabetes_model_reg/M11/30_train_code/your_train_code
  
  if(use_run_logging):
    #train_run = Run.get_context() # Run.get_context(allow_offline=False)
    if (train_run is not None):
      try:
          try:
            print("Train(online run) and Azure ML pipeline Run.parent.id: {}".format(train_run.parent.id))
          except Exception as e5:
            #print(e5)
            print("Train(online run) and Azure ML pipeline Run.id: {}".format(train_run.id))
      except Exception as e:
        print(e)
        use_run_logging = False
    else:
      print("Warning 5: Method train_df() - Cannot log to train_run since it is None")
            
  # LABEL
  label = target_column_name 
  if(target_column_name is not None):
      label = target_column_name

  # Pandas way
  #X = df.drop(label, axis=1)
  #y = df.pop(label).to_frame()
  #X = gold_train_df.iloc[:, 0:9] # Features. 
  #y = gold_train_df.iloc[:, 10] # LABEL
  
  # Pyspark way
  X = gold_train_df.select(gold_train_df.columns[0:10])
  y = gold_train_df.select(gold_train_df.columns[10])
  
  X = X.toPandas()
  y = y.toPandas()

  X_train, X_test, y_train, y_test = train_test_split(X, y,test_size=0.2,random_state=0)

  data = {"train": {"X": X_train, "y": y_train},
          "test": {"X": X_test, "y": y_test}}

  # FIT MODEL
  alphas = np.arange(0.0, 1.0, 0.05) #  list of numbers from 0.0 to 1.0 with a 0.05 interval

  latest_mse = None
  best_mse = None
  best_rmse = None
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
    rmse = sqrt(mse)

    if(use_run_logging):
      train_run.log('alpha', alpha)
      train_run.log('mse', mse)
      train_run.log('rmse', rmse)
    #mlflow.log_metric("alpha", alpha)
    #mlflow.log_metric("mse", mse)

    model_file_name = dbfs_model_out_path + 'ridge_{0:.2f}.pkl'.format(alpha)

    # SAVE file
    latest_path = model_file_name
    os.makedirs(os.path.dirname(latest_path), exist_ok=True)
    pickle.dump(reg, open(latest_path, 'wb'))
    print(latest_path)

    #print('ESML Manual training: Current alpha is {0:.2f}, and mse is {1:0.2f}'.format(alpha, mse))

    # Keep track on BEST fitting
    if(latest_mse is None):
        latest_mse = mse
        best_rmse = rmse
        best_mse = latest_mse
        best_model_file_path = latest_path
    elif(best_mse is not None):
        if(mse <= best_mse):
            latest_mse = mse
            best_mse = latest_mse
            best_rmse = rmse
            best_model_file_path = latest_path

  print("Databricks Manual training via Azure ML Pipeline generated by ESML: Best fitted model is now: {}, since MSE = {} and RMSE {}".format(best_model_file_path,best_mse, best_rmse))

  ### Alt A) SAVE model as .pickle (ESML will register model automatically later)
  try:
      fitted_model = pickle.load(open(best_model_file_path, 'rb'))
      print("Manual training:load Model with joblib.load, name model.pkl SUCCESS for {}".format(best_model_file_path))
  except Exception as e:
      print("Manual training: Cannot load Model with name {}".format(best_model_file_path))

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

  scoring_tags = calculate_test_set_scoring_tags(best_rmse)
  return train_run, aml_model,fitted_model,best_model_file_path,scoring_tags
