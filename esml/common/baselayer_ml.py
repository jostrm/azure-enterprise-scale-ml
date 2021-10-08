import pandas as pd
import numpy as np
from math import sqrt
from sklearn.metrics import mean_squared_error, r2_score,precision_score,recall_score,average_precision_score,f1_score,roc_auc_score,accuracy_score,roc_curve,confusion_matrix,mean_absolute_error, matthews_corrcoef, multilabel_confusion_matrix
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

def APE(actual, pred):
    """
    Calculate absolute percentage error.
    Returns a vector of APE values with same length as actual/pred.
    """
    return 100 * np.abs((actual - pred) / actual)


def MAPE(actual, pred):
    """
    Calculate mean absolute percentage error.
    Remove NA and values where actual is close to zero
    """
    not_na = ~(np.isnan(actual) | np.isnan(pred))
    not_zero = ~np.isclose(actual, 0.0)
    actual_safe = actual[not_na & not_zero]
    pred_safe = pred[not_na & not_zero]
    return np.mean(APE(actual_safe, pred_safe))

def get_4_regression_metrics(test_set, label,fitted_model):
    validation_data_pd = test_set
    y_test = validation_data_pd.pop(label).to_frame()
    y_predict = fitted_model.predict(validation_data_pd)

    
    # Calculate root-mean-square error
    y_actual = y_test.values.flatten().tolist()
    rmse = sqrt(mean_squared_error(y_actual, y_predict))
    mae = mean_absolute_error(y_actual, y_predict)
    spearman_correlation, p = spearmanr(y_actual, y_predict)

    # Calculate mean-absolute-percent error and model accuracy 
    sum_actuals = sum_errors = 0

    for actual_val, predict_val in zip(y_actual, y_predict):
        abs_error = actual_val - predict_val
        if abs_error < 0:
            abs_error = abs_error * -1

        sum_errors = sum_errors + abs_error
        sum_actuals = sum_actuals + actual_val

    mean_abs_percent_error = sum_errors / sum_actuals
    
    # Calculate the R2 score by using the predicted and actual 
    y_test_actual = y_test[label]
    r2 = r2_score(y_test_actual, y_predict)

    plt.style.use('ggplot')
    plt.figure(figsize=(10, 7))
    plt.scatter(y_test_actual,y_predict)
    plt.plot([np.min(y_test_actual), np.max(y_test_actual)], [np.min(y_test_actual), np.max(y_test_actual)], color='lightblue', label="R^2={}".format(r2))
    plt.xlabel("Actual")
    plt.ylabel("Predicted")
    plt.title("Actual VS Predicted (R^2={} )".format(r2))

    return rmse, r2, mean_abs_percent_error,mae, spearman_correlation,plt


def get_7_classification_metrics(test_set, label,fitted_model,multiclass=None):
    X_test = test_set # X_test
    y_test = X_test.pop(label).to_frame() # y_test (true labels)
    y_predict = fitted_model.predict(X_test) # y_predict (predicted labels)
    y_predict_proba = None
    
    if (has_predict_proba(fitted_model)):
        y_predict_proba = fitted_model.predict_proba(X_test) # y_predict (predicted probabilities)
        if(has_iloc(y_predict_proba)):
            #df_out['predict_proba_0']  = y_predict_proba.iloc[:,0]
            predict_proba = y_predict_proba.iloc[:,1]
        else:
            #df_out['predict_proba_0']  = y_predict_proba[:,0]
            predict_proba  = y_predict_proba[:,1]

    #predict_proba = y_predict_proba[:, 1] # Positive values only
    auc = None
    matrix = None
    precision = None
    f1 = None
    if(multiclass is not None):
        #print("Multiclass classification")
        try:
            auc = roc_auc_score(y_true=y_test, y_score=y_predict_proba,multi_class=multiclass)
            pass
        except Exception as e:
            if("IndexError: too many indices for array" in e.message):
                pred = y_predict_proba[:,1]
                auc = roc_auc_score(y_true=y_test, y_score=pred,multi_class=multiclass)
            else:
                raise e
        matrix = multilabel_confusion_matrix(y_test, y_predict) # binarized under a one-vs-rest way
        precision = precision_score(y_test, y_predict, average=None)
        recall = recall_score(y_test, y_predict, average=None)
        f1 = f1_score(y_test,y_predict,average=None)
    else:
        #print("Binary classification")
        auc = roc_auc_score(y_test, predict_proba)
        matrix = confusion_matrix(y_test, y_predict)
        precision= average_precision_score(y_test, y_predict)
        recall = recall_score(y_test, y_predict)
        f1 = f1_score(y_test,y_predict)

    #print("Generic classification metrics")
    accuracy = accuracy_score(y_test, y_predict)
    matthews = matthews_corrcoef(y_test, y_predict)  # Matthews Correlation Coefficient is The Best Classification Metric You’ve Never Heard Of...

    plt = None
    if(multiclass is None):
        fpr, tpr, thresholds = roc_curve(y_test, predict_proba)
        plt.plot(fpr, tpr, color='blue', label='AUC='+str(auc))
        plt.plot([0, 1], [0, 1], color='darkblue', linestyle='--')
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        plt.title('Receiver Operating Characteristic (ROC) Curve')
        plt.legend()
    #plt.show()
    
    return auc,accuracy,f1, precision,recall,matrix,matthews, plt

def has_predict_proba(model):
    if model is not None and hasattr(model, 'predict_proba') and model.predict_proba is not None:
        return True
    else:
        return False

from scipy.sparse import issparse
def has_iloc(df_series_or_ndarray):
    if issparse(df_series_or_ndarray):
        return True
    if (isinstance(df_series_or_ndarray, pd.DataFrame)):
        return True
    if (isinstance(df_series_or_ndarray, pd.Series)):
        return True
    if (isinstance(df_series_or_ndarray, np.ndarray)):
        return False
    return False