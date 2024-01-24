import numpy as np
from sklearn.model_selection import StratifiedShuffleSplit
from ..interfaces.iESMLSplitter import IESMLSplitter

class ESMLSplitter1(IESMLSplitter):
    def __init__(self):
        super().__init__()

    ###
    # Overrides abstract method: 
    # Returns: train = dataframe, train_percentage = 0.6, validate = dataframe, validate_percentage = 0.2, test = dataframe, test_percentage = 0.1
    ###
    def split(self,gold_df,label,train_percentage,seed,stratified):
        train = None
        validate = None
        validate_percentage = None
        test = None
        test_percentage = None

        #### ESML implementation. But you can create a siimilar class, inherit IESMLSplitter and override this with your OWN logic here, how to split data
        whats_left_for_both = round(1-train_percentage,1)  # 0.4 ...0.3 if 70%
        left_per_set = round((whats_left_for_both / 2),2) # 0.2  ...0.15
        validate_and_test = round((1-left_per_set),2) # 0.8 ....0.75

        if(stratified == True):
            print("Stratified split on column {} using StratifiedShuffleSplit twice, to get GOLD_TRAIN/OTHER and then 0.5 split on OTHER to get GOLD_VALIDATE & GOLD_TEST".format(label))
            train, validate, test = self.split_stratified(gold_df,whats_left_for_both,left_per_set,label)
        else:
            train, validate, test = \
                np.split(gold_df.sample(frac=1, random_state=seed), 
                        [int(train_percentage*len(gold_df)), int(validate_and_test*len(gold_df))])

            validate_percentage = left_per_set
            test_percentage = left_per_set

        return train,train_percentage,validate,validate_percentage,test,test_percentage


    ##
    # PRIVATE methods - not in IESMLSplitter interface
    ##
    # INFO:
    # validateset_and_testset_percentage_together - If train=0.8 then this is 0.2
    # left_per_set - 0.5 meaning will be 10% each if 20% validateset_and_testset_percentage_together
    # NB! In StratifiedShuffleSplit it can and will overlap as a default behaviour. (hence below impl.)
    def split_stratified(self,gold_data, validateset_and_testset_percentage_together=0.2,left_per_set=0.5, y_label=None, seed=42):

        s1 = StratifiedShuffleSplit(n_splits=1, test_size=validateset_and_testset_percentage_together, random_state=seed)

        y_labels_array = gold_data[y_label]
        for train_index, test_valid_index in s1.split(gold_data, y_labels_array): # gold_dataset_pandas, gold_dataset_pandas.status_
            train = gold_data.iloc[train_index]
            testset_and_validate_set = gold_data.iloc[test_valid_index]

        s2 = StratifiedShuffleSplit(n_splits=1, test_size=left_per_set, random_state=seed) # Split Remaining from TRAIN in 2 sets, for us to get 3 sets: TRAIN, VALIDATE, TEST

        y_labels_array = testset_and_validate_set[y_label]
        for test_index, validate_index in s2.split(testset_and_validate_set, y_labels_array):
            test_set = testset_and_validate_set.iloc[test_index]
            validate_set = testset_and_validate_set.iloc[validate_index]
            
        return train,validate_set,test_set
