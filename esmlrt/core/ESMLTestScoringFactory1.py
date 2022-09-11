import sys
import os
from azureml.core.model import Model
sys.path.append(os.path.abspath("."))  # NOQA: E402
from baselayer.ml import get_4_regression_metrics,get_7_classification_metrics
from interfaces.iESMLTestScoringFactory import IESMLTestScoringFactory
from interfaces.iESMLController import IESMLController

# p.GoldTest, p.ws, p.get_best_model_and_run_via_experiment_name
#  model (tag scoring),source_best_run (tag image) ,fitted_model (calc scoring)

class ESMLTestScoringFactory(IESMLTestScoringFactory):
    project = None

    def __init__(self,project):
        if not isinstance(project, IESMLController): raise Exception('Bad interface. Should be IESMLController')
        if not IESMLController.version() == '1.4': raise Exception('Bad revision')
        self.project = project

    '''
    p.GoldTest, p.ws,get_best_model_and_run_via_experiment_name
    '''
    def get_test_scoring_4_regression(self, label,run=None, fitted_model=None):
        p = self.project
        if(run is not None):
            source_best_run = run
            model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
            model = Model(p.ws, model_name)
            fitted_model = fitted_model
        else:
            experiment, model,source_best_run, best_run,fitted_model = p.get_best_model_and_run_via_experiment_name() # Looks at Azure

        test_set_pd =  p.GoldTest.to_pandas_dataframe()
        rmse, r2, mean_abs_percent_error,mae, spearman_correlation,plt = get_4_regression_metrics(test_set_pd, label,fitted_model)

        ds = p.GoldTest
        tags = ds.tags
        tags["RMSE"] = "{:.6f}".format(rmse)
        tags["R2"] = "{:.6f}".format(r2)
        tags["MAPE"] = "{:.6f}".format(mean_abs_percent_error)
        tags["Spearman_Correlation"] = "{:.6f}".format(spearman_correlation)
        ds = ds.add_tags(tags = tags)

        #model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
        #model = Model(p.ws, model_name)
        model.tags["test_set_RMSE"] = "{:.6f}".format(rmse)
        model.tags["test_set_R2"] = "{:.6f}".format(r2)
        model.tags["test_set_MAPE"] = "{:.6f}".format(mean_abs_percent_error)
        model.tags["test_set_Spearman_Correlation"] = "{:.6f}".format(spearman_correlation)

        model.add_tags(tags = model.tags)
        
        #source_best_run.tag("ESML TEST_SET Scoring", "Yes, including plot: Actual VS Predicted")
        source_best_run.log_image("ESML_GOLD_TestSet_AcutalPredicted", plot=plt)

        return rmse, r2, mean_abs_percent_error,mae,spearman_correlation,plt
    
    '''
    p.active_model["label"],p.ws, p.GoldTest, p.get_best_model_and_run_via_experiment_name, 
    label,ws, GoldTest, model, fitted_model, source_best_run/run
    '''
    def get_test_scoring_7_classification(self, label_in=None,multiclass=None,positive_label=None, run=None, fitted_model=None):
        p = self.project

        label = p.active_model["label"]
        if(label_in is not None):
            label = label_in

        if(run is not None):
            source_best_run = run
            model_name = source_best_run.properties['model_name'] # we need Model() object instead of "fitted_model" -> which is a pipeline, "regression pipeline",
            model = Model(p.ws, model_name)
            fitted_model = fitted_model
        else:
            experiment, model,source_best_run, best_run,fitted_model = p.get_best_model_and_run_via_experiment_name() # Looks at Azure

        ds = p.GoldTest
        test_set_pd =  ds.to_pandas_dataframe()
        labels = test_set_pd[label].unique()
        lbl_count = len(labels)
        if lbl_count>2: # Multi class classification
            if(multiclass is None):
                multiclass = 'ovr' # Set default if user forgotten...that it is multi-class classification

        auc,accuracy,f1, precision,recall,matrix,matthews, plt = get_7_classification_metrics(test_set_pd, label,fitted_model,multiclass,positive_label)

        # 1) Log on the TEST_SET used
        if(auc is not None):
            ds.tags["ROC_AUC"] = "{:.6f}".format(auc)
        else:
            ds.tags["ROC_AUC"] = "-"

        ds.tags["Accuracy"] = "{:.6f}".format(accuracy)

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
            labels = ds.to_pandas_dataframe()[p.active_model["label"]].unique()

        if(f1_str is None):
            f1_str = ""
        if(prec_str is None):
            prec_str = ""
        if(rec_str is None):
            rec_str = ""
        
        tags = ds.tags
        tags["F1_Score"] = f1_str
        tags["Precision"] = prec_str
        tags["Recall"] = rec_str
        tags["Matthews_Correlation"] = "{:.6f}".format(matthews)
        tags["Confusion_Matrix"] = str(matrix)
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
        model.add_tags(tags = model.tags)

        # 3) Also, log on RUN
        #source_best_run.tag("ESML TEST_SET Scoring", "Yes, including plot: ROC")
        if(plt is not None):
            print("Saving plot to Azure ML - best run {}".format(source_best_run.id))
            source_best_run.log_image(name="ESML_GOLD_TestSet_ROC", plot=plt)

        return auc,accuracy, f1, precision,recall,matrix,matthews,plt