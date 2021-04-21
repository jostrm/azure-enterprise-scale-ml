# azure-enterprise-scale-ml (ESML)
Enterprise Scale ML (ESML) - on Azure

*A solution accelerator, for enterprise scale Machine Learning projects*

If you are looking for *`AutoLake™ - Data Mesh/Featurestore @ Azure`* and turnkey `MLOps` with `AutoML`?
 - Yes, this is the repo and solution accelerator including this (and some more)

![](./esml/images/esml-turnkey.png)

# INTRO - Is this for you?
**Q1:I want to use Azure AutoML, with MLOps ready to be `turned ON`** , with datalake design automatically generated for me, including `BRONZE, SILVER, GOLD` concept
- A: Yes. ESML is AutoML first, and have married this with MLOps, and an `AutoLake™` for Azure ML Studio.

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
    
**Q4:Does ESML support <ins>`BIG DATA` use cases? </ins>?** - Can I still get use ESML, which is Python based, no PySpark?
- A: **First**. `What is BIG DATA?` I asked my collegeus on the Databricks team: 

    - Q: If you have data below 8-10TB, No, but this is a grey zone here. 
    - Q: If <1TB - definetely not BIG data.
    - Q: Above 10TB - Yes. Here you need a spark cluster. Azure ML CPU clusters is not a good tool here.
    - AND: Looking at my own recent experience (past 2 years) - helping customers in 13 ML projects. 

        - None of the 13 ML-projects (models) was close to being BIG DATA (e.g. well below 1TB)
        - A few was 100-500MB
        - Most was 50-100MB
        - Some was <15 MB
    - Hence, ESML has a `<1TB` first approach, you might call it: *Small->Large Data* first approach. 
        - This is per model. The `AutoLake` is `PETA byte` scalable.
- A: **Second**: `You CAN support BIG DATA in ESML`. The parts/step in the pipeline that do requires BIG DATA crunching performance, you can use an Synapse Spark step, or Azure Databricks notebook setp - Spark clusters, in the Azure ML Pipeline, in ESML.
    - Tip: If you mount the BRONZE,SILVER,GOLD folders and process data with Databricks there - the data will be automaticaly read & registered as Datasets by ESML in Azure ML Studio - ready for training.
    - With that said, ESML is Python first, and has no <ins>accelerators</ins> build on top of PySpark yet (but it would be a good feature)

**Q5:I <ins>DO NOT</ins> want to do ML** just `traditional data wrangling/analtyics` - Can I still use ESML, for just quick DEV & AutoLake for my project?
- A: Yes. ESML or Azure ML is not tied to machine learning. Its all about "crunching data with cloud compute, and saving results (into a datalake in this case)"
    - ESML puts a `project` , `enterprise`, `Autolake` concept on top of Azure ML - the excact workload/analysis can be `ML, MILP, Multivariate`, or just a `Hello world counter`.
- A: With that said. ESML has a <ins>*ML first*</ins> approach, the most <ins>accelerators</ins> are ML-specific.

**Q: How was this accelerator born, and what is it based on? It this for me?**
 - A:Working with multiple enterprise customers (aviation, manufacturing, energy and retail industry), we noticed common `non-industry-specific` challenges, to scale across projects, that ESML solves. 
 
    * [X] ESML `extends` Azure Machine Learning via accelerators, organizational agnostic. 
    * [X] It extends at specific purposes: `data refinement/datalake/machine learning` to build faster. 
    * [X] Also adds `enterprise grade solution design & scalability` (dev,test, prod) - across subscriptions. 

Note: You can use this for any `enterprise grade` solution in need of multi-subscription solutions, with an `enterprise datalake` need.
- ESML was born out of these needs. Based on both Microsoft `best practices` and customer `proven practices`
- ESML accelerates common things a ML-solution from A-Z needs, and focus on `reusage of code and refined data` across projects, at an enterprise. To be more efficient. 
Contains both "must-have" to "nice-to-have" capabilities.
- Disclaimer:Although this have accelerated others, there is no guarantee it will accelerate your situtation. Read the MIT LICENCE file & Happy coding.

# WHAT is ESML?
`ESML` is an `accelerator` , 1 part is this `ESML SDK`- accelerator code and a auto-datalake to `code ML faster`, abstract away `Azure ML Studio` (datasets/versioning/experiments) - automated creation of artifacts.  

It `glues (networking, identity,security)` Azure services together, to get a more `product feel/ SaaS feel`. Glues together multiple PaaS (data factory, Azure ML Studio, Datalake GEN 2) across `subscriptions`. 

## ESML Accelerator benefits 
ESML has `MLOps embedded`, and adds `NEW` concepts to enrich Azure ML Studio: 
- EMSL enables `enterprise CONCEPTS` (Project/Model/Dev_Test_Prod)` - able to scale across Azure subscriptions in DEV, TEST, PROD for a model.
- ESML includes `accelerators for data refinement, with CONCEPTS`: Bronze, Silver, Gold, able to `share refined data ACROSS projects` & models
- ESML includes *nice-to-have* `accelerators for ML CONCEPTS` such as `Split to TRAIN,VALIDATE, TEST` (X_test, y_test to auto-generate charting). 
    - But Not only *nice-to-have*, also *must-have* for *lineage* of an ML model.
- ESML `marries` `MLOps` with `AutoML` - you get working MLOps template with support for Azure AutoML.
- Oh..and you `don't need to care about the Datalake design` (or HOWTO work with Azure ML Studio Datasets) for versioning data & track lineage - since ESML `Autolake`

![](./esml/images/split_gold_and_train_automl_small.png)
 - These datasets are automapped/autogenerated by ESML at `p.split_to_gold()` 
 - Same thing at feature engineering, at `p.Bronze.Save(dataframe_state)` - the Bronze dataset will be created, and a new version (if not p.rnd=True) is created for you.

# WHAT is ESML Autolake™ ( Azure Datalake Storage GEN2 accelerator)
- It is based on Azure Datalake Storage GEN2, but includes a turnkey lake-design "skeleton" with concepts for ML (train, inference) and data refinement (Bronze, Silver, Gold), and enterprise scale concepts (incremental load, versioning, dev/test/prod)
- It is also automated for Azure ML Studio, to automatically register data as Azure ML Studio Datasets
    - Connected "per project & model". You see only your projects data.
- And it contains automated enterprise security ( uses Azure keyvault for secrets for you etc)
## "What you see, is what you get (Feature store & Catalog)" & `Data Mesh` embedded & Environment (DEV,TEST,PROD) aware
![](./esml/images/esml-autolake.png)

### CONCEPTUALLY
- `Data mesh support:` Not only support for monolitic centralized data ingestion pipelines/team, but `also SELF-SERVICE domain-driven/per project`
    - Each project has their own pipelines (and Azure Datafactory instance), but can get help from the centralized Data ingestion team.
        - To have ONLY a centralized team who owns and curates the data from all domains. It does not organizationally scale as we have learned.
    - Each `domain/project` is responsible for their datasets, which they onboard and `refine from BRONZE->GOLD`, with `support` of the centralized team.
- `Feature store`: ESML leverages Azure ML Datasets, adds a `extra layer`/FEATURE STORE with the Bronze,Silver, Gold concept, both for TRAIN and INFERENCE/SCORING
    - `Feature registration is automated`, when saving BRONZE, SILVER or GOLD. (No need to register version, datatypes, timestamp, etc like in other amazing feature store alternatives, than can be cloudy and a lot of work to maintain)
    - `Time travel`: "Go back in time for GOLD_TRAIN or GOLD_SCORED dataset, just use Azure ML Studio and flip the VERSION combobox, or send "version" via code
        - GOLD for training: 
            - > `gold_2 = p.get_gold_version(2)` which uses the Azure ML SDK, so you can also use that directly
                -  > ds = p.Gold.get_by_name(workspace = ws, name = p.Gold.Name, version =  "latest")
        - Get GOLD_SCORING dataset for specific schema and specific MODEL version=1 used at inference, with a date-filter
            - > `ds_list, df_all = p.get_scored(date_filter, "1")`
- `Bronze-Silver-GOLD`: Refinement process, lineage, and to talk about different `status`  of data. 
    - Project manager: How is the project going? I heard you are in data refinement mode now, how far gone?
    - Data engineer: We are in `SILVER` state now, believe we are in `GOLD` next week, ready to `TRAIN MODEL`
### Data scientists `NEVER have to create an Azure ML Dataset / register FEATURE STORE objects`
- But will implicitly take advantage of all the great features of Azure ML Datasets 'under the hood',to build its Feature store
### Data scientists `NEVER need to know the physical datalake design`
### Data scientists `ONLY` need to read/write to the `Bronze,Silver,Gold concept`
- Datasets/Feature store is automated. + `RBAC` is set to these Bronze/Silvver/Gold folders - avoids a dataswamp))
- And will implicitly work in a cost effective, performance effective .parquet format 'under the hood'

### PHYSICALLY
- 1 Azure storage account per environment (dev, test, prod)
- All varieties of formats in ”in”, but 1 common format in ”out” -> `.parquet`
- `Physical Lineage:` From `IN`-data to `GOLD`
    - IN->OUT/BRONZE, SILVER, GOLD (train, test, validate, score)
- `Self-describing` Both due to `Bronze-Silver-GOLD`, but also ”sample” in R&D mode. A meta `Data catalog` is also recommended as add-on, such as `Azure Purview`
- `1 lake-design`: Lake design do evolve. We need backward conpatibility and versioning 
    - Example: ”Upgrade my project to `lake v5` from `lake v2` (ADF is used)
- `Physical LINEAGE` from IN-data to GOLD
# `CONTEXT`: ESML is more than this SDK with mlops & autolake. Also...
## ESML is also architecture to scale across 1-1000 PROJECTS
- `Avoid Technical quota` roofs in Azure (IP ranges, compute cores).
- `Organizationally`: Cost followups per project, model governance etc
- `Share refined data, between projects` with the ESML `Auto-lake` sharing feature
- `Fill your LAKE day-by-day, CENTRALLY & as a MESH: `: Distributed responsibility between projects, but keep same `skeleton` design, same physical storage & auto-features.
    - Recommendation: 
        1) Use a centralized INGESTION team to `BOOTSTRAP` the projects with dataset-starting points. (they usually know WHERE and HOW to onboard operational data)
        2) Then the project takes over responsibility to refined data from `BRONZE 2 GOLD` and govern that process & pipelines.
        - Use the centralized team as a `help & qualtiy check point` if projects wants to share back refined data to `MASTER` data.
- `Avoid messiness`: both in the cloud, and in the datalake. Easy RBAC. 
- `Enterprise "ML cockpit"` over ALL your projects & models.
- `Project=Team` A group of people that should have same ACCESS (to specific data etc). A team that can create 1-M machine learning models. 
    - **Project example:** To create an ML model, its common to see a small TEAM of `both internal personal + external data scientists`, 3-5 people, creating 1 ML-model
    - **Common requirement:** They should `ONLY see their "USE CASE" and "DATA" in the lake`, but also `optionally` share back refined DATA, to MASTER-LAKE, where other projects can reuse - `if eligible via RBAC`
![](./esml/images/esml-oneslider.png)


### That was the CONTEXT, But, that aside (thats infra/enterprise architect people stuff)...back to focus on this ESML SDK, and its value for YOUR project and model.
### Lets assume we have 1 project that IT has setup for you. You want to use this ESML SDK for 1 model, to get it from DEV, TEST, PROD:

# Folders (source code) explained
## `esml` folder
This is the `ESML accelerator SDK`. To work with Azure machine learning `faster`, and in an enterprise scale way (across multiple workspaces), includes and abstracts an enterprise datalake design. 
`Tip:` This is now just source code. Until this is packaged and PIP distributed, you can use this as a GIT sub-module
The `Azure ESML-accelerator SDK` (esml folder) includes as example: 
- `Factories`: Easier to prep data, get compute, Train model, Deploy models
- `Datalake AutoMapping` – Automaps the datalake to Azure ML datasets. 
- `Enterprise environments & “selfawareness”` - ESML knows what config to use, and where a model is to be promoted -  from DEV, TEST, PROD that is different Azure ML workspaces/subscriptions.
- ....and more - see feature list at the bottom of this Readme.
- `Dependency:` ESML has no dependencies to ESML folder. It has dependencies to other Azure SDK's (Azure Storage, Azure ML, Azure Keyvault)


## `mlops` and `settings` folders (TEMPLATE folders inside `copy_my_subfolders_to_my_grandparent`)
- You should copy all subfolders in `copy_my_subfolders_to_my_grandparent` to your root, next to the subclass `azure-enterprise-scale-ml`
    - `Example:`: See here, for how these folders are use together with EMSL:  https://github.com/jostrm/azure-enterprise-scale-ml-usage
- `mlops`: This is a template, a working `MLOps pipeline, using the ESML SDK, that can deploy a model `across environments where DEV, TEST, PROD` can be in different workspaces/different Azure subscriptions.
- `settings`: This is a template settings folder, for `dev,test,prod`.
- Tip: You can use this MLOps `template`, as-is to copy and edit for your projects and models. (Or you can just get inspired of it, see usage of ESML)
- `Dependency:` MLOPs folder has dependencies to ESML folder. 


## `environment_setup` folder
- This is the install-script of the full CONDA environment, for  Azure ML SDK with AutoML and ESML to work.
     - A) Dev-evironment: You can install it on your local computer for debugging, se `dev_env_attended`. 
     - B) MLOps: The `unattended` Linux setup script exists for the `MLOps unattended` mode, to be able to install on a `Linux build agent in Azure Devops` (Ubunti 18.04) with Azure ML & AutoML.
        - Note: This is a `CUSTOM setup-script`, based on the official Azure ML SDK for AutoML at GITHUB v 1.26.0 (which in future is also going to support unattended MLOps for Azure Devops build agents)
        - You `DON'T need to care about this`. (But its needed for MLOps to work)

## `azure_provisioning` folder
- Azure Devops template (build and release pipelines)
    - https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/esml/azure_provisioning/azure_devops_pipelines
- Azure ARM (Azure blueprint | Bicep)
    - With a `naming convention generator`, to fit all resources needed for ESML to your enterprise naming convention.

# Getting started
### 1. See install
There is a 3 step process - goto this READMEN [./01-install_quickstart.md](./01-install_quickstart.md) 
- Tip: During install `Configure at least DEV`, of enterprise environments (DEV, TEST, PROD)
- Glance in the `SETTINGS` folder. The `green` circles is what YOU need to configure, at least. (see image, bottom at this README)
### 2. `Run Notebooks` - to get familiar with the MLops template & ESML SDK
    
# HOW TO run demo Notebooks:

- A:  Copy notebooks. From the linked `enterprise-scale-ml` folder, you can copyt the "notebook_demos" folder, to its grandparent folder, same level as auzure-enterprise-scale-ml repo.
    - Note: The won't work until you copied them, since having relative path's.
 ## `Q: How to EDIT the Notebooks, and have GIT to ignore them?`
A - You can have "DEBUG" notebooks. Just  **rename** it with suffix `_DEBUG`.ipynb - then gitignore will not hassle you about there
## Now - what NOTEBOOKS are we talking about? 
We'd recommend running `esml_howto_0_mini.ipynb` first, for a QUICK step demo. This does 3 things:
- 1) `AutoMap datalake` & init ESML project
- 2) `Train model & compare` scoring to existing active model in DEV, TEST, or PROD
- 3) `Deploy model & Test` AKS webservice

## 5 more notebooks 
- See folder `./copy_my_subfolders_to_my_grandparent/notebook_demos/` - copy them to its grandparent folder (usually the root)
    - Note: The won't work until you copied them to the correct place, since having relative path's.
- 1)Howto: [Work with ESMLDatasets - Bronze, Silver, Gold](./copy_my_subfolders_to_my_grandparent/notebook_demos/esml_howto_5_datasets.ipynb) and the `Gold_Train,Gold_Validate, Gold_Test` concept.
- 2)Howto: [Train a model](./copy_my_subfolders_to_my_grandparent/notebook_demos/esml_howto_2_train.ipynb) - accelerated with `ESML AutoMLFactory` and `ESML ComputeFactory`
- 3)Howto: [Compare scoring of a model across subscriptions (DEV to TEST) and register](./copy_my_subfolders_to_my_grandparent/notebook_demos/esml_howto_3_compare_and_register.ipynb) model to be deployed in TEST or PROD (in other subscriptions)
- 4)Howto: [Deploy and SCORE and GET Scored data via FILTERS in AutoLake](./copy_my_subfolders_to_my_grandparent/notebook_demos/esml_howto_3_deploy_score.ipynb) a model served as BATCH or ONLINE, and how the `scored data can be auto-saved` to datalake and save ONLINE caller-id.
- 5)Howto: See different AKS online webservices settings - 1 node VS `autoscaling` VS a/b testing with managed inference.

# More "Is this for me?" Q&A

**Q6: Is ESML something for me - elevator pitch?**
- A: ESML is organizationally agnostic, and supports use cases from `simple data refinement -> for Power BI` up to advanced `multi-timeseries machinea learning-forecasting`, with datadrift, interpretml with `MLOps`
- A: If you have been looking into `Datalake` & `Data mesh`, the `Autolake` includes a lake design with data mesh concepts, bootstrapped for you, also including the feature store concept.
- A: You can use Python machine learning algorithms such as (scikit learn, Keras, Pytorch, Tensorflow), or use Azure Machine learning and AutoML which includes +29 algorithms such as Prophet for forecasting.
    - **ML problems:** ESML and AutoML can be used for fast building of `regresssion`,`classification`, `forecasting` machine learning solutions. 
    - **Model serving:** ESML accelerates models to be served as: `batch scoring`,`online scoring`. 
    - **Spark clusters**:  You can also `use Azure Databricks` as a pipeline-step, e.g. to crunch big data from/to the ESML `Auto-lake` via `Bronze,Silver,Gold` concept.
        - You can ALSO work from Azure Databricks as IDE, via ESML SDK to get 100% of `AutoLake` features, or Spark directly to the `Bronze,Silver,Gold` mounted folders, only X% of `Autolake` features works.
 
**Q7: As a `Project manager ` or `Head of AI` will I like ESML?** (ESML Cockpit & Governance)
- A: Yes, since this has `policy-based` support for `allowed` compute/training cost per DEV, TEST, PROD environment. `They` can choose the defaults, on a `cost-based decicion` and get a fair but rough estimate via `ESML cost tracking`
    - ESML tracks estimated `COST ` after 1 run in DEV, TEST or PROD - what the future runs will costs for a training pipeline,  or batch/online scoring 
    - ESML has `configuration defaults`, that can be `overriden per project/model` use case.
        - Example: In DEV you might want to have cheap training, with poor scoring in "rnd-mode", but then flip to `p.rnd=False` to get great scoring.
- `Predicted cost:` For `training` or `scoring`, `AutoLake` has its `TRAIN` and `SCORING` datasets which is used for the estimation.
    - How does it work? Since the DEV has its own config, and the training data registered in Azure ML Studio as Datasets, you will see the predicted cost there (on run/pipeline), after 1st run is completed.
    -   After 1 training-run/scoring - we know how long the DEV-cluster was used, for a specific data, and a specific ML-configuration, and what the NEXT run will cost

**Q8:I need DirectQuery from Power BI, Azure datalake does not support this. I guess I need a SQL Database, datalake just is not enough?**
- A: True. BUT - since you have versioning built in (both for data and changing schema) in `AutoLake`, you may utilize this: first save the scored data/analytics to the datalake, then to database as `cache`
    - The pro's of this is that you can use the build in versioning to create your Database tables from the dataset-version: A "version-table" in your DB, and use INFERENCE version in ESML and "GOLD_SCORED" schema.

**Q: What are the limitations in ESML v0.2 ?**
- A: An accelerator has a purposed `edge` and `ease of use` - also purposely less flexible and more `standardized`.
    - All data is saves automatically as `.parquet` in the datalake (Bronz, Silver, Gold). The `IN` data folder should be either .csv or .parquet
    - Only TABULAR data is supported. No images as of now.
    - Saving / Reading data defaults to `Pandas dataframes` (as of now), and `Azure ML Dataset is always available` - use this to `convert to Spark dataframe` to run `Azure Databricks steps` etc.
    - Tips: Things ESML does not cover, you can always fall back to the Azure ML SDK & open source.
        - Use the ESML accelerator to `solve 80% of your use cases faster`. Example: The `Autolake feature` can be used for **whatever data-refinement/analytics projects**
    - Model serving: ESML right now accelerates only `batch scoring`and `online scoring`. If you have a `streaming` scenario, build as usual (EventHubs with Kafka) but you can use `ESML AutoLake`etc.
    - The DEMO examples: MLOps pipeline uses AML compute clusters and AKS clusters in v0.2. `Spark/Databricks DEMO` examples are coming in future ESML releases.
# ESML - Feature list (Currently: v 0.2)
- Curren verision is v 0.2 is - built for Azure ML SDK 1.26.0 (AutoML)
## ROADMAP (can change of course, and has no timeline)
- Please email me feature requests at: `joakim.joakim@microsoft.com`
## v 0.1

* [X] Automapping & scanning of datalake to Azure Datasets
    - DS = p.DatasetByName("ds01_diabetes")
    - DS = p.`get_gold_version(1)`
    - df = ds.`Bronze`.to_pandas_dataframe() | ds.`Silver`.to_pandas_dataframe()
* [x] Enterprise environments: DEV, TEST, PROD across Azure ML Studio workspaces/subscriptions
    - `p.dev_test_prod = "test"`
* [x] Enterprise configuration - Project `self awareness` about environment & configuration
    - `Policy based default configuration` & project-specific
* [x] Embedded `Enterprise Security` - Azure keyvault is used under `the EMSL hood` when storing secrets to create artifacts, call websercices, etc
* [x] Model comparison `across DEV, TEST, PROD subscriptions`  - promote, m1_name, r1_id, m2_name, r2_run_id = `AutoMLFactory(p).compare_scoring_current_vs_new_model(target_env)`
    - Easy `promote` newly trained model, to target env IF it scores better - if(promote): `AutoMLFactory(p).register_active_model(target_env)`
* [X] Cost savings - R&D flag support vs Operationalization - `p.rnd=True`
    - `No dataset versioning` saving storage
    - [ ] `autofilter (20%)` data from IN folder - meaning `SMALL compute` can be used, debugging/building codebase.
* [X] Write to datalake `GEN2` Datastore & Azure Datasets - including `versioning` of IN and GOLD
* [X] `Online Deploy (AKS)`, with saving to DATALAKE inference - `service,api_uri, kv_aks_api_secret` = `p.deploy_automl_model_to_aks(model,inference_config)`
    - ESML saves API_key in Azure keyvault automatically
    - ESML solves 4 common 'errors/things': `correct compute name` and `valid replicas, valid agents, valid auto scaling`
    - AutoML support: Deploy "offline" old AutoML run for DEV/TEST/PROD environment
    - Support for → DEV, TEST or PROD environment
    - [X] `AKS-dev_test 1 node` for DEV & `Autoscalning` for TEST, PROD environments.
    - [ ] A/B deployment support, but not tested.
* [x] `Online scoring (AKS)` - `df = p.call_webservice(p.ws, X_test, caller_user_id, False) # Auto-fetch key from keyvault`
    - Fetches API url and key from keyvault
    - `1 codeline` to call webservice, get a pandas dataframe back, which also stored scoring:
        - `Auto-save scoring` to datalake INFERENCE, with support for `caller-tracking`, `unique calls per day`, `model versioning`
* [X] Auto-Split, with label saved as TAG with PERCENTAGE `train_6, validate_set_2, test_set_2` = `p.split_gold_3(0.6, label)`
* [x] Auto-GOLD_Xy split for GOLD_TEST, GOLD_VALIDATE - `X_test, y_test, tags` = `p.get_gold_validate_Xy() # Version is default latest`
    - Good for validate, test purposes. Test model/AKS-webservice
* [x] AutoMLFactory: `pipeline training` (AutoMLStep)  -  `best_run, fitted_model, exp` = `AutoMLFactory(p).train_pipeline(automl_config)`
    - dev,test, or prod
* [x] AutoMLFactory: `run training`(AutoMLRun) - `best_run, fitted_model, exp` = `AutoMLFactory(p).train(ws,automl_config, experiment_name, dev_test_prod)`
    - dev,test, or prod

(AFter above - PUBLISHES to Public GIT)

* [x] `MLOps+AutoML pipeline with ESML`
* [x] `1-click Azure Devops MLOps template`(subclassing ESML)
* [x] GITHUB - publish ESML public repo
### v 0.2
* [x] `SCORING DATASET` - M03_GOLD_SCORED with meta about `model_version`, `date_folder`, `caller_id`
    - Good for debugging and R&D
* [x] `SCORING FILTER` - Get scoring from datalake - FILTER (see image), for active environment `dev,test, prod`
* [x] Update AutoML.configs with new LOG-location: "debug_log": "./common/logs/azure_automl_debug_[dev_test_prod].log"
* [x] ESML get_config()  ESML notebooks and pipeline to use this, selfaware about location to read/write [dev_test_prod]_ws_config.json
* [x] PipelineFactory: 6 step example for `MLOPS` template with 2 build and 2 release pipelines:
    * [x] Train: `AutoMLStep`(1) 
    * [x] Deploy: `Deploy_2_AKS`(1) 
    * [x] Test: `Test_AKS`(1)
* [ ] Secret feature (maybe in May)

### v 0.3
* [ ] PipelineFactory: 6 step example: 
    * [ ] Prep: `Bronze_2_Gold_pipeline(3)` 

### v 0.4
* [ ] PipelineFactory: Train: `Bronze_2_Gold_pipeline` (non AutoML) 3 step example
* [ ] PipelineFactory: Train: `Batch Scoring` example

### v 0.5
* [ ] PipelineFactory: 3 step example: 
    * [ ] Databricks: `Bronze_2_Gold_pipeline(3)` with `Databricks notebook`

### v 0.6
* [ ] Test examples for AutoMLFactory for also: classification, forecasting.
* [ ] PipelineFactory: Inference: `Bronze_2_Gold_pipeline` (non AutoML) 3 step example
* [ ] PipelineFactory: Inference: `Train_step` (non AutoML) 1 step

### v 0.7
* [ ] Azure blueprint update
* [ ] Azure blueprint + networking/PL update
* [ ] Bicep instead of Blueprint + YAML instead of Azure Devops pipeline templates.

# More IMAGES

## `Auto-lake` with Azure ML `automapping of Datasets`

![](./esml/images/esml-automapping.png)

## `MLOps` - Example: compare model in DEV subscription with TEST subscription

![](./esml/images/esml-mlops-2.png)
## `Settings`
- Besides there green circles, you have a config per environment (dev,test,prod) for COMPUTE power & and HYPERPARAMETER tuning needed (e.g. in DEV you might wanna have cheaper training runs)

![](./esml/images/esml-settings.png)

## DEPLOY to AKS - realtime & batch scoring
- You can deploy a model to AKS with 2 lines of code. 
- Then use this endpoint to inference, for a single row or batches of rows (that will be saved in the lake). See other inmages.
![](./esml/images/deploy-to-aks.png)

## Scoring - ONLINE or BATCH scoring, with same serving (AKS)
- `ONLINE/REALTIME`: Since you can deploy a model in ESML with 2 lines of code, it is easy to serve a model. Also it will use performance config for the environment you are targeting (DEV,TEST, PROD)
- `BATCH SCORING`: As an alternative of using an additional Azure ML pipeline to BATCH score, you can also use the AKS/Realtime endpoint for batch scoring
    - This, since ESML (defaults, but optionally) saves scored data to the datalake for you, as a GOLD_SCORED dataset, you can easily batch score data also
        - It saves scored data so you can retrieve it with FILTERs: `ByDate, ByCaller, By Model_version_used_that_day_for_scoring`

    - Note: Azure ML Pipelines are better for massive batchessince we can use PARALLELL RUNSTEP, to have 10 000 rows in 10 batches sored in parallell. It can also be more cost effective (since compute goes up & down to zero after scoring pipeline is done). 
        - Tip: BUT, If you want to achieve same principle of "parallell runstep" batches, you can of course as a caller just split the data into batches of 1000 rows each, and make 10 calls to the AKS online endpoint. AKS can handle parallell calls, and are great at auto-scaling. (But you need to handle the merge when getting the 10 results back)

- Here is an example how you can "BATCH SCORE", and tracking a CALLER_ID, using a specifi model_version to score with:

> ![](./esml/images/scoring-batch-or-online.png)

## `AutoLake - Inference Get scoring in Datalake`: FILTERS
- Get the data from `current environment (dev,test pr prod)`, p.dev_test_prod = "dev"

![](./esml/images/esml-get-scoring.png)

## `Datalake - Inference & lineage`: "under the hood"
- Q1:Where is the data saved automatically? 
- Q2: What do I need to fetch scored data? 
 - A: model_name + datatime_folder (and optionally a "caller_id" as filter)

![](./esml/images/scoring-lake.png)