from abc import ABCMeta, abstractmethod

class IESMLTestScoringFactory:
    __metaclass__ = ABCMeta

    @classmethod
    def version(self): return "1.0"
    
    @abstractmethod
    def get_test_scoring_7_classification(self): raise NotImplementedError
    
    @abstractmethod
    def get_test_scoring_7_regression(self): raise NotImplementedError