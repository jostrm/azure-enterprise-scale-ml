# azure-enterprise-scale-ml (ESML)
Enterprise Scale ML (ESML) - AI Factory on Azure
- A solution accelerator, for `Enterprise Scale Machine Learning` & `MLOps`, based on best & proven practices for organizational scale, across projects. 
    - Best practice: `CAF/AI Factory`: https://docs.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/ai-machine-learning-mlops#mlops-at-organizational-scale-ai-factories
    - Best practice: `Modern data architecture`: https://docs.microsoft.com/en-us/azure/architecture/solution-ideas/articles/azure-databricks-modern-analytics-architecture
    - Best practice: `Datalake design`: https://docs.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-best-practices
        - `Datamesh`: https://martinfowler.com/articles/data-mesh-principles.html
- ESML has a default scaling from 1-250 ESMLprojects for its `ESML AI Factory`. 
    - That said, the scaling roof is on IP-plan, and ESML has its own IP-calculator (allocated IP-ranges for 250 is just the default)
- `Enterprise "cockpit"` over ALL your projects & models. 
    - See what `state` a project are in (Dev,Test,Prod states) with `cost dashboard` per project/environment

# THE Challenge
Innovating with AI and Machine Learning, multiple voices expressed the need to have an `Enterprise Scale AI & Machine Learning Platform` with `end-2-end` turnkey `DataOps` and `MLOps`.
Other requirements were to have an `enterprise datalake design`, able to `share refined data across the organization`, and `high security` and robustness: General available technology only, vNet support for pipelines & data with private endpoints. A secure platform, with a factory approach to build models. 

`Even if best practices exists, it can be time consuming and complex` to setup such a `AI Factory solution`, and when designing an analytical solution a private solution without public internet is often desired since working with productional data from day one is common, e.g. already in the R&D phase. Cyber security around this is important. 
-	`Challenge 1:` Marry multiple, 4, best practices
-	`Challenge 2:` Dev, Test, Prod Azure environments/Azure subscriptions
-	`Challenge 3:` Turnkey: Datalake, DataOps,  INNER & OUTER LOOP MLOps
Also, the full solution should be able to be provisioned 100% via `infrastructure-as-code`, to be recreated and scale across multiple Azure subscriptions, and `project-based` to scale up to 250 projects - all with their own set of services such as their own Azure machine learning workspace & compute clusters.

![](./esml/images/esml-s02e01-challenge.png)

# THE Strategy
To meet the requirements & challenge, multiple best practices needed to be married and implemented, such as: `CAF/WAF, MLOps, Datalake design, AI Factory, Modern Data Architecture.`
![](./esml/images/esml-s02e01-the-solution.png)
An open source initiative could help all at once, this open-source accelerator Enterprise Scale ML(ESML) -  `to get an AI Factory on Azure`
# THE Solution - TEMPLATES & Accelerator
`ESML` provides an `AI Factory` quicker (within 4-40 hours), with 1-250 ESMLProjects, an ESML Project is a set of Azure services glued together securely.
-	`Challenge 1 solved:` Marry multiple, 4, best practices
-	`Challenge 2 solved:` Dev, Test, Prod Azure environments/Azure subscriptions
-	`Challenge 3 solved:` Turnkey: Datalake, DataOps,  INNER & OUTER LOOP MLOps
`ESML marries multiple best practices` into one `solution accelerator`, with 100% infrastructure-as-code
## ESML AI Factory - 4 step process: 
![](./esml/images/esml-s02e01-4steps.png)
 # ESML AI Factory "Oneslider": Dev,Test,Prod environments - Enterprise Scale LandingZones
- Easy to provision a new ESMLProject for Dev,Test,Prod with easy cost followup, since its own PROJECT resource groups for each `Project team` in the ESML `AI Factory`:
- Horisontally 3 COMMON environment (Dev,Test, Prod) and vertically ESMLProject 1-250
  ![](./esml/images/esml-s01e01-0.png)

The Azure Devops/BICEP can optionally integrate with ITSM system as a "ticket" in ServiceNow/Remedy/JIRA Service Desk. The below info is needed for the ESML provisioning:
![](./esml/images/esml-project-ticket.png)
![](./esml/images/Bicep-1-click.png)
## ESML Architecture - "Modern data analytics platform"
Based on this reference architecture: https://docs.microsoft.com/en-us/azure/architecture/solution-ideas/articles/azure-databricks-modern-analytics-architecture

![](./esml/images/esml-arch-small.png)

# Q: Is this for you? DataOps married with MLOps? Whats the benefits of the `ESML Controlplane SDK?`
- ESML "marries" DataOps + MLOps, with `templates` for both Azure Data factory and Azure machine learning pipeline templates - `ESML autogenereated Azure ML Pipelines`
- ESML Auto-provisions the AI Factory, with 100% BICEP, where you can `1-click` a new ESMLProject in Azure Devops, serviecs glued together with `private endpoints` (network & identity)
- ESML has MLOps: both `INNER` and `OUTER LOOP` (can `talk across Dev,Test, Prod Azure ML workspaces`)
- `ESML controlplane` can compare scoring from model in `DEV workspace` with `TEST workspace`, and register the model in an external workspace (this with also network security: vNets & private endpoints, NSG's, FW)
    - See image: 
![](./esml/images/esml-s01e01-3.png)

# INTRO - Is this for you: refine data? AutoML or manual ML? R&D phase? 
**Q1:I want to use Azure AutoML, with MLOps ready to be `turned ON`** , with datalake design automatically generated for me, including `BRONZE, SILVER, GOLD` concept
- A: Yes. ESML is AutoML first, and have married this with MLOps, and an `AutoLake™` for Azure ML Studio.
- There is `22 DEMO notebooks` End-2-End MLOps, with Azure ML Pipelines, `using Azure datalake GEN 2 all the way` - from Azure datafactory, in Azure ML Pipelines/Datasets.

**Q2:I want to do ML, but <ins>only R&D phase</ins>** - I don't need MLOps or DEV,TEST, PROD environments. Can I still get benefits of ESML - get a quick DEV env & AutoLake?
- A: Yes. ESML is meant for quick R&D ( and if successful PoC -> quickly turn ON, to full enterprise scale MLOps solution
    - `Quick setup:` You can setup ESML for 1 environment only (have same subscriptionID for all 3).
        - Copy the `settings` & `notebook_demo` folder (but no need to copy MLOPS folder)
    - `R&D Mode:` Run ESML SDK with `ESMLProject.rnd=True`, and dataset-versioning will be turned off, but you still get a `AutoLake` with bronze, silver, gold concept. 

**Q3:I want to do ML, but <ins> NOT `AutoML`</ins> - just scikit learn, <ins>my own model</ins>.** Can I still leverage ESML, besides training step?
- A: Yes, you can wrap your TRAIN-step code, in an Azure ML Pipeline, as a Python step, or Databricks step, and still leverage the `AutoLake` and other `ESML accelerators`.
    - You have multiple options for your steps in this pipeline, besides automl_step, you have python_script_step, Databricks_script_step, estimator_step, synapse_spark_step, ...
    - Full list: https://docs.microsoft.com/en-us/python/api/azureml-pipeline-steps/azureml.pipeline.steps?view=azure-ml-py
- A: With that said, ESML has a *`AutoML` first* approach.
    - Using this accelerates more, and enables easier & cheaper governance (unattended retraining with auto-hyperparameter tuning)
 
**Q: How was this accelerator born, and what is it based on? It this for me?**
 - A:Working with multiple enterprise customers (aviation, manufacturing, space, energy and retail industry), we noticed common `non-industry-specific` challenges, to scale across projects, that ESML solves - an organizational scalability.
 
    * [X] ESML `extends` Azure Machine Learning via accelerators, organizational agnostic - since the `project/teams` concept in ESML.
    * [X] It extends at specific purposes: `data refinement/datalake/machine learning` to build faster. 
    * [X] Also adds `enterprise grade solution design & scalability` (dev,test, prod environments) - across subscriptions. 
    * [X] `An Enterprise Datalake, with ADLS GEN2, and logical evendriven DataMesh, with private endpoints security

Note: You can use this for any `enterprise grade` solution in need of single or multi-subscription solutions, with an `enterprise datalake` need, `DEV only` need, or `DEV->TEST->PROD` need.
- ESML was born out of these needs. Based on both Microsoft and open source `best practices` and customer `proven practices`
- Disclaimer:Although this have accelerated others, there is no guarantee it will accelerate your situtation. Read the MIT LICENCE file & Happy coding.

**Q6 ESML AI Factory: Can I just use the Azure ML SDK directly? Instead of the ESML SDK?** 
- Yes, You can bypass ESML SDK 100%  (the 5th ingredience) and only take advantage of the other ingredients (See ) the templates
# EDUCATION & Prerequisites (good to have in the `backpack`)
- Learning by doing is probably the best thing, but below some `Azure certificates` are listed good to have in the `backpack`
 - DP 100 https://docs.microsoft.com/en-us/learn/certifications/exams/dp-100
- There are also 6 ESML videos (in editing room), about ~1h each, hopefully up soon.
## ESML Accelerator benefits 
ESML has `MLOps embedded`, and adds `NEW` concepts to enrich Azure ML Studio: 
- EMSL enables `enterprise CONCEPTS` (Project/Model/Dev_Test_Prod)` - able to scale across Azure subscriptions in DEV, TEST, PROD for a model.
- ESML includes `accelerators for data refinement, with CONCEPTS`: Bronze, Silver, Gold, able to `share refined data ACROSS projects` & models
- ESML Pipeline factory `automatically` generates `Azure ML pipelines` of 7 types, with the data model `IN->Bronze->Silver-Gold` (we will refer to this as `IN_2_GOLD`)
- ESML includes *efficiency* `accelerators for ML CONCEPTS` such as `SCORE vs INFERENCE`,`ESMLPipelieFactory` (auto-creates pipeline), `Auto-Split to TRAIN,VALIDATE, TEST` (auto-register).
- ESML `marries` `MLOps` with `AutoML` - you get working MLOps template with support for Azure AutoML.
- You `don't need to remember folder paths` - since the ESML Datalake design and `automapping` of Azure ML Datasets, if you work with the `ESML SDK` (Python, Pyspark)

![](./esml/images/split_gold_and_train_automl_small.png)
 - These datasets are automapped/autogenerated by ESML at `p.split_to_gold()` 
 - Same thing at feature engineering, at `esmldataset.Bronze.Save(dataframe_state)` - the Bronze dataset will be created, and a new version (if not p.rnd=True) is created for you.

# ESMLPipelineFactory
- This scoring pipeline is automatically ESML-generated, via only `2 lines of code`!! (This is possible due to the 4 ingrediences in ESML)
- If you have your data in IN in "GOLD" state, it will work `as-is`, but probably : ) you want to add your `data wrangling` per `IN_TO_SILVER` step, in the 1-M auto-generated `ds_name_by_config.py` scripts
![](./esml/images/aml-pipeline_batch_ppt-3.png)

Azure ML is great, it improves pipeline creation with 90% fewer lines of code to [https://azure.microsoft.com/en-us/services/machine-learning/#features](https://azure.microsoft.com/en-us/services/machine-learning/#features)

I love when I get asked to push the boundries, and asks where dropping in from multiple places: 
- Q: Azure Machine learning is great, but can ESML accelerate that even more? to make it even easier, less code, to create Azure mahcine learning pipelines? 
- A: Hm, lets try. Below is the result: (0.1% of the code, of the already 90% acceleration, to get the same `batch scoring pipeline`)
    - Currently in ESML there are 7 Azure ML pipeline types, that can be generated in the same manner - with 2 lines of code, for scoring, retraining, or just refine data, etc.
    
![](./esml/images/templates-aml.png)

# WHAT is ESML Autolake™ ( Azure Datalake Storage GEN2 accelerator)
- It is based on Azure Datalake Storage GEN2, but includes a turnkey lake-design "skeleton" with concepts for ML (train, inference) and data refinement (Bronze, Silver, Gold), and enterprise scale concepts (incremental load, versioning, dev/test/prod). 
- It also has MASTER vs PROJECT concept, able to support both `DeltaLake` on Azure datalake GEN2 and `Azure ML pipelines with Azure Datalake GEN 2` Datastore.
- It is also automated for Azure ML Studio, to automatically register data as Azure ML Studio Datasets
    - Connected "per project & model". You see only your projects data.
- And it contains automated enterprise security ( uses Azure keyvault for secrets for you etc)
## `Automapping` Data to Azure ML Datasets - only possible due to the `ESML datalake`

![](./esml/images/esml-automapping.png)

## `MLOps` - Example: compare model in DEV subscription with TEST subscription

![](./esml/images/esml-mlops-2.png)

## `TEST_SET Scoring` to Azure ML Studio, as TAGS
- You can use ESML to `automatically calculate TEST-SET scoring`, 1 line of code (works for classification or regression), and this will be TAGGED on the Azure ML Dataset `GOLD_TEST` and also on the `Model`
- ![](./esml/images/esml-testset-scoring.png)
- ![](./esml/images/01_setup_model_9.png)
 
## `Scoring Drift / Concept Drift` to promote newly trained model (also as step in ESML MLOps pipeline)
- We can adjust WEIGHTS, and definition of what a BETTER model is, scoring wise.
- Example below, the newly trained model in DEV SCORED worse, than TARGET model in TEST environment, Promote=False.
- ![](./esml/images/01_setup_model_10.png)

## `Settings`
- Besides there green circles, you have a config per environment (dev,test,prod) for COMPUTE power & and HYPERPARAMETER tuning needed (e.g. in DEV you might wanna have cheaper training runs)
    - Defaults `enteprise settings` (dev,test,prod), is usually set & decided once, by an `enterprise architect`, and all `ESML Projects` inherits these, but can `override` them also, if use case needs that.
        - To override default `enteprise settings`, a projects sets the `project specific` settings.

![](./esml/images/esml-settings.png)
### Project/Model settings
![](./l/esml/images/01_setup_model_1.png)
## The BEST Model - according to YOU": Model_settings
- What: YOU define what "the best model" is. When ESML are comparing and promoting models, its based on YOUR `Model settings` with your `weights` that will decide `last registered model = best`
    - And, you can alwauys override this, to register an model of your choice manually - it'll become "the latest" and hence "the best" in the eyes of the ESML (when include in deployemnt for scoring pipleline )
- Purpose: For SCORING-DRIFT to know what metrics to use when COMPARING `compare_metrics` that YOU control, and can put `WEIGHTs` on also.
- See also the `"docs1"`, `"docs2"`,`"docs3"` text in image
- All else, you can set to 0.0 to have no `WEIGHTS` when comparing scoring for model A and B, to see if we want ot promote model A
- ![](./esml/images/01_setup_model_3.png)

## DEPLOY to AKS - realtime scoring
- You can deploy a model to AKS with 2 lines of code. All ESML projects has their own `private attached AKS cluster to Azure ML (BICEP)`
- ESML will also save the credentials & url directly `to the ESML Projects keuvault.`
- ESML environments: If you are in DEV environment, the default `enteprise settings` is a Dev_Test (1 node AKS-cluster), if TEST or PROD environment an `autoscale cluster` decided by `ESML core team`
    - Defaults `enteprise settings` settings, is usually set & decided once, by an `enterprise architect` in the ESML core team, and all `ESML Projects` inherits these, but can `override` them also, if use case needs that.
![](./esml/images/deploy-to-aks.png)