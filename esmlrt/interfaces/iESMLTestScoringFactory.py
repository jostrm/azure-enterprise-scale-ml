from abc import ABCMeta, abstractmethod

class IESMLTestScoringFactory:
    __metaclass__ = ABCMeta

    _ml_type = "classification"

    def __init__(self,ml_type = "regression"):

        if(ml_type != "regression" and ml_type != "classification"):
            raise Exception("Currently ESML TestScoringFactory only supports ml_type of 'classification', 'regression'. For 'forecast', Please see docs for hwo you can calculat this yourself for forecasting at https://docs.microsoft.com/en-us/azure/machine-learning/how-to-auto-train-forecast")
        self._ml_type = ml_type

    @classmethod
    def version(self): return "1.4"
    
    ###
    # properties
    ###
    @property
    @abstractmethod
    def ml_type(self):
        return self._ml_type

    ###
    # Pass either a Run, or a Model(). If Run, this superseeds Model
    ## Tip: Prefer to pass Run() rather than Model(), since the plot graphics can only be uploaded on a Run(), and not a Model()
    # returns auc,accuracy,f1, precision,recall,matrix,matthews,plt
    # returns:8 metric values + model with tags, equals 9 values to unpack
    ###
    @abstractmethod
    def get_test_scoring_classification(self,ws,target_column_name,GoldTest,fitted_model,train_run=None,aml_model=None,multiclass=None,positive_label=None): raise NotImplementedError
    
    ###
    # Pass either a Run, or a Model(). If Run, this superseeds Model
    ## Tip: Prefer to pass Run() rather than Model(), since the plot graphics can only be uploaded on a Run(), and not a Model()
    # returns: rmse, r2, mean_abs_percent_error,mae,spearman_corr,plt 
    ###
    @abstractmethod
    def get_test_scoring_regression(self,ws,label,GoldTest,fitted_model,run=None, aml_model=None): raise NotImplementedError

    ### 
    # returns:7 or 9 metric values + model with tags, equals 9 values to unpack
    ## Regression (7+2 summy=9): model,rmse, r2, mean_abs_percent_error,mae,spearman_corr,plt, dummy, dummy
    ## Classification (9): model,auc,accuracy,f1, precision,recall,matrix,matthews,plt
    ###
    def get_test_scoring_8(self,ws,target_column_name,test_ds,fitted_model,train_run=None,aml_model=None, multiclass=None,positive_label=None):
        if self._ml_type == 'regression':
            model, rmse, r2, mean_abs_percent_error,mae,spearman_correlation,plt = self.get_test_scoring_regression(ws,target_column_name,test_ds,fitted_model,train_run,aml_model)
            dummy = None
            return model,rmse, r2, mean_abs_percent_error,mae,spearman_correlation,plt, dummy, dummy # returns 9 (unpacking same as classification)
        elif self._ml_type == 'classification':
            return self.get_test_scoring_classification(ws,target_column_name,test_ds,fitted_model,train_run,aml_model,multiclass,positive_label) # returns 9