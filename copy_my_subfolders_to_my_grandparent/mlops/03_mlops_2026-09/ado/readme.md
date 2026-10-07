# Azure Devops pieplines: Build, Release template for MLOps

- To retrain models, re-reploy endpoints, smoke-test, performace-testing. 
- For the models, defined here: usecase_code\50-ml-model-factory
- Set `scenario` to a file in `usecase_code\50-ml-model-factory\user-config\model\scenarios`; the root `.venv` Python path stays unchanged. See the [shared setup and ownership layout](../readme.md#model-factory-ownership-layout).
- Using the dataops pipelines, with Azure datafactory here: copy_my_subfolders_to_my_grandparent\dataops\azure-datafactory