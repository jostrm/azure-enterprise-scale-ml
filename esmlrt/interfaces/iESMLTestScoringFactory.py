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

    @ml_type.setter
    def ml_type(self, ml_type_in):
        self._ml_type = ml_type_in

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
    # GENERIC: returns:7 or 9 metric values + model with tags, equals 9 values to unpack
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

    def print_test_scoring(self,val_1,val_2,val_3, val_4, val_5, val_6, val_7, val_8=None):
        name_val_map = IESMLTestScoringFactory.get_name_value_map(val_1,val_2,val_3, val_4, val_5, val_6, val_7, val_8=None)
        my_map = name_val_map[self._ml_type]
        i = 0
        array_len = len(my_map)
        for m in my_map:
            if(i > (array_len-1)):
                break
            
            name = my_map[i]
            val = my_map[i+1]
            i = i+2
            print("{} = {}".format(name,val))

    @staticmethod
    def get_name_value_map(val_1,val_2,val_3, val_4, val_5, val_6, val_7, val_8=None):
        name_val_map = {
            "classification": ["AUC", val_1, "Accuracy", val_2, "F1 Score", val_3,"Precision",val_4, "Recall",val_5,"Mathews correlation", val_6, "Confusion Matrix", val_7 ]
            ,"regression": ["RMSE", val_1,"R2",val_2, "MAPE", val_3, "MAE", val_4,"Spearman correlation",val_5]
        }
        return name_val_map