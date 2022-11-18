import sys
sys.path.append("..")
from esmlrt.interfaces.iESMLPipelineStepMap import IESMLPipelineStepMap

# Optional: Only needed to be implemented/used if overriding compute for certain steps, example SparkSteps. Override with YOUR implementation of the the abstract class IESMLPipelineStepMap
class ESMLPipelineStepMap(IESMLPipelineStepMap):
    def __init__(self):
        super().__init__()

    ###
    # returns: IN_2_GOLD_TRAIN_notebook_mapping, IN_2_GOLD_SCORE_notebook_mapping
    # compute_type: dbx, synapse1, spark2
    ###
    def get_train_map(self, dataset_folder_names):

        
        nb1 = "/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER
        nb1 = "/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes"
        script = "in2silver_ds02_diabetes.py" # Add/CPU: Since static date_folder, "lookup data", but keep CPU
        #_nb3 = "/esml_my/dev/project/11_diabetes_model_reg/M11/13_in2silver_ds01_diabetes" # Ignore in map: Use CPU since small/mediuem/large data, and use default global date_folder
        nb4 = "/esml/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold" # Databricks: MERGE_2_GOLD
        #_nb5 = "notebook SPLIT and Register datasets" # Python/CPU: since easier/built into ESML | Databricks:SPLIT & REGISTER DATASETS
        nb6 = "/esml/dev/project/11_diabetes_model_reg/M11/30_train_register" #Databricks: TRAIN & REGISER model: Here we need to register and TAG modela according to ESML / MLFlow
        #_nb7 = "notebook MLOps:calc testset scoring. compare, promote" # Python/CPU: since easier/built into ESML 

        ### LETS START to switch out only 4 steps [nb1,nb4,nb4,nb6] to DATABRICKS steps
        step1 = 'in2silver_{}'.format(dataset_folder_names[0])
        #step2 = 'in2silver_{}'.format(dataset_folder_names[1])
        step4 = 'silver_merged_2_gold'
        #step5 = 'train_split_and_register'
        step6 = 'train_manual'
        dataset_folder_names_str = self.get_dataset_folders_as_csv_string(dataset_folder_names)
        star_csv = "*.csv"
        star_parquet = "*.parquet"

        self.IN_2_GOLD_TRAIN_notebook_mapping= [
           {'step_name': step1, 'code': nb1,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'}, # IN_2_SILVER note: date_folder_override: Showcase static lookup data. Overrides main date_folder, which all other steps reads from
           #{'step_name': step2, 'code': script,'compute_type':self._compute_type_py, 'date_folder_or': '2021-01-01 10:35:01.243860', 'dataset_folder_names':dataset_folder_names,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'},
           {'step_name': step4,'code': nb4,'compute_type':self._compute_type_dbx, 'date_folder_or': None,'dataset_folder_names':dataset_folder_names_str,"dataset_filename_ending":star_parquet,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'}, # MERGE 2 GOLD
           {'step_name': step6,'code': nb6,'compute_type':self._compute_type_dbx,'date_folder_or': None, 'dataset_folder_names':dataset_folder_names_str,"dataset_filename_ending":star_parquet,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'} # TRAIN & Register model
        ]

        return self.IN_2_GOLD_TRAIN_notebook_mapping


    ###
    # returns: IN_2_GOLD_SCORE_notebook_mapping
    ###
    def get_inference_map(self, dataset_folder_names):

       nb1 = "/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER
       script = "in2silver_ds02_diabetes.py" # Add/CPU: Since static date_folder, "lookup data", but keep CPU
       nb4 = "notebook MERGE silver to GOLD"# Databricks: MERGE_2_GOLD
       _nb7a = "esml/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold" # Python/CPU: since easier/built into ESML (AML Batch scoring pipeline)
       _nb7b = "notebook Deploy model to AKS" # Python/CPU: since easier/built into ESML (AKS-endpoint / AML Batch scoring pipeline)

       step1 = 'in2silver_{}'.format(dataset_folder_names[0])
       step2 = 'in2silver_{}'.format(dataset_folder_names[1])
       step4 = 'silver_merged_2_gold'
       dataset_folder_names_str = self.get_dataset_folders_as_csv_string(dataset_folder_names)
       star_csv = "*.csv"
       star_parquet = "*.parquet"

       self.IN_2_GOLD_SCORE_notebook_mapping = [
           {'step_name': step1, 'code': nb1,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':'s-p002-aml-rt91', 'cluster_id':'0912-204847-wimps924'}, # IN_2_SILVER note: date_folder_override: Showcase static lookup data. Overrides main date_folder, which all other steps reads from
           #{'step_name': step2,  'code': script,'compute_type':self._compute_type_py, 'date_folder_or': '2021-01-01 10:35:01.243860','compute_name':'s-p002-aml-rt91', 'cluster_id':'0912-204847-wimps924'},
           {'step_name': step4, 'code': nb4,'compute_type':self._compute_type_dbx, 'date_folder_or': None,'dataset_folder_names':dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':'s-p002-aml-rt91', 'cluster_id':'0912-204847-wimps924'} # MERGE 2 GOLD
           #Note: SCORE GOLD & SAVE - is done by ESML PythonscriptStep in pipeline
       ]

       return self.IN_2_GOLD_SCORE_notebook_mapping