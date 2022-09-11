from abc import ABCMeta, abstractmethod

class IESMLDataset:
    __metaclass__ = ABCMeta

    @classmethod
    def version(self): return "1.4"