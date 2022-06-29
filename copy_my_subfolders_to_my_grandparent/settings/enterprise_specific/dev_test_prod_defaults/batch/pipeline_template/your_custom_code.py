import numpy as np
import pandas as pd

# You can create whatever code you like in this M11 folder, to reference in the "template scripts"
class In2GoldProcessor():
    _df = None
    _df_processed = None
    _your_other_thing = None
    
    def __init__(self, dataframe_in, other_thing=None):
        self._df=dataframe_in
        self._your_other_thing = other_thing

    def scored_gold_post_process_M11_DEMO(self):
        data1 = self._df

        # M11 - diabetes specific code
        if "person_id" in self._df.columns:
            data1["person_id"] = data1.index + 1
            data1.person_id = data1.person_id.astype(int)

            arr = np.where(np.isclose(data1.values, -0.044642), 0, data1.values)
            arr2 = np.where(np.isclose(arr, 0.05068), 1, arr)
            arr3 = np.where(np.isclose(arr2, -0.009147), 40, arr2)

            data1 = pd.DataFrame(arr3, index=data1.index, columns=data1.columns)
            data1.person_id = data1.person_id.astype(int)

        # M11 end//

        self._df_processed = data1
        return self._df_processed

    @property
    def data_in(self):
        return self._df
    @property
    def data_processed(self):
        return self._df_processed

    def in_to_silver_ds01_M10_M11_DEMO(self, inference_mode=True):
        #### DEMO code ### replace this with YOUR custom code (for DEMO it supports 3 models. real world - you only have 1 model to care for here) 
        
        # Drop LABEL column for DEMO purpose if INFERNCE, to simulate real inference scenario...we dont know the prediction yet.
        if(inference_mode):
            target_column_name = "Survived"
            if target_column_name in self._df.columns: # 1) M10_Titanic specific code
                #  DROP some columns
                self._df_processed = self._df
                self._df_processed = self._df_processed.drop(target_column_name, axis=1) # DEMO scenario: Simulate feature engineering...source system might not know column name for Y, and certainly not values
                #self._df.drop("Name", axis=1, inplace=True) # Drop Name since its only "noise" for ML. AutoML will remove it automatically though...
                #self._df.rename(columns={'Siblings/Spouses Aboard': 'siblings_spouces_aboard', 'Parents/Children Aboard': 'parent_or_child_aboard'}, inplace=True)
                self._df_processed.columns =  self._df_processed.columns.str.replace("[/]", "_")
                return self._df_processed
            else:
               self._df_processed = self._df

            target_column_name = "Y"
            if target_column_name in self._df.columns: # 2) M11_Diabetes specific code
                self._df_processed = self._df.drop(target_column_name, axis=1) # ,inplace=True
            else:
               self._df_processed = self._df
            target_column_name = "price"
            if target_column_name in self._df.columns: # 3)car specicif
                self._df_processed = self._df.drop(target_column_name, axis=1) # ,inplace=True
            else:
               self._df_processed = self._df
            
        return self._df_processed

    def silver_merged_processing(self, other_thing=None):
        #combined_df = combined_df.sample(frac=0.5, replace=True, random_state=1) # For DEMO purpose, just user 50% to score
        self._df_processed = self._df.dropna()
        #self._df_processed = self._df_processed.reset_index(drop=True)
        return self._df_processed

# Once and only once: Use a class (static or not) from both your notebooks to DEBUG, and from the pipeline python files

class M01In2GoldProcessor(object):
    @staticmethod
    def M01_ds01_process_in2silver(df):
        df_processed = df #df.drop(columns=['XYZ'])
        df_processed.columns = df_processed.columns.str.replace("[/]", "_")
        return df_processed

    @staticmethod
    def M01_ds02_process_in2silver(df):
        df_processed = df
        df_processed.columns = df_processed.columns.str.replace("[/]", "_")
        return df_processed

    @staticmethod
    def M01_merge_silvers(df1,df2):
        merged = df1 # #pd.merge(df1, df2, left_on='Xyz', right_on='Zxy')
        merged = merged # merged.drop(columns=['XyzKlyfs','XyzKlax'])
        merged =merged # merged[merged['label_col'].notna()] # drop na rows
        return merged

class M12_In2GoldProcessor(object):
    @staticmethod
    def ds01_process_in2silver(df):
        df_processed = df #df.drop(columns=['XYZ'])
        df_processed = df_processed[df_processed.mileage < 10000]
        return df_processed

    @staticmethod
    def ds02_process_in2silver(df):
        df_processed = df
        df_processed = df_processed[df_processed.mileage < 10000]
        return df_processed
    @staticmethod
    def ds03_process_in2silver(df):
        df_processed = df
        df_processed = df_processed[df_processed.mileage < 10000]
        return df_processed

    @staticmethod
    def merge_silvers(df1,df2,df3):
        merged = df1 # #pd.merge(df1, df2, left_on='Xyz', right_on='Zxy')
        merged = merged # merged.drop(columns=['XyzKlyfs','XyzKlax'])
        merged =merged # merged[merged['label_col'].notna()] # drop na rows
        
        merged = pd.concat([df1,df2,df3]) # VW + AUDI + BMW
        return merged

class Trainer():
    _model_name = None
    _esml_model_name = "10_titanic_model_clas"
    _esml_model_alias = "M10"
    _esml_current_env = "dev"
    _ml_type = "classification"

    _df_train = None
    _df_validate = None
    _df_test = None
    _df_other = None
    _scoring_dictionary = {}
    
    def __init__(self, aml_model_name,esml_model_name, esml_model_alias, esml_current_env, ml_type, train_df,validate_df,test_df, other_df=None):
        self._model_name = aml_model_name
        self._esml_model_name = esml_model_name
        self._esml_model_alias = esml_model_alias
        self._esml_current_env = esml_current_env
        self._ml_type = ml_type

        self._df_train=train_df
        self._df_validate = validate_df
        self._df_test = test_df
        
        self._df_other = other_df

    def train(self):
        if(self._esml_model_alias == "M10"): # For demo purposes only...you should only have one Trainer instance, per model. Not handle multiple.
            pass
        elif(self._esml_model_alias == "M11"):
            pass

    def calculate_test_set_scoring(self):
        if(self._ml_type == "regression"):
            pass
        elif(self._ml_type == "classification"):
            pass
        elif(self._ml_type == "forecasting"):
            pass
        else:
            pass

    def compare_scoring_current_vs_new_model(self, current_leader_model,current_leader_scoring, target_env="test"):
        promote = True

        if (self._model_name is not None): # not the 1st time
            if(current_leader_model is not None): # and we have a target model to compare with
                pass # if (self._scoring_dictionary > current_leader_scoring)

        return promote