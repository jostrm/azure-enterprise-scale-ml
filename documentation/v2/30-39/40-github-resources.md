![Header](../10-19/images/header.png)

# Github Resources & Tutorials: TABULAR, TEXT, IMAGES, GenAI - Is there any Microsoft Github code examples I can try? 
Here is a collection of tutorials and Github resources for use cases you can achieve with AIFactory projects.

> [!NOTE]
>Most tutorials are Python first, with Jupyter Notebooks to create artifacts.
  
See below for more resources and notebooks

## ESML Project (Azure Machine Learning: TABULAR, TEXT, IMAGES)

> [!TIP]
>- **Q1: WHEN to use WHAT compute in Azure Machine Learning? (Compute Instance, GPU cluster, AKS Cluster, Managed online endpoints)**
>   - Coding (CI) VS Train (cluster in pipeline) VS Inference (auto-scaling managed endpoint)
>   - R&D phase VS Prodcution phase
>- **Q2: Notebook & Pipelines ? Train a model VS serve a model**
>    - Example: It may be that you need a LARGE GPU node to train or finetune a model, but when serving - the endpoint only needs and enpoint with multiple smaller nodes with auto-scaling
>- **Q3: Productionalizing: Loadbalance endpoint, Auto-scaling backend, parallel batch processing?**
>- **Q4: Productionalizing GenAI: Monitoring, Loadbalancing, API management, token rate limiting, cross-charging**
>

### Azure Machine Learning Tutorials

- [START: Github](https://github.com/Azure/azureml-examples)
- [TUTORIALS: Github](https://github.com/Azure/azureml-examples/tree/main/tutorials)

Some highlights
- [Pipeline(python) - Titanic](https://github.com/Azure/azureml-examples/blob/main/sdk/python/jobs/pipelines/1b_pipeline_with_python_function_components/pipeline_with_python_function_components.ipynb)
- [Pipeline (yaml)](https://github.com/Azure/azureml-examples/actions/workflows/sdk-jobs-pipelines-1a_pipeline_with_components_from_yaml-pipeline_with_components_from_yaml.yml)
- [Batch processing in parallel](https://github.com/Azure/azureml-examples/blob/main/sdk/python/jobs/pipelines/1g_pipeline_with_parallel_nodes/pipeline_with_parallel_nodes.ipynb)

### Responsible AI: Train model via Pipeline, and generate Responsible AI
- TABULAR:
    - [Loan: Classification](https://github.com/Azure/azureml-examples/tree/main/sdk/python/responsible-ai/tabular/responsibleaidashboard-finance-loan-classification)
    - [Housing: Classification](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/tabular/responsibleaidashboard-housing-classification-model-debugging/responsibleaidashboard-housing-classification-model-debugging.ipynb)

    - [Healthcare - Covid : Classification](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/tabular/responsibleaidashboard-healthcare-covid-classification/responsibleaidashboard-healthcare-covid-classification.ipynb)
- TEXT: 
    - [Covid 19 Emergency event - Mulitlabel Text: Classification](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/text/responsibleaidashboard-multilabel-text-classification-covid-events.ipynb)
- IMAGE: (NB! GPU's are needed for this scenario)
    - [Fridge items": Classification, Object detection ](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/vision/responsibleaidashboard-image-classification-fridge.ipynb)
    - [object-detection-MSCOCO](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/vision/responsibleaidashboard-object-detection-MSCOCO.ipynb)
    
### "Try-a-tonne / Hackathon": Responsible AI
- [Create Jobs](https://github.com/Azure/azureml-examples/actions/workflows/sdk-jobs-pipelines-1a_pipeline_with_components_from_yaml-pipeline_with_components_from_yaml.yml)


## ESGenaAI Project: RAG with Azure AI Foundry, Azure AI Search

- [Advanced - code first RAG](https://learn.microsoft.com/en-us/azure/search/tutorial-rag-build-solution)
- [API management - AI Gateway](https://learn.microsoft.com/en-us/azure/api-management/genai-gateway-capabilities)
- [API management - AI Gateway: Github](https://github.com/Azure-Samples/AI-Gateway)