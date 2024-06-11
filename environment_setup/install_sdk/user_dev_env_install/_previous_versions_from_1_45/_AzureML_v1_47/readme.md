# Conda version
- 4.14.0
# Pip version
- 22.2.2
# Python version
- 3.8.13
# Azure ML and AutoML version (2022-11-10)
- 1.47
# Tested OK or NOT - history: fresh install on DSVM, with MiniConda, started in Admin mode
- STATUS: not OK, after below fixes:
- 2022-11-10: 1st test. Error:
    - 1) `Vanilla Azure ML AutoML 1.47 install` (no ESML pip to fix datalake gen2, keyvault). Before: p.ws.update(v1_legacy_mode=True)
        - Error: `ModuleNotFoundError: No module named 'azure.keyvault'`
        - ---> 26 from azure.keyvault.secrets import SecretClient
        -  27 from azure.identity import ClientSecretCredential
        - 28 from azure.storage.filedatalake import DataLakeServiceClient
    - 2) After: `p.ws.update(v1_legacy_mode=True)`
        - Error: `ModuleNotFoundError: No module named 'azure.keyvault'`
    - 3) After: `ESML pip install fix:kv` (adding Azure keyvault dependencies, but not pip for azure-datalake)
        - Error: `ModuleNotFoundError: No module named 'azure.storage.filedatalake`
            - esml/common/`storage_factory.py`
            - 33 from baselayer_azure import AzureBase
    - 4) After: `ESML pip install fix:kv+lake` ()
        - lake: 12.6.0
        - secrets==4.3.0
        - keyvault==4.10
    - 5) SB / `pygmentize.exe` error during install:
        - Error: ERROR: Could not install packages due to an EnvironmentError: [WinError 5] Access is denied: 'C:\\Users\\esmladmin\\AppData\\Local\\Temp\\2\\pip-uninstall-iu93hpmr\\pygmentize.exe'

 
    
