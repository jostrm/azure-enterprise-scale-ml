import pandas as pd
import numpy as np
from math import sqrt
from sklearn.metrics import mean_squared_error, r2_score,precision_score,recall_score,average_precision_score,f1_score,roc_auc_score,accuracy_score,roc_curve,confusion_matrix,mean_absolute_error, matthews_corrcoef, multilabel_confusion_matrix
import matplotlib.pyplot as plt
from scipy.stats import spearmanr
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.metrics import confusion_matrix
from sklearn.metrics import ConfusionMatrixDisplay

#import seaborn as sn

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

# validateset_and_testset_percentage_together - If train=0.8 then this is 0.2
# left_per_set - 0.5 meaning will be 10% each if 20% validateset_and_testset_percentage_together
# NB! In StratifiedShuffleSplit it can and will overlap as a default behaviour. (hence below impl.)
def split_stratified(gold_data, validateset_and_testset_percentage_together=0.2,left_per_set=0.5, y_label=None, seed=42):

    s1 = StratifiedShuffleSplit(n_splits=1, test_size=validateset_and_testset_percentage_together, random_state=seed)

    y_labels_array = gold_data[y_label]
    for train_index, test_valid_index in s1.split(gold_data, y_labels_array): # gold_dataset_pandas, gold_dataset_pandas.status_
        train = gold_data.iloc[train_index]
        testset_and_validate_set = gold_data.iloc[test_valid_index]

    s2 = StratifiedShuffleSplit(n_splits=1, test_size=left_per_set, random_state=seed) # Split Remaining from TRAIN in 2 sets, for us to get 3 sets: TRAIN, VALIDATE, TEST

    y_labels_array = testset_and_validate_set[y_label]
    for test_index, validate_index in s2.split(testset_and_validate_set, y_labels_array):
        test_set = testset_and_validate_set.iloc[test_index]
        validate_set = testset_and_validate_set.iloc[validate_index]
        
    return train,validate_set,test_set

'''
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
labels = p.GoldTest.to_pandas_dataframe()[p.active_model["label"]].unique()
disp = ConfusionMatrixDisplay(confusion_matrix=matrix, display_labels=labels)
p1 = disp.plot()

'''
def get_7_classification_metrics(test_set, label,fitted_model,multiclass=None,positive_label=None):
    X_test = test_set # X_test
    labels = test_set[label].unique()

    y_test = X_test.pop(label).to_frame() # y_test (true labels)
    y_predict = fitted_model.predict(X_test) # y_predict (predicted labels)
    y_predict_proba = None
    
    if (has_predict_proba(fitted_model)):
        y_predict_proba = fitted_model.predict_proba(X_test) # y_predict (predicted probabilities)
        if(has_iloc(y_predict_proba)):
            predict_proba = y_predict_proba.iloc[:,1]
        else:
            predict_proba  = y_predict_proba[:,1]

    #predict_proba = y_predict_proba[:, 1] # Positive values only
    cm_image = None
    auc = None
    matrix = None
    precision = None
    f1 = None
    plot = None

    if(multiclass is not None): # Much more usual to use confusion matrix, than ROC for multi-classification
        matrix = multilabel_confusion_matrix(y_test, y_predict) # binarized under a one-vs-rest way
        precision = precision_score(y_test, y_predict, average=None)
        recall = recall_score(y_test, y_predict, average=None)
        f1 = f1_score(y_test,y_predict,average=None)
        plot = generate_multi_class_plot(matrix,labels)
    else:
        #print("Binary classification")
        auc = roc_auc_score(y_test, predict_proba)
        matrix = confusion_matrix(y_test, y_predict)
        fig_1 = plt.figure(1,figsize = (20,4.8))
        chart_1 = fig_1.add_subplot(121)
        chart_1.set_title("Confusion Matrix - TEST_SET")
        df_cm = pd.DataFrame(matrix, index = [i for i in labels],columns = [i for i in labels])
        
        disp = ConfusionMatrixDisplay(confusion_matrix=matrix, display_labels=labels)
        cm_plot = disp.plot(ax = chart_1)
        #s1= sn.heatmap(df_cm, annot=True) # ESML-v14 dependency to seaborn removed

        try:
            precision= average_precision_score(y_test, y_predict,pos_label=positive_label)
            recall = recall_score(y_test, y_predict,pos_label=positive_label)
            f1 = f1_score(y_test,y_predict,pos_label=positive_label)
        except:
            precision= average_precision_score(y_test, y_predict)
            recall = recall_score(y_test, y_predict)
            f1 = f1_score(y_test,y_predict)

    accuracy = accuracy_score(y_test, y_predict)
    matthews = matthews_corrcoef(y_test, y_predict)  # Matthews Correlation Coefficient is The Best Classification Metric You’ve Never Heard Of...

    if(multiclass is None):
        fpr, tpr, thresholds = roc_curve(y_test, predict_proba)

        fig_1 # fig_2 = plt.figure(1,figsize = (20,4.8))
        chart_2 = fig_1.add_subplot(122) # fig_2.add_subplot(122)

        chart_2.plot(fpr, tpr, color='blue', label='AUC='+str(auc))
        chart_2.plot([0, 1], [0, 1], color='darkblue', linestyle='--')
        chart_2.set_xlabel('False Positive Rate')
        chart_2.set_ylabel('True Positive Rate')
        chart_2.set_title('Receiver Operating Characteristic (ROC) Curve')
        chart_2.legend()
        plot = plt
    
    return auc,accuracy,f1, precision,recall,matrix,matthews, plot

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


def print_confusion_matrix(confusion_matrix, axes, class_label, class_names, fontsize=14):

    df_cm = pd.DataFrame(
        confusion_matrix, index=class_names, columns=class_names,
    )

    try:
        heatmap = sn.heatmap(df_cm, annot=True, fmt="d", cbar=False, ax=axes)
    except ValueError:
        raise ValueError("Confusion matrix values must be integers.")
    heatmap.yaxis.set_ticklabels(heatmap.yaxis.get_ticklabels(), rotation=0, ha='right', fontsize=fontsize)
    heatmap.xaxis.set_ticklabels(heatmap.xaxis.get_ticklabels(), rotation=45, ha='right', fontsize=fontsize)
    axes.set_ylabel('True')
    axes.set_xlabel('Predicted')
    axes.set_title(str(class_label))

def generate_multi_class_plot(matrix,labels):
    even_no = int(len(labels))
    if (even_no % 2) == 0 and even_no>=2: # Only if "even" number, matrix
        dims = int(even_no / 2)
        
        fig, ax = plt.subplots(dims, dims, figsize=(12, 7))
        for axes,cfs_matrix,label in zip(ax.flatten(), matrix, labels):
            pass
            #print_confusion_matrix(cfs_matrix, axes, label, ["N", "Y"]) # TODO-ESML-v14 dependency to seaborn removed

        fig.tight_layout()
        return plt
    else:
        return None


