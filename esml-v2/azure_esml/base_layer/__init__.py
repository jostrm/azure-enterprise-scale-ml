"""Generic Azure workspace adapters; independent of customer and domain policy."""

from .azure_ml import AzureMLCLIBackend, AzureMLSDKBackend
from .contracts import IFolderCatalog, MLBackend, WorkspaceTarget
from .folders import BlobFolderCatalog, LocalFolderCatalog

__all__ = [
    "AzureMLCLIBackend",
    "AzureMLSDKBackend",
    "BlobFolderCatalog",
    "IFolderCatalog",
    "LocalFolderCatalog",
    "MLBackend",
    "WorkspaceTarget",
]
