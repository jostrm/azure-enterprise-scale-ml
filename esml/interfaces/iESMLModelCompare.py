from abc import ABCMeta, abstractmethod

class IESMLModelCompare:
    __metaclass__ = ABCMeta

    @classmethod
    def version(self): return "1.0"
    
    @abstractmethod
    def compare_scoring_current_vs_new_model(self, target_environment = None): raise NotImplementedError