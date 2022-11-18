from abc import ABCMeta, abstractmethod

# Abstract base class - do not instantite this. Use the concrete class ESMLSplitter or your own class instead.
class IESMLPipelineStepMap:
    __metaclass__ = ABCMeta

    IN_2_GOLD_TRAIN_notebook_mapping = None
    IN_2_GOLD_SCORE_notebook_mapping = None
    _compute_type_py="py"
    _compute_type_dbx="dbx"
    _compute_type_synapse_spark="synapse"
    _compute_type_spark_other="spark2"

    @classmethod
    def version(self): return "1.4"
    
    ###
    # returns: IN_2_GOLD_TRAIN_notebook_mapping, IN_2_GOLD_SCORE_notebook_mapping
    # compute_type: dbx, synapse1, spark2
    ###
    @abstractmethod
    def get_train_map(self, dataset_folder_names):

        nb1 = "Workspace/esml_my/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER
        script = "in2silver_ds02_diabetes.py" # Add/CPU: Since static date_folder, "lookup data", but keep CPU
        #_nb3 = "Workspace/esml_my/dev/project/11_diabetes_model_reg/M11/13_in2silver_ds01_diabetes" # Ignore in map: Use CPU since small/mediuem/large data, and use default global date_folder
        nb4 = "Workspace/esml_my/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold" # Databricks: MERGE_2_GOLD
        #_nb5 = "notebook SPLIT and Register datasets" # Python/CPU: since easier/built into ESML | Databricks:SPLIT & REGISTER DATASETS
        nb6 = "Workspace/esml_my/dev/project/11_diabetes_model_reg/M11/30_train_register" #Databricks: TRAIN & REGISER model: Here we need to register and TAG modela according to ESML / MLFlow
        #_nb7 = "notebook MLOps:calc testset scoring. compare, promote" # Python/CPU: since easier/built into ESML 

        ### LETS START to switch out only 4 steps [nb1,nb4,nb4,nb6] to DATABRICKS steps
        step1 = 'in2silver_{}'.format(dataset_folder_names[0])
        step2 = 'in2silver_{}'.format(dataset_folder_names[1])
        step4 = 'silver_merged_2_gold'
        step5 = 'train_split_and_register'
        step6 = 'train_manual'
        #dataset_folder_names_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(dataset_folder_names)
        star_csv = "*.csv"
        star_parquet = "*.parquet"


        self.IN_2_GOLD_TRAIN_notebook_mapping= [
           #{'step_name': step1, 'code': nb1,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':dataset_folder_names,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'}, # IN_2_SILVER note: date_folder_override: Showcase static lookup data. Overrides main date_folder, which all other steps reads from
           #{'step_name': step2, 'code': script,'compute_type':self._compute_type_py, 'date_folder_or': '2021-01-01 10:35:01.243860', 'dataset_folder_names':dataset_folder_names,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'},
           #{'step_name': step4,'code': nb4,'compute_type':self._compute_type_dbx, 'date_folder_or': None,'dataset_folder_names':dataset_folder_names,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'}, # MERGE 2 GOLD
           #{'step_name': step6,'code': nb6,'compute_type':self._compute_type_dbx,'date_folder_or': None, 'dataset_folder_names':dataset_folder_names,'compute_name':'s-p002-aml-rt91','cluster_id':'0912-204847-wimps924'} # TRAIN & Register model
        ]

        return self.IN_2_GOLD_TRAIN_notebook_mapping


    ###
    # returns: IN_2_GOLD_SCORE_notebook_mapping
    ###
    @abstractmethod
    def get_inference_map(self, dataset_folder_names):

        nb1 = "Workspace/esml_my/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER
        script = "in2silver_ds02_diabetes.py" # Add/CPU: Since static date_folder, "lookup data", but keep CPU
        nb4 = "notebook MERGE silver to GOLD"# Databricks: MERGE_2_GOLD
        _nb7a = "Workspace/esml_my/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold" # Python/CPU: since easier/built into ESML (AML Batch scoring pipeline)
        _nb7b = "notebook Deploy model to AKS" # Python/CPU: since easier/built into ESML (AKS-endpoint / AML Batch scoring pipeline)

        step1 = 'in2silver_{}'.format(dataset_folder_names[0])
        step2 = 'in2silver_{}'.format(dataset_folder_names[1])
        step4 = 'silver_merged_2_gold'
        #dataset_folder_names_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(dataset_folder_names)
        star_csv = "*.csv"
        star_parquet = "*.parquet"

        self.IN_2_GOLD_SCORE_notebook_mapping = [

        ]

        return self.IN_2_GOLD_SCORE_notebook_mapping

    #
    # Good method to run, to verify that your map looks good.
    # Note: The key's should look like the python filenames in the snapshot folder 'M11". Example 'in2silver_ds01_diabetes.py' or 'in2silver_ds01_diabetes.dbx' if Databricks compute
    #
    def print(self, a_map):
        for m in a_map:
            keys = m.keys()
            for k in keys:
                print(k,':', m[k])
            print(" ")
    
    def has_dbx(self,map):
        has_dbx = False
        for m in map:
            if(m['compute_type'] == 'dbx'):
                has_dbx = True
                break
        return has_dbx

    def get_all_dbx_compute_cluster_map(self,map):
        all_unique_dbx_ids = {}
        names = set()
        for m in map:
            if(m['compute_type'] == 'dbx' and m['cluster_id'] is not None):
                if (m['cluster_id'] not in names):
                    names.add(m['cluster_id'])
                    #a_pair = {m['compute_name']: m['cluster_id']}
                    all_unique_dbx_ids[m['compute_name']] = m['cluster_id']

        return all_unique_dbx_ids
    def get_all_compute_clusters(self,map,compute_type="dbx"):
        all_unique_ids = []
        for m in map:
            if(m['compute_type'] == compute_type and m['compute_name'] is not None and m['compute_name'] not in all_unique_ids):
                all_unique_ids.append(m['compute_name'])

        return all_unique_ids

    def get_dbx_map_step(self,map, dataset_name):
        has_dbx = False
        step_name = None
        map_step = None
        for m in map:
            if(m['compute_type'] == 'dbx'):
                if('in2silver' in m['step_name'] and dataset_name in m['step_name']):
                    has_dbx = True
                    step_name = m['step_name']
                    map_step=m
                    break
                else:
                    has_dbx = False

        return has_dbx,step_name,map_step