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

    def in_to_silver_ds01_M10_M11_DEMO(self):
        #### DEMO code ### replace this with YOUR custom code (for DEMO it supports 2 models, usually only 1....) 
        target_column_name = "Survived" 
        if target_column_name in self._df.columns: # 1) M10_Titanic specific code
            #  DROP some columns
            self._df_processed = self._df.drop(target_column_name, axis=1) # DEMO scenario: Simulate feature engineering...source system might not know column name for Y, and certainly not values
            #self._df.drop("Name", axis=1, inplace=True) # Drop Name since its only "noise" for ML. AutoML will remove it automatically though...
            #self._df.rename(columns={'Siblings/Spouses Aboard': 'siblings_spouces_aboard', 'Parents/Children Aboard': 'parent_or_child_aboard'}, inplace=True)
 
        target_column_name = "Y"
        if target_column_name in self._df.columns: # 2) M11_Diabetes specific code
            self._df_processed = self._df.drop(target_column_name, axis=1) # ,inplace=True
        
        target_column_name = "price"
        if target_column_name in self._df.columns: # 2) M11_Diabetes specific code
            self._df_processed = self._df.drop(target_column_name, axis=1) # ,inplace=True

        return self._df_processed

    def silver_merged_processing(self, other_thing=None):
        #combined_df = combined_df.sample(frac=0.5, replace=True, random_state=1) # For DEMO purpose, just user 50% to score
        self._df_processed = self._df.dropna()
        #self._df_processed = self._df_processed.reset_index(drop=True)
        self._df_processed.columns =  self._df_processed.columns.str.replace("[/]", "_") # Rename columns, remove /
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