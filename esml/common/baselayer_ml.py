import pandas as pd
import numpy as np
from math import sqrt
from sklearn.metrics import mean_squared_error, r2_score,recall_score,average_precision_score,f1_score,roc_auc_score,accuracy_score,roc_curve,confusion_matrix
import matplotlib.pyplot as plt

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

    # Calculate mean-absolute-percent error and model accuracy 
    sum_actuals = sum_errors = 0

    for actual_val, predict_val in zip(y_actual, y_predict):
        abs_error = actual_val - predict_val
        if abs_error < 0:
            abs_error = abs_error * -1

        sum_errors = sum_errors + abs_error
        sum_actuals = sum_actuals + actual_val

    mean_abs_percent_error = sum_errors / sum_actuals
    accuracy = 1 - mean_abs_percent_error
    
    # Calculate the R2 score by using the predicted and actual 
    y_test_actual = y_test[label]
    r2 = r2_score(y_test_actual, y_predict)

    plt.style.use('ggplot')
    plt.figure(figsize=(10, 7))
    plt.scatter(y_test_actual,y_predict)
    plt.plot([np.min(y_test_actual), np.max(y_test_actual)], [np.min(y_test_actual), np.max(y_test_actual)], color='lightblue')
    plt.xlabel("Actual")
    plt.ylabel("Predicted")
    plt.title("R^2={}".format(r2))

    return rmse, r2, mean_abs_percent_error,accuracy,plt


def get_7_classification_metrics(test_set, label,fitted_model):
    X_test = test_set # X_test
    y_test = X_test.pop(label).to_frame() # y_test (true labels)
    y_predict = fitted_model.predict(X_test) # y_predict (predicted labels)
    y_predict_proba = fitted_model.predict_proba(X_test) # y_predict (predicted probabilities)

    predict_proba = y_predict_proba[:, 1] # Positive values only
    auc = roc_auc_score(y_test, predict_proba)
    fpr, tpr, thresholds = roc_curve(y_test, predict_proba)
    
    accuracy, precision, recall, f1, matrix = \
    accuracy_score(y_test, y_predict),\
    average_precision_score(y_test, y_predict),\
    recall_score(y_test, y_predict),\
    f1_score(y_test,y_predict), \
    confusion_matrix(y_test, y_predict)

    plt.plot(fpr, tpr, color='blue', label='AUC='+str(auc))
    plt.plot([0, 1], [0, 1], color='darkblue', linestyle='--')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('Receiver Operating Characteristic (ROC) Curve')
    plt.legend()
    #plt.show()
    
    return auc,accuracy,f1, precision,recall,matrix, plt

