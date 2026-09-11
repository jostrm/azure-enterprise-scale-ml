# ML MODEL FACTORY

# How is the folder structure of these AI Factory ML templates ordered
Evertyihng are generic templates. Not hardcoded examples. You can simply change to your data, and it will work - or prefferlby use the usecase_code\40-agent-factory to build ML-models from these templates.

- SPEED: There are 3 categories of use cases: Batch, Online, Streaming
- TYPE: Under each category, such as "Batch", we haeve different use case cateogories
    - classification (tabular data)
    - regression (tabular data)
    - timeseries-forecasting (tabular data)
    - computer-vision (image data)
    - purposely not there: TEXT, VIDEO, SPEECH, since todays LLMs takes care of that.
- TECHNOLOGY (IDE): Each usecase of speed and type you can pick differnt technology of your choice
    - azure-automl: Azure Machine Learning AutoML
    - azureml-pipeline: Azure Machine Learning Pipeline
        - both via Python SDK v2, and CLI v2
    - databricks-azureml-pipeline-step: Azure Machine Learning Pipeline step for Databricks Spark notebook called in Azure ML
    - databricks-notebook: Databricks spar notebook
    - notebook: Jupyter notebook in Python

## Batch, Online or Streaming use cases
- Batch use cases, meaning ml/dl-models deployed and served on Azure Machine Learning batch pipelines, or Databricks batch processing. Using Azure datafactory to load multiple rows from storage to a pipeline that does inferehces on all rows, and saves the result back to the stoage account.The compute is not up at start, but spins up a cluster that processes the data, then goes down again.
- Online, meaning ml- or dl-models served on AKS or ContainerApps, or Azure ML Managed Online Endpoints, or Databricks equivalent that also have scale to zero cluster. Where a user or consuming applicaiton can call pass some data to a REST endpoint, and get a REST response back, in near real time. The compute is always up-and running, hot. 
- Streaming, meaning models served via Azure Databricks strucured streadming or Azure Stream analtyics, both via Azure Eventhubs. The results are near real time, and can also be save to storage. 


## You are an Enteprise Scale AI Factory Machine learning model developer

Focus on using Azure machine learning AutoML, but also Databricks examples. 

Machine learning models you should create will be scenarios (see Kaggle data) of simple examples of
- classification, such as the "Youwld you surviced Titanic or not" with titanic.parquet data
- regression, such as "risk of diabetes" or "risk of customer churn"
- forecasting, such as "sales forecasting"  of orange juice, https://github.com/Azure/azureml-examples/tree/main/sdk/python/jobs/automl-standalone-jobs/automl-forecasting-orange-juice-sales
- time-series foreacting: 
- computer vision, such as: Multi-class image classification, Multi-label image classificaiton, object detectio, instance segmentaiton (all are supported in AutoML)

Have both examples using AutoML, and without. AutoML v2, docs: https://learn.microsoft.com/en-us/azure/machine-learning/concept-automated-ml?view=azureml-api-2

Create both Jyptuer notebook examples, Azure ML pipelines with Python, and with the CLI. 
Here are some AutoML notebooks: https://github.com/Azure/azureml-examples/tree/main/sdk/python/jobs/automl-standalone-jobs

Use only Azure machine learning V2 examples. 
https://learn.microsoft.com/en-us/azure/machine-learning/?view=azureml-api-2
Create each example with Python SDK, and with CLI v2. 
Docs: https://learn.microsoft.com/en-us/azure/machine-learning/how-to-train-model?view=azureml-api-2&tabs=python

Use Responsible AI tooling, on each model scenario: https://learn.microsoft.com/en-us/azure/machine-learning/concept-responsible-ai?view=azureml-api-2
