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
    _all_dbx_envs = None
    _step_filter_whitelist = None

    def __init__(self,step_filter_whitelist, all_dbx_envs):
        self._step_filter_whitelist = step_filter_whitelist
        self._all_dbx_envs = all_dbx_envs

    @classmethod
    def version(self): return "1.4"

    ###
    # properties
    ###
    @property
    def all_dbx_envs(self):
        return self._all_dbx_envs
    
    ###
    # returns: IN_2_GOLD_TRAIN_notebook_mapping, IN_2_GOLD_SCORE_notebook_mapping
    # compute_type: dbx, synapse1, spark2
    ###
    def get_train_map(self, dataset_folder_names,step_filter_whitelist=None):

        self.IN_2_GOLD_TRAIN_notebook_mapping = self.your_train_map(dataset_folder_names)
        self.IN_2_GOLD_TRAIN_notebook_mapping = self.use_only_whitelisted_steps()
        return self.IN_2_GOLD_TRAIN_notebook_mapping

    ###
    # returns: IN_2_GOLD_SCORE_notebook_mapping
    ###
    def get_inference_map(self, dataset_folder_names):

        self.IN_2_GOLD_SCORE_notebook_mapping = self.your_inferenc_map(dataset_folder_names)
        self.IN_2_GOLD_SCORE_notebook_mapping = self.use_only_whitelisted_steps()
        return self.IN_2_GOLD_SCORE_notebook_mapping

    @abstractmethod
    def your_train_map(self,dataset_folder_names):

        #################### TODO 4 YOU - This is only an example implementation! ################################
        script = "in2silver_ds02_other.py" # Add/CPU: Since static date_folder, "lookup data", but keep CPU

        nb1 = "/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds01_diabetes" #Override/Databricks: IN_2_SILVER
        nb2 = "/esml/dev/project/11_diabetes_model_reg/M11/10_in2silver_ds02_other"
        nb3 = "/esml/dev/project/11_diabetes_model_reg/M11/20_merge_2_gold" # # Databricks: MERGE_2_GOLD (or Ignore in map: Use CPU since small/mediuem/large data, and use default global date_folder)
        nb4 = "/esml/dev/project/11_diabetes_model_reg/M11/21_split_GOLD_and_register_datasets" # Databricks: split dataset
        nb5 = "/esml/dev/project/11_diabetes_model_reg/M11/30_train_register" #Databricks: TRAIN & REGISER model: Here we need to register and TAG modela according to ESML / MLFlow

        step1 = esml_snapshot_step_names.in2silver_template.value.format(dataset_folder_names[0])
        step2 = esml_snapshot_step_names.in2silver_template.value.format(dataset_folder_names[1])
        step3 = esml_snapshot_step_names.silver_merged_2_gold.value
        step4 = esml_snapshot_step_names.train_split_and_register.value
        step5 = esml_snapshot_step_names.train_manual.value

        star_csv = "*.csv"
        star_parquet = "*.parquet"
        # ds01_
        only_one_folder_name = [dataset_folder_names[0]]
        ds_01_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(only_one_folder_name)
        # ds02_
        only_one_folder_name = [dataset_folder_names[1]]
        ds_02_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(only_one_folder_name)

        # silver_merged_2_gold
        all_dataset_folder_names_str = IESMLPipelineStepMap.get_dataset_folders_as_csv_string(dataset_folder_names)

        # NB! cluster_id / Compute name sensitive. It can include letters, digits and dashes. Need to be `2 and 16 characters in length`
        your_train_map = [
           #{'step_name': step1, 'code': nb1,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':ds_01_str,"dataset_filename_ending":star_csv,'compute_name':'x-p002-aml-rt91','cluster_id':'1234-200000-wimps924'}, # IN_2_SILVER note: date_folder_override: Showcase static lookup data. Overrides main date_folder, which all other steps reads from
           #{'step_name': step2, 'code': nb2,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':ds_02_str,"dataset_filename_ending":star_csv,'compute_name':'x-p002-aml-rt91','cluster_id':'0912-200000-wimps924'},
           #{'step_name': step3, 'code': nb3,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':all_dataset_folder_names_str,"dataset_filename_ending":star_parquet,'compute_name':'x-p002-aml-rt91','cluster_id':'1234-200000-wimps924'},
           #{'step_name': step4, 'code': nb4,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':"","dataset_filename_ending":star_parquet,'compute_name':'s-p002-aml-rt91','cluster_id':'1234-200000-wimps924'},
           #{'step_name': step5, 'code': nb5,'compute_type':self._compute_type_dbx,'date_folder_or': None,'dataset_folder_names':"","dataset_filename_ending":star_parquet,'compute_name':'s-p002-aml-rt91','cluster_id':'1234-200000-wimps924'},
        ]

        #################### TODO 4 YOU - END ################################
        return your_train_map

    @abstractmethod
    def your_inferenc_map(self,dataset_folder_names,step_filter_whitelist=None):

        #################### TODO 4 YOU - This is only an example implementation! ################################

        # NB! cluster_id / Compute name sensitive. It can include letters, digits and dashes. Need to be `2 and 16 characters in length`
        your_infernece_map = [

        ]
         #################### TODO 4 YOU - END ################################
        return your_infernece_map

    def use_only_whitelisted_steps(self):
        newMapping = []
        if(self._step_filter_whitelist is not None and len(self._step_filter_whitelist) > 0):
           counter = 0
           for white_step_name in self._step_filter_whitelist:
               step_dic = self.IN_2_GOLD_TRAIN_notebook_mapping[counter]
               if(len(step_dic)> 0):
                    if(white_step_name == step_dic['step_name']):
                        newMapping.append(step_dic)
               else:
                    break
               counter = counter+1
        else:
            newMapping = self.IN_2_GOLD_TRAIN_notebook_mapping
            
        return newMapping

    @staticmethod
    def get_dataset_folders_as_csv_string(dataset_folder_names):
        if (dataset_folder_names is not None and len(dataset_folder_names) > 0):
            dataset_folder_names = ','.join(dataset_folder_names)
        else:
            dataset_folder_names = ""
        return dataset_folder_names
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

    def get_dbx_map_step(self,map, dataset_name_or_step_name):
        has_dbx = False
        step_name = None
        map_step = None
        for m in map:
            if(m['compute_type'] == 'dbx'):
                if('in2silver' in m['step_name'] and dataset_name_or_step_name in m['step_name']):
                    has_dbx = True
                    step_name = m['step_name']
                    map_step=m
                    break
                if(dataset_name_or_step_name == m['step_name']):
                    has_dbx = True
                    step_name = m['step_name']
                    map_step=m
                    break

        return has_dbx,step_name,map_step


from enum import Enum
class esml_snapshot_step_names(str, Enum):
    in2silver_template = "in2silver_{}",
    silver_merged_2_gold = "silver_merged_2_gold",
    train_split_and_register = "train_split_and_register",
    train_manual = "train_manual",
    scoring_gold = "scoring_gold",