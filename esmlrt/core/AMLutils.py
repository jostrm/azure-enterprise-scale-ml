
# Task_type - https://docs.microsoft.com/en-us/python/api/azureml-automl-core/azureml.automl.core.shared.constants.tasks?view=azure-ml-py
# AutoML Supported value(s): 'accuracy, precision_score_weighted, norm_macro_recall, AUC_weighted, average_precision_score_weighted'. 
class azure_metric_classification():
    AUC = "AUC_weighted"
    Accuracy = "accuracy"
    Precision = "precision_score_weighted"
    Precision_avg = "average_precision_score_weighted"
    Recall = "norm_macro_recall"
    #F1_score = "f1_score_weighted"
    #Log_loss = "log_loss"

# AutoML Supported value(s):  'normalized_mean_absolute_error, normalized_root_mean_squared_error, spearman_correlation, r2_score'
class azure_metric_regression():
    MAE = "normalized_mean_absolute_error"
    RMSE = "normalized_root_mean_squared_error"
    R2 = "r2_score"
    Spearman = "spearman_correlation"
    #MAPE = "mean_absolute_percentage_error"  # Not supported in AutoML training as
    #R2oob = "explained_variance"
    #Recall = "recall"