import sys
sys.path.append("..")
from esmlrt.interfaces.iESMLPipelineStepMap import IESMLPipelineStepMap
from esmlrt.interfaces.iESMLPipelineStepMap import esml_snapshot_step_names

# Optional: Only needed to be implemented/used if overriding compute for certain steps, example SparkSteps. Override with YOUR implementation of the the abstract class IESMLPipelineStepMap
class ESMLPipelineStepMap(IESMLPipelineStepMap):
    def __init__(self, step_filter_whitelist = None, all_dbx_envs = None):
        if(all_dbx_envs is None):

            dev_rg = 'your-project-resource-group'
            dev_workspace = 'your-databricks-workspace-name'

            all_dbx_envs = {
                'dev': {'resource_group': dev_rg, 'workspace_name':dev_workspace},
                'test': {'resource_group': 'xyz-xyz-esml-project001-weu-test-001-rg', 'workspace_name': 'z'},
                'prod': {'resource_group': 'xyz-xyz-esml-project001-weu-prod-001-rg', 'workspace_name': 'z'}
            }
        super().__init__(step_filter_whitelist,all_dbx_envs)

    ###
    # returns: IN_2_GOLD_TRAIN_notebook_mapping, IN_2_GOLD_SCORE_notebook_mapping
    # compute_type: dbx, synapse1, spark2
    ###
    def your_train_map(self, dataset_folder_names):

        script = "in2silver_ds02_other.py" # Add/CPU: Since static date_folder, "lookup data", but keep CPU

        # Just FYI - Below is a correct path if you do not have connected Azure Databricks to "Repos", e.g. if you are at "Workspace"
        nb1_not_GIT_connected_correct_url = "/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER

        # TODO 4 YOU - Hower over notebooks name and copy/paste to get the below prefix. You cannot get this by "righ click on notebook/copy file path relative to root"
        prefix_error_1_need_to_remove_Workpace = "Workspace/Repos/yourname@yourorg/adoinfo/notebook_databricks"
        prefix_error_2_need_to_add_forward_slash = "Repos/yourname@yourorg/adoinfo/notebook_databricks"
        prefix_correct = "/Repos/yourname@yourorg/adoinfo/notebook_databricks"

        nb1 = prefix_correct+"/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER
        nb2 = prefix_correct+"/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds02_other"
        nb3 = prefix_correct+"/esml/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold" # # Databricks: MERGE_2_GOLD (or Ignore in map: Use CPU since small/mediuem/large data, and use default global date_folder)
        nb4 = prefix_correct+"/esml/dev/project/11_diabetes_model_reg/M11/21_split_GOLD_and_register_datasets" # Databricks: split dataset
        nb5 = prefix_correct+"/esml/dev/project/11_diabetes_model_reg/M11/30_train_register" #Databricks: TRAIN & REGISER model: Here we need to register and TAG modela according to ESML / MLFlow

        step1 = esml_snapshot_step_names.in2silver_template.value.format(dataset_folder_names[0])
        step2 = esml_snapshot_step_names.in2silver_template.value.format(dataset_folder_names[1])
        step3 = esml_snapshot_step_names.silver_merged_2_gold.value
        step4 = esml_snapshot_step_names.train_split_and_register.value
        step5 = esml_snapshot_step_names.train_manual.value

        star_csv = "*.csv"
        star_parquet = "*.parquet"
        # ds01_
        only_one_folder_name = [dataset_folder_names[0]]
        ds_01_in2silver_dataset_folder_names_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(only_one_folder_name)
        # ds02_
        only_one_folder_name = [dataset_folder_names[1]]
        ds_02_in2silver_dataset_folder_names_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(only_one_folder_name)

        # silver_merged_2_gold
        all_dataset_folder_names_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(dataset_folder_names)

        my_dbx_cluster_friendly = 's-p001-m01-rt91' # note needs to be short <16 chars. Feel free to use this name, or rename for your cluster in Databricks
        my_dbx_cluster_url_name = '1234-333666-wimps924' # See web browser URL when having cluster selected
        TRAIN_notebook_mapping= [
           {'step_name': step1, 'code': nb1,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':ds_01_in2silver_dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':my_dbx_cluster_friendly,'cluster_id':my_dbx_cluster_url_name}, # IN_2_SILVER note: date_folder_override: Showcase static lookup data. Overrides main date_folder, which all other steps reads from
           {'step_name': step2, 'code': nb2,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':ds_02_in2silver_dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':my_dbx_cluster_friendly,'cluster_id':my_dbx_cluster_url_name},
           {'step_name': step3, 'code': nb3,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':all_dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':my_dbx_cluster_friendly,'cluster_id':my_dbx_cluster_url_name},
           {'step_name': step4, 'code': nb4,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':"","dataset_filename_ending":star_csv,'compute_name':my_dbx_cluster_friendly,'cluster_id':my_dbx_cluster_url_name},
           {'step_name': step5, 'code': nb5,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':"","dataset_filename_ending":star_csv,'compute_name':my_dbx_cluster_friendly,'cluster_id':my_dbx_cluster_url_name},
        ]

        return TRAIN_notebook_mapping


    ###
    # returns: IN_2_GOLD_SCORE_notebook_mapping
    ###
    def your_inferenc_map(self, dataset_folder_names):

       nb1 = "/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER
       script = "in2silver_ds02_diabetes.py" # Add/CPU: Since static date_folder, "lookup data", but keep CPU compute
       nb3 = "/esml/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold"
       _nb7a = "scoring gold" # Python/CPU: since easier/built into ESML (in the AML Batch scoring pipeline)
       _nb7b = "notebook Deploy model to AKS" # Python/CPU: since easier/built into ESML (AKS-endpoint / AML Batch scoring pipeline)

       step1 = esml_snapshot_step_names.in2silver_template.value.format(dataset_folder_names[0])
       step3 = esml_snapshot_step_names.silver_merged_2_gold.value
       #step5 = esml_snapshot_step_names.scoring_gold

       dataset_folder_names_str = ESMLPipelineStepMap.get_dataset_folders_as_csv_string(dataset_folder_names)
       star_csv = "*.csv"
       star_parquet = "*.parquet"

       my_dbx_cluster_friendly = 's-p001-m01-rt91' # note needs to be short <16 chars
       my_dbx_cluster_url_name = '1234-333666-wimps924' # See web browser URL when having cluster selected
       INFERENCE_notebook_mapping = [
           {'step_name': step1, 'code': nb1,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':my_dbx_cluster_friendly, 'cluster_id':my_dbx_cluster_url_name}, # IN_2_SILVER note: date_folder_override: Showcase static lookup data. Overrides main date_folder, which all other steps reads from
           #{'step_name': step2,  'code': script,'compute_type':self._compute_type_py, 'date_folder_or': '2021-01-01 10:35:01.243860','compute_name':my_dbx_cluster_friendly, 'cluster_id':my_dbx_cluster_url_name},
           {'step_name': step3, 'code': nb3,'compute_type':self._compute_type_dbx, 'date_folder_or': None,'dataset_folder_names':dataset_folder_names_str,"dataset_filename_ending":star_csv,'compute_name':my_dbx_cluster_friendly, 'cluster_id':my_dbx_cluster_url_name} # MERGE 2 GOLD
           #Note: SCORE GOLD & SAVE - is done by ESML PythonscriptStep in pipeline
       ]

       return INFERENCE_notebook_mapping