from abc import ABCMeta, abstractmethod

class IESMLModelCompare:
    __metaclass__ = ABCMeta

    _setting_path = ""
    _esml_controller = None
    _debug_always_promote_model = False

    def __init__(self, setting_path = "",debug_always_promote_model=False):
        self._setting_path = setting_path
        self._debug_always_promote_model = debug_always_promote_model

    @classmethod
    def version(self): return "1.4"

    ###
    # properties
    ###
    @property
    @abstractmethod
    def esml_controller(self):
        return self._esml_controller

    @esml_controller.setter
    def esml_controller(self, esml_controller):
        self._esml_controller = esml_controller

    ###
    # Abstract stuff (with a ESML default implementation you can override)
    ###
    
     #if (target_environment == "dev" & p.dev_test_prod = "dev") -> compare againt  stage "dev" -> Should be same if no difference is made
     #if (target_environment== "test" & p.dev_test_prod = "dev") -> compare againt next stage "test" -> should always be better in TEST, since longer traininng run
     #if (target_environment == "prod" & & p.dev_test_prod = "test") -> compare "test" againt next stage "prod"  -> TEST and PROD might be same
     #if (target_environment == "prod" & & p.dev_test_prod = "dev") -> Exception! Should always use corret staging cycle. Not "jump over"
    
    ###
    #returns: promote_new_model,source_model_name,new_run_id,target_model_name, target_best_run_id,target_workspace,source_model
    ##
    @abstractmethod
    def compare_scoring_current_vs_new_model(self, new_run_id, current_ws,current_environment, target_environment,target_workspace, experiment_name): raise NotImplementedError


    ###
    # Implemented stuff
    ###
    
    def get_metric_mappings(self):
        metric_map_regression = {
            "RMSE_promote_weight": "normalized_root_mean_squared_error",
            "R2_promote_weight": "r2_score",
            "MAPE_promote_weight": "mean_absolute_percentage_error",
            "MAE_promote_weight": "normalized_mean_absolute_error",
            "Spearman_promote_weight": "spearman_correlation"
        }

        metric_map_classification = {
            "AUC_promote_weight": "AUC_weighted",
            "Accuracy_promote_weight": "accuracy",
            "Precision_promote_weight": "precision_score_weighted",
            "Recall_promote_weight": "recall_score_weighted",
            "F1_promote_weight": "f1_score_weighted",
            "Log_loss_weight":"log_loss",
            "Matthews_promote_weight": "matthews_correlation"
        }
        return metric_map_regression, metric_map_classification

    def regression_print_metrics(self,best_run, model):
        #metrics = best_run.get_metrics()
        metrics = self.get_metrics_regression(best_run,model)

        rmse = metrics.get('normalized_root_mean_squared_error',-999.0)
        r2 = metrics.get('r2_score', -999.0)
        spearman = metrics.get('spearman_correlation', -999.0)
        mape = metrics.get('mean_absolute_percentage_error',-999.0)
        _mae = metrics.get('normalized_mean_absolute_error', -999.0)

        all_metrics = {}
        all_metrics["normalized_root_mean_squared_error"] = rmse
        all_metrics["r2_score"] = r2
        all_metrics["mean_absolute_percentage_error"] = mape
        all_metrics["normalized_mean_absolute_error"] = _mae
        all_metrics["spearman_correlation"] = spearman

        print("RMSE (normalized_root_mean_squared_error): " + str(rmse))
        print("MAPE (Mean average Percentage Error): " + str(mape))
        print("MAE (normalized_mean_absolute_error): " + str(_mae))
        print("R2 (r2_score): " + str(r2))
        print("Spearman (spearman_correlation): " + str(spearman))
        
        return all_metrics

    def classification_print_metrics(self,best_run,model):
        metrics = self.get_metrics_classification(best_run,model)

        auc = metrics.get('AUC_weighted', -1.0)
        accuracy = metrics.get('accuracy', -1.0)
        precision = metrics.get('precision_score_weighted', -1.0)
        precision_avg = metrics.get('average_precision_score_weighted', -1.0) # No Testset scoring
        recall = metrics.get('recall_score_weighted', -1.0)
        f1_score = metrics.get('f1_score_weighted', -1.0)
        log_loss = metrics.get('log_loss', -1.0) # No Testset scoring
        mathews = metrics.get('matthews_correlation', -1.0)

        all_metrics = {}
        all_metrics["AUC_weighted"] = auc
        all_metrics["accuracy"] = accuracy
        all_metrics["precision_score_weighted"] = precision
        all_metrics["average_precision_score_weighted"] = precision_avg
        all_metrics["recall_score_weighted"] = recall
        all_metrics["f1_score_weighted"] = f1_score
        all_metrics["log_loss"] = log_loss
        all_metrics["matthews_correlation"] = mathews

        print("AUC (AUC_weighted): " + str(auc))
        print("Accuracy: " + str(accuracy))
        print("Precision (precision_score_weighted): " + str(precision))
        print("Recall (recall): " + str(recall))
        print("F1 Score (1.0 is good): " + str(f1_score))
        print("Logg loss (0.0 is good): " + str(log_loss))
        print("matthews_correlation (1.0 is good): " + str(mathews))

        return all_metrics

    def get_metrics_classification(self,best_run, model):
        metrics = {}
        if("test_set_Accuracy" in model.tags): # First Try: TEST SET Scoring from TAGS
            print("INFO: Using ESML TEST_SET SCORING, since tagged on MODEL - using this to compare SCORING")
            
            metrics["accuracy"] = model.tags["test_set_Accuracy"]
            metrics["AUC_weighted"] = model.tags["test_set_ROC_AUC"]
            metrics["precision_score_weighted"] = model.tags["test_set_Precision"]
            metrics["recall_score_weighted"] = model.tags["test_set_Recall"]
            metrics["f1_score_weighted"] = model.tags["test_set_F1_Score"]
            metrics["matthews_correlation"] = model.tags["test_set_Matthews_Correlation"]
            # Missing: log_loss, average_precision_score_weighted (same loss for both..)
            metrics["log_loss"] = -1
            metrics["average_precision_score_weighted"] = -1

        elif (best_run is not None):
            print("Warning: Falling back o use AutoML validation scoring when comparing. Run 'ESMLTestScoringFactory(p).get_test_scoring_7_classification()' use TEST_SET SCORING when comparing")
            metrics = best_run.get_metrics() # Backup, use Validation scoring, e.g. no TestSet scoring is calculated&tagged on model
        return metrics

    def get_metrics_regression(self,best_run, model):
        metrics = {}
        if("test_set_R2" in model.tags): # First Try: TEST SET Scoring from TAGS 
            print("INFO: Using ESML TEST_SET SCORING, since tagged on MODEL - using this to compare SCORING")
            
            metrics["normalized_root_mean_squared_error"] = model.tags["test_set_RMSE"]
            metrics["r2_score"] = model.tags["test_set_R2"]
            metrics["mean_absolute_percentage_error"] = model.tags["test_set_MAPE"]
            metrics["spearman_correlation"] = model.tags["test_set_Spearman_Correlation"]
            
            #Missing: normalized_mean_absolute_error
            metrics["normalized_mean_absolute_error"] = -1

        elif (best_run is not None):
            print("Warning: Falling back o use AutoML validation scoring when comparing. Run 'ESMLTestScoringFactory(p).get_test_scoring_4_regression()' to use TEST_SET SCORING when comparing")
            metrics = best_run.get_metrics() # Backup, use Validation scoring, e.g. no TestSet scoring is calculated&tagged on model
        return metrics
