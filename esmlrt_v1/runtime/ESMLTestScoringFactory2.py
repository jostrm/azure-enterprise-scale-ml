from ctypes import ArgumentError
import sys
import os
from datetime import datetime
from azureml.core.model import Model
# sys.path.append("..")
from ..baselayer.ml import get_4_regression_metrics,get_7_classification_metrics
from ..interfaces.iESMLTestScoringFactory import IESMLTestScoringFactory
#import mlflow

class ESMLTestScoringFactory(IESMLTestScoringFactory):

    def __init__(self,ml_type):
        super().__init__(ml_type)
        #mlflow.autolog()
    ###
    # Pass either a Run, or a Model(). If Run, this superseeds Model
    # Tip: Prefer to pass Run() rather than Model(), since the plot graphics can only be uploaded on a Run(), and not a Model()
    ###
    def get_test_scoring_regression(self,ws,label,GoldTest,fitted_model,run=None, aml_model=None):

        source_best_run = None
        model = None
        if(run is not None and aml_model is not None):
            print("ESML info: get_test_scoring_regression: RUN exists, Model exists with name {}".format(aml_model.name))
            model = aml_model
            source_best_run = run
        elif(run is not None):
            source_best_run = run
            if(aml_model is None):
                model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
                model = Model(ws, model_name)
            else:
                model = aml_model
        elif(aml_model is not None):
            model = aml_model
        else:
            raise ArgumentError("run is None! Cannot get model name. Also aml_model parameter is None")
            #experiment, model,source_best_run, best_run,fitted_model = p.get_best_model_and_run_via_experiment_name() # Looks at Azure

        fitted_model = fitted_model
        test_set_pd =  GoldTest.to_pandas_dataframe()
        rmse, r2, mean_abs_percent_error,mae, spearman_correlation,plt = get_4_regression_metrics(test_set_pd, label,fitted_model)
        
        print("rmse is:{}".format(rmse))

        date_time = datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
        ds = GoldTest
        tags = ds.tags
        if(tags is None):
            tags = {} # Create new dictionary

        tags["RMSE"] = "{:.6f}".format(rmse)
        tags["R2"] = "{:.6f}".format(r2)
        tags["MAPE"] = "{:.6f}".format(mean_abs_percent_error)
        tags["Spearman_Correlation"] = "{:.6f}".format(spearman_correlation)
        tags["esml_time_updated"] = "{}".format(date_time)
        tags["ml_type"] = self._ml_type
        ds = ds.add_tags(tags = tags)

        model.tags["test_set_RMSE"] = "{:.6f}".format(rmse)
        model.tags["test_set_R2"] = "{:.6f}".format(r2)
        model.tags["test_set_MAPE"] = "{:.6f}".format(mean_abs_percent_error)
        model.tags["test_set_Spearman_Correlation"] = "{:.6f}".format(spearman_correlation)

        model.tags["esml_time_updated"] = "{}".format(date_time)
        model.tags["ml_type"] = self._ml_type
        model.add_tags(tags = model.tags)
        
        if(source_best_run is not None):
           source_best_run.log_image("ESML_GOLD_TestSet_AcutalPredicted", plot=plt)
        
        if (plt is not None):
            pass
            #####plt.savefig("ESML_GOLD_TestSet_AcutalPredicted.png")
            #figure = plt.gcf()
            #mlflow.log_figure(figure, "ESML_GOLD_TestSet_AcutalPredicted.png")

        return model,rmse, r2, mean_abs_percent_error,mae,spearman_correlation,plt
    
    ###
    # Pass either a Run, or a Model(). If Run, this superseeds Model
    # Tip: Prefer to pass Run() rather than Model(), since the plot graphics can only be uploaded on a Run(), and not a Model()
    ###
    def get_test_scoring_classification(self,ws,target_column_name,GoldTest,fitted_model,run=None,aml_model=None,multiclass=None,positive_label=None):
        
        source_best_run = None
        model = None
        if((run is not None) and (aml_model is not None)):
            print("ESML info: get_test_scoring_classification: RUN exists, Model exists with name {}".format(aml_model.name))
            model = aml_model
            source_best_run = run
        elif(run is not None):
            print("ESML info: get_test_scoring_classification: RUN exists, lets get a model from that run")
            source_best_run = run
            model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
            model = Model(ws, model_name)
        elif(aml_model is not None):
            print("ESML info: get_test_scoring_classification: RUN does not exists, aml_model is passed as a parameter")
            model = aml_model
        else:
            raise ArgumentError("run is None! Cannot get model name. Also aml_model parameter is None")
            #experiment, model,source_best_run, best_run,fitted_model = p.get_best_model_and_run_via_experiment_name() # Looks at Azure
        
        fitted_model = fitted_model
        ds = GoldTest
        test_set_pd =  ds.to_pandas_dataframe()
        labels = test_set_pd[target_column_name].unique()
        lbl_count = len(labels)
        if lbl_count>2: # Multi class classification
            if(multiclass is None):
                multiclass = 'ovr' # Set default if user forgotten...that it is multi-class classification

        auc,accuracy,f1, precision,recall,matrix,matthews, plt = get_7_classification_metrics(test_set_pd, target_column_name,fitted_model,multiclass,positive_label)

        tags = ds.tags
        if(tags is None):
            tags = {} # Create new dictionary

        # 1) Log on the TEST_SET used
        if(auc is not None):
            tags["ROC_AUC"] = "{:.6f}".format(auc)
        else:
            tags["ROC_AUC"] = "-"

        tags["Accuracy"] = "{:.6f}".format(accuracy)

        f1_str = None
        prec_str = None
        rec_str = None
        if(multiclass is not None):
            f1_str =  str(list(map('{:.6f}'.format,f1))).replace("'","")
            prec_str = str(list(map('{:.6f}'.format,precision))).replace("'","")
            rec_str = str(list(map('{:.6f}'.format,recall))).replace("'","")
        else:
            f1_str = "{:.6f}".format(f1)
            prec_str = "{:.6f}".format(precision)
            rec_str = "{:.6f}".format(recall)
            labels = ds.to_pandas_dataframe()[target_column_name].unique()

        if(f1_str is None):
            f1_str = ""
        if(prec_str is None):
            prec_str = ""
        if(rec_str is None):
            rec_str = ""
        
        date_time = datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
        
        tags["F1_Score"] = f1_str
        tags["Precision"] = prec_str
        tags["Recall"] = rec_str
        tags["Matthews_Correlation"] = "{:.6f}".format(matthews)
        tags["Confusion_Matrix"] = str(matrix)
        tags["esml_time_updated"] = "{}".format(date_time)
        tags["ml_type"] = self._ml_type
        ds = ds.add_tags(tags = tags)

        #2) Also, log on MODEL
        if(auc is not None):
            model.tags["test_set_ROC_AUC"] =  "{:.6f}".format(auc)
        else:
            model.tags["test_set_ROC_AUC"] =  "multiclass classification - see multilabel_confusion_matrix instead"

        model.tags["test_set_Accuracy"] =  "{:.6f}".format(accuracy)
        model.tags["test_set_F1_Score"] =  f1_str
        model.tags["test_set_Precision"] =  prec_str
        model.tags["test_set_Recall"] =  rec_str
        model.tags["test_set_Matthews_Correlation"] =  "{:.6f}".format(matthews)
        model.tags["test_set_CM"] =  str(matrix)
        model.tags["esml_time_updated"] = "{}".format(date_time)
        model.tags["ml_type"] = self._ml_type
        model.add_tags(tags = model.tags)

        # 3) Also, log on RUN
        #source_best_run.tag("ESML TEST_SET Scoring", "Yes, including plot: ROC")
        if(plt is not None and source_best_run is not None):
            print("Saving plot to Azure ML - best run {}".format(source_best_run.id))
            source_best_run.log_image(name="ESML_GOLD_TestSet_ROC", plot=plt)

        return model,auc,accuracy, f1, precision,recall,matrix,matthews,plt