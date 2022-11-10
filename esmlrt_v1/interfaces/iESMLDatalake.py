from abc import ABCMeta, abstractmethod

class IESMLDatalake:
    __metaclass__ = ABCMeta

    @classmethod
    def version(self): return "1.4"

    @abstractmethod
    def split_gold_3(self,train_percentage,stratified=False): raise NotImplementedError