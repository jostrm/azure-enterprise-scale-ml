from abc import ABCMeta, abstractmethod

# Abstract base class - do not instantite this. Use the concrete class ESMLSplitter or your own class instead.
class IESMLSplitter:
    __metaclass__ = ABCMeta

    @classmethod
    def version(self): return "1.4"
    
    ###
    # returns: train = dataframe, train_percentage = 0.6, validate = dataframe, validate_percentage = 0.2, test = dataframe, test_percentage = 0.1
    ###
    @abstractmethod
    def split(self,gold_df,label,train_percentage,seed,stratified):

        train = None
        validate = None
        validate_percentage = None
        test = None
        test_percentage = None

        #### Customize Build your OWN logic here, how to split data, by creating a new class similar as esmlrt/runtime/ESMLSplitter(IESMLSplitter)
        ## ....
        #### Customize END

        #return train,train_percentage,validate,validate_percentage,test,test_percentage
        raise NotImplementedError
