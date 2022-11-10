# Conda version
- 4.14.0
# Pip version
- 22.2.2
# Python version
- 3.8.13
# Azure ML and AutoML version (2022-11-10)
- 1.47
# Tested OK history: fresh install on DSVM, with MiniConda, started in Admin mode
- 2022-11-10: 1st test. 
    - 1) `Vanilla Azure ML AutoML 1.47 install` (no ESML pip to fix datalake gen2, keyvault). Before: p.ws.update(v1_legacy_mode=True)
        - Error: `ModuleNotFoundError: No module named 'azure.keyvault'`
        - ---> 26 from azure.keyvault.secrets import SecretClient
        -  27 from azure.identity import ClientSecretCredential
        - 28 from azure.storage.filedatalake import DataLakeServiceClient
    - 2) After: `p.ws.update(v1_legacy_mode=True)`
        - Error: `ModuleNotFoundError: No module named 'azure.keyvault'`
    - 3) After: `ESML pip install fix:kv` (adding Azure keyvault dependencies, but not pip for azure-datalake)
        - Error: `ModuleNotFoundError: No module named 'azure.storage.filedatalake`
    - 4) After: `ESML pip install fix:kv+lake` ()
    

ModuleNotFoundError: No module named 'azure.keyvault'
- Next test: 2022-12-01: