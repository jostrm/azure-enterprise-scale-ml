# Documentation - Full documentation

Quick Setup
1) [Prerequisites - to setup AIFactory](./10-19/12-prerequisites-setup.md) - Estimated setup time: 1-2h
2) [End-2-End SETUP tutorial - AIFactory + 1 ESMLProject](#24-end-2-end-setup-tutorial-aifactory-4-8-hours---how-to) - Estimated setup time: 4-8h

**Governance related** - relevant for central IT, networking team (CoreTeam: 10-29)

* [11) Infra:AIFactory: Static documentation (CoreTeam)](#11-infraaifactory-static-documentation-coreteam)
* [12) Infra:AIFactory: Roles & Permissions for users (CoreTeam)](#12-infraaifactory-roles--permissions-for-users-coreteam)
* [13) Infra:AIFactory: Flow diagrams (CoreTeam)](#13-infraaifactory-flow-diagrams-coreteam)
* [14) Infra:AIFactory: Networking (CoreTeam)](./10-19/14-networking-privateDNS.md)
* [15) Infra:AIFactory: Overview of services: Naming convention(CoreTeam)](./10-19/15-aifactory-overview.md)
* [21) Infra:AIFactory: How-to: Onboarding of CoreTeam users and ProjectMembers via Pipelines (CoreTeam)](#21-infraaifactory--how-to-onboarding-of-coreteam-users-and-projectmembers-via-pipelines-coreteam)
* [22) Datalake template: How-to: Setup Datalake & Onboard ProjectTeam permissions (CoreTeam)](#22-datalake-template--how-to-setup-datalake--onboard-projectteam-via-pipelines)
* [23) DataOps template: How-to: Setup DataOps via PIPELINE templates (CoreTeam)](#23-templates-dataops---how-to-setup-dataops-via-pipeline-templates)
* [24) End-2-End setup tutorial: AIFactory (4-8 hours) - How-to](#24-end-2-end-setup-tutorial-aifactory-4-8-hours---how-to)
* [25) Personas: Connecting people & agents to processes (DataOps, MLOps, GenAIOps) & tools(architectures and services)](#25-personas-connecting-people--agents-to-processes-dataops-mlops-genaiops--toolsarchitectures-and-services)
* [26) UPDATE AIFactory: Update with new features](../v2/20-29/26-update-AIFactory.md)
* [26) EXTEND AIFactory project type: With new Services, Your BICEP](../v2/20-29/27-extend-AIF-pipelines.md)


**Consumer related** - relevant for developers, data scientists, data engineers (ProjectTeam: 30-39)

* [30) Usage: Dashboard, Available Tools & Services, DataOps, MLOps, Access options to AIFactory (ProjectTeam)](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam)
* [31) How-to guide: Get access to the AIFactory:RBAC & Networking (ProjectTeam)](#31-how-to-guide-get-access-to-the-aifactoryrbac--networking-projectteam)
* [32) Overview: Dashboards, Services & Acceleration in AIFactory (ProjectTeam, CoreTeam)](#32-overview-dashboards-services--acceleration-in-aifactory-projectteam-coreteam)
* [33) Setup: Install AzureML SDK v1+v2 and ESML accelerator library](#33-setup-install-azureml-sdk-v1v2-and-esml-accelerator-library)
* [34) Setup: Datalake: How-to onboard your own data, to project folder R&D purpose](#34-setup-datalake---project-folder-how-to-onboard-your-own-data-projectteam---rd-purpose)
* [35) Setup: ESML SDK accelerated Notebook templates](#35-setup-esml-sdk-accelerated-notebook-templates)
* [36) How-to guide: DataOps](#36-how-to-guide-dataops)
* [37) How-to guide: MLOps](#37-how-to-guide-mlops)
* [38) How-to guide: LLMOps & RAG Chat Agent](#38-how-to-guide-llmops--rag-chat-agent)
* [39) End-2-End config tutorial - ESML Project, ESGenAI Project](#39-end-2-end-setup-esml-project-esgenai-project) - Estimated config time: 1-2h
* [40) Microsoft resources on Github](./30-39/40-github-resources.md)

**FAQ - Trouble shooting** - relevant for all
* [FAQ - Core team & AFactory infra](#40-faq)
* [FAQ - Data scientist & Azure ML pipelines](#40-faq)
* [FAQ - Data engineering & Azure ML pipelines](#40-faq)

# 10) AI Factory (ESML) - About the documentation
This is the main page for all documentation, with links to underlying specifics. The docs pages is sorted within a number series, by role and by component.

### Rolebased:  The docs pages is sorted within a number series conneted to role, and focus area.

*Example: Series 10-29 is targeting the AIFactory CoreTeam, e.g. governance of the AIFactory. Series 30-39 is relevant for AIFactory ProjectTeams, e.g. the consumers of the AIFactory services & accelerators.*

| Doc series | Role | Focus | Details|
|------------|-----|--------|--------|
| [10-19](#10-ai-factory-esml---about-the-documentation) | `CoreTeam`|`Governance`| Setup of AI Factory. Governance. Infrastructure, networking. Permissions |
| [20-29](#20-infraaifactory---how-to-onboarding-roles--permission-described-coreteam) | `CoreTeam` | `Usage`| User onboarding & AI Factory usage. DataOps for the CoreTeam's data ingestion team |
| [30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) | `ProjectTeam` | `Usage`| Dashboard, Available Tools & Services, DataOps, MLOps, Access options to the private AIFactory |
| [40-49](#40-faq) | `All`|`FAQ`| Various frequently asked questions. Please look here, before contacting an ESML AIFactory mentor. |

### Component based: There are 4 main components of an ESML AIFactory. 
All 4 can be used, or optionally cherry picked. The 1st component, Infra:AI Factory, is a pre-requsite. Below the 4 components are seen. 

This table will be used in the documentation to clarify WHAT a section covers, and for WHOM/Role

| Component | In section | Focus in section | Role| Doc series
|-----------|------------|----------------|-------|----|
| 1) Infra:AIFactory | Y | - | CoreTeam | [10-19](#10-ai-factory-esml---about-the-documentation) |
| 2) Datalake template | Y | - | All | [20-29](#20-infraaifactory---how-to-onboarding-roles--permission-described-coreteam),[30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) |
| 3) Templates for: DataOps, MLOps, *LLMOps | Y | - | All | [20-29](#20-infraaifactory---how-to-onboarding-roles--permission-described-coreteam),[30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) |
| 4) Accelerators: ESML SDK (Python, PySpark), RAG Chatbot, etc  | Y | - |ProjectTeam | [30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) |


![](./10-19/images/10-aifactory-4-components-2024-small.png)


## 11) `Infra:AIFactory`: Static documentation (CoreTeam)
Here you will see the definition of an AIFactory via lists and diagrams, and workflows how to add projects or members to an AIFactory.
- [High-Level Diagram - AIFactory Capabilities ](../v2/10-19/11-architecture-diagrams.md#high-level-diagrams---architecture--capabilities)
- [High-Level Diagram - ESML project: Overview services ](../v2/10-19/11-architecture-diagrams.md#ai-factory---esml-project-overview)
- [High-Level Diagram - ESGenAI project: Overview services](../v2/10-19/11-architecture-diagrams.md#ai-factory---esgenai-project-overview)
- [Mid-Level Diagram - Azure Services integration:ESML ](../v2/10-19/11-architecture-diagrams.md#high-level-diagram---services-integration-esml-project)
- [Mid-Level Diagram - Azure Services integration:ESGenAI ](../v2/10-19/11-architecture-diagrams.md#design-patterns-supported-esgenai)
- [Low-Level Diagram - Infrastructure & LLMOps ](../v2/10-19/11-architecture-diagrams.md#low-level-diagram---llmops-esgenai)
- [Low-Level Diagram - Infrastructure & MLOps ](../v2/10-19/11-architecture-diagrams.md#low-level-diagram---llmops-esgenai)
- [Networking Diagram - Hub-Spoke, ESLZ, Private DNS, FW ](../v2/10-19/14-networking-privateDNS.md)
    - Network Connectivity
        - Network topology: Hub/Spoke | VirtualWan (Vwan Hub)
        - Firewall: What ports needs to be opened? 
        - User access: Direct via corp network, VPN from home, Bastion "jumphost" for admins

[All Diagrams: Architecture & Services - High-Level & Low Level Diagrams](../v2/10-19/11-architecture-diagrams.md)

## 12) `Infra:AIFactory`: Roles & Permissions for users (CoreTeam)
Detailed information about Roles and permission, such as Microsoft Entra ID

Service Principals (Automation & Ops purpose) & Permissions for Users, AD groups. 

[Permissions & Roles: Coreteam VS Project team](./10-19/12-permissions-users-ad-sps.md)

## 13) `Infra:AIFactory`: Flow diagrams (CoreTeam)

Flow diagram which can explains the workflows, how to utilize the complete solution(AI Factory, MLOps Accelerator) in different scenarios. 

- [Flow Diagram - Add AIFactory project, Add users](./10-19/13-flow-diagram-1.md)
- [Flow Diagram - DataOps Configuration](./10-19/13-flow-diagram-dataops.md)

## 14) `Infra:AIFactory`: Networking: Private DNS zones, Hub/Spoke etc (CoreTeam)

[HOWTO - Networking: Hybrid access, Private DNS Zones, etc](./10-19/14-networking-privateDNS.md)

# 20) `Infra:AIFactory` - How-to: Onboarding, Roles & Permission described (CoreTeam)

| Component | In section | Focus in section | Role in section | Index
|-----------|------------|----------------|-------|----|
| 1) Infra:AIFactory | Y | Usage & Onboard teams | CoreTeam:Infra | [21](#21-infraaifactory--how-to-onboarding-of-coreteam-users-and-projectmembers-via-pipelines-coreteam) |
| 2) Datalake template | Y | Setup | CoreTeam:Infra | [22](#22-datalake-template--how-to-setup-datalake--onboard-projectteam-via-pipelines) |
| 3) Templates for: DataOps, MLOps, *LLMOps | Y | DataOps | CoreTeam: DataIngestion | [23](#23-templates-dataops---how-to-setup-dataops-via-pipeline-templates) |
| 4) Accelerators: ESML SDK (Python, PySpark), RAG Chatbot, etc  | N | - | - | - |

User onboarding, permissions and usage howto. There are 2 roles in the AIFactory, here the different permissions roles have is explained.
 - AIFactory CoreTeam: 
 - AIFactory ProjectTeam: 

## 21) `Infra:AIFactory`- How-to: Onboarding of CoreTeam users and ProjectMembers via PIPELINES (CoreTeam)
See Roles and permissions. 
See [Flow Diagram - Add AIFactory project, Add users](./10-19/13-flow-diagram-1.md)

### Option A) GitHub Actions workflow
- Workflows: 
    - 1) [BICEP+GithubActions](./10-19/13-flow-diagram-1.md)
    - 2) Terraform+GithubActions
### Option B) Azure Devops workflow
- Workflows: 
    - 1) [BICEP+AzureDevops](./10-19/13-flow-diagram-1.md)
    - 2) Terraform+AzureDevops

## 22) `Datalake template`- How-to: Setup Datalake & Onboard ProjectTeam via PIPELINES
Here you can find HOWTO guides for the ESML CoreTeam, how to setup the Datalake structure, and how to provide a ProjectTeam access to their datalake projectfolder, by running a pipeline (ADO, GHA)


- [What Permissions: This is the datalake access users will get](./10-19/12-permissions-users-ad-sps.md)
- [How-to: Add users to AIFactory project, gets them correct Datalake folder access automatically ](./10-19/13-flow-diagram-1.md)

## 23) `Templates: DataOps` - How-to: Setup DataOps via PIPELINE templates
Here you can find HOWTO guides for the ESML CoreTeam,  its Dataingestion team within the CoreTeam. 

## 24) `End-2-End setup tutorial: AIFactory (4-8 hours) - How-to`

[Prerequisites - to setup AIFactory](./10-19/12-prerequisites-setup.md)

Here is an [End-2-End setup tutorial](./20-29/24-end-2-end-setup.md), with an estimated ~4-8 hour setup time.
- Estimated setup time is 3-7 hours, to have the full AIFactory automation configured, and create "AIFactory Common DEV" + the 1st AIFactory project created (type:ESML)
- Estimated setup time 1 hour: Configure AIFactory Common DEV + the 1st ESMLProject (type: ESML)

After the setup, you can simply click on a pipeline to provision 1 or 250 AIFactory project architectures, of type ESML or ESGenAI.

## 25) `Personas`: Connecting people & agents to processes (DataOps, MLOps, GenAIOps) & tools(architectures and services)

Personas is a tool the AIFactory uses to map *tools, processes and people*, to scale AI **organizationally** as well.  
Personas is used to: 

1) **Find resource gaps, define responsibility, or find redesign needs:** If you do not have people in your organization that fit a persona description needed to support a process step, you either need to redesign the architecture, change the process, or onboard new people with that persona. Personas is a good tool to define scope of **responsibility**
2) **Education:** Mapping personas to specific **Azure services** in the architecture provides the benefits of offering **educational** sessions and online courses to upskill within.
3) **Security & Access:** Personas mapped to **processes, architectures and services** can be used to define which services they need access to in a process.
4) **Project planning & Interactions** Personas mapped to each other can be used see which personas that primarily interacts with each other, to be used to setup sync meetings and project planning.

[Go here for PERSONAS docs, persona cards, personas tables ](./20-29/25-personas.md)


# 30) Usage: Dashboard, Available Tools & Services, DataOps, MLOps, Access options to AIFactory (ProjectTeam)
Here you can find HOWTO guides for a ESML ProjectTeam, including its DataOps, MLOps, supported use cases, accelerated use cases.
Also how to get access to the private AIFactory. 

| Component | In section | Focus in section | Role in section | Index
|-----------|------------|----------------|-------|----|
| 1) Infra:AIFactory | Y | Usage & Get Access, Dashboards, Services | ProjectTeam | [31](#31-how-to-guide-get-access-to-the-aifactoryrbac--networking-projectteam),[32](#32-overview-dashboards-services--acceleration-in-aifactory-projectteam-coreteam) |
| 2) Datalake template | Y | Usage & Get Access | ProjectTeam | [34](#34-setup-datalake-access-to-project-folder-how-to-onboard-your-own-data) |
| 3) Templates for: **DataOps, MLOps**, *LLMOps | Y | DataOps | ProjectTeam | 36,37 |
| 4) Accelerators: ESML SDK (Python, PySpark), RAG Chatbot, etc  | Y | Setup SDK & Templates | ProjectTeam | [33](#33-setup-install-azureml-sdk-v1v2-and-esml-accelerator-library),[35](#35-setup-esml-sdk-accelerated-notebook-templates) |


## 31) How-to guide: Get access to the AIFactory:RBAC & Networking (ProjectTeam)

1) Talk to your AIFactory CoreTeam. Ask them to onboard you, as per section [20)](#20-infraaifactory---how-to-onboarding-roles--permission-described-coreteam)

2) Depending on your AIFactory setup, you may need to take additional actions to get network access.
- A) AIFactory, isolated mode (not peered): [HOWTO - Bastion acccess](../v2/30-39/31-jumphost-vm-bastion-access.md)
- B) AIFactory, peered mode, corp network: - No action needed. Line of sight exists already.
    - Pre-req:[Docs - Setup secure Azure machine learning on Azure](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-create-secure-workspace-vnet?view=azureml-api-1)
    - Pre-req:[Docs - Well Architected Framework on Azure](https://learn.microsoft.com/en-us/azure/well-architected/)
    - Pre-req:[Docs - Well Architected Framework on Azure](https://learn.microsoft.com/en-us/azure/well-architected/)
- C) AIFactory, peered mode, corp VPN: - No action needed. Line of sight exists already
    - Pre-req: Same as B)

## 32) Overview: Dashboards, Services & Acceleration in AIFactory (ProjectTeam, CoreTeam)

### 32.1 Dashboards in the AI Factory

There are multiple ESML AIFactory dashboards available, that the coreteam shared to you. 

[How-to guide: IMPORT AIFacotory dashboards or select them, clone them, to customize them further](../v2/30-39/32-dashboards.md)

### 32.2 Azure services available in the AI Factory
There are Azure services packaged both for DataOps, MLOps, and Generative AI. 

[SERVICES LIST: Overview of the services, as a list, with naming convetions](./10-19/15-aifactory-overview.md)

[SERVICES ARCHITECTIRE - architectural diagrams](./10-19/11-architecture-diagrams.md)


### 32.3 Supported & Accelerated use cases (AI Factory - ProjectTeam)
Here you can find information about supported use cases, and accelerated use cases.

[HOWTO - Supported use cases & Accelerated use cases](../v2/30-39/32-use_cases-where_to_start.md)

## 33) Setup: Install AzureML SDK v1+v2 and ESML accelerator library
Here you see HOWTO install AzureML SDK v1+v2 and ESML accelerator library, locally, or at an Azure Machine Learning Compute Instance.

[HOWTO - install AzureML SDK v1+v2 and ESML accelerator library](../v2/30-39/33-install-azureml-sdk-v1+v2.md)

## 34) Setup: Datalake - Project folder: How-to onboard your own data (ProjectTeam - R&D purpose)

1) Prerequisite: Datalake access [HOW-TO: Setup Datalake & Onboard ProjectTeam permissions (CoreTeam)](#22-datalake-template--how-to-setup-datalake--onboard-projectteam-via-pipelines)
2) [HOWTO - Quickstart: Onboard own data, to the datalake](../v2/30-39/34-datalake-onboard-data.md)

## 35) Setup: ESML SDK accelerated Notebook templates
The ESML AIFactory comes with Notebook templates, generic notebooks (not examples). See below: How to clone them, and configure them, to accelerate your projects.
It also comes with DEMO data, per project team. 

**Pre-requisite:** Get Datalake access - See section [34](#34-how-to-guide-get-access-to-datalake---project-folder-onboard-own-data)

[HOWTO - Quickstart: Copy AI Factory notebook templates](../v2/30-39/33-install-azureml-sdk-v1+v2.md)

[HOWTO - Quickstart: Configure templates, and data settings - train model with own data](../v2/30-39/35-setup-aifactory-notebook-templates-py.md)

## 36) How-to guide: DataOps

[HOWTO - Quickstart: DataOps with Azure Datafactory ESML templates](../v2/30-39/36-dataops.md)

## 37) How-to guide: MLOps

1) [START HERE - WHAT is accelerated & WHAT is vanilla Azure ML, Azure Databricks? ](../v2/30-39/32-use_cases-where_to_start.md)

2) [HOWTO - Quickstart: Accelerate MLOps - with ESML boost on Azure Machine Learning and Databricks](../v2/30-39/37-datascientist-ml-acceleration.md)

3) [HOWTO - Quickstart: MLOps with Azure Machine Learning and Databricks](../v2/30-39/37-mlops.md)

## 38) How-to guide: LLMOps & RAG Chat Agent

[ !WIP! - HOWTO - Quickstart: LLMOps & RAG Chat Agent](../v2/30-39/37-mlops.md)
## 39) End-2-End setup: ESML Project, ESGenAI Project

**ESML Project:** Here is an end-2-end setup tutorial, for DataOps and MLOps
- Estimated time to setup is 1-2 hours
- ESML project configured with both DataOps and MLOps - retrained on "data changed" and on "code changed"
- Retraining DEMO-model on "data changed" and on "code changed" (CI/CD trigger)
- Deployed as online endpoint, and batch endpoint
- [!WIP! - Quickstart: MLOps with Azure Machine Learning and Databricks](../v2/30-39/39-end-2-end-esml-projects.md)


**ESGenAI Project:** Here is an end-2-end setup tutorial, for ESML GenAI project
- Estimated time to setup is 1-2 hours
- ESGenAI project configured with "on your data" with Azure AI Search, Promptflow with multiple indexed. 
- Re-indexed on "code changed" (CI/CD trigger on promptflow) and redeployed endpoint
- Deployed as an online endpoint, with possibility to scale with multiple backends (round-robin)
- Batch Evaluation & Live Monitoring
- [!WIP! HOWTO - Quickstart: MLOps with Azure Machine Learning and Databricks](../v2/30-39/39-end-2-end-esml-projects.md)

[TODO - Link]

# 40) FAQ
Here you can browse some Q's, and jump into relevant section. We tried to group the FAQ's into different roles & services

## 41) FAQ - Core team & AFactory infra

Example quetions: 
- Q: How-to clone repo with submodule to local computer? the folder  `azure-enterprise-scale-ml` is empty? 
- Q: Why can't it find the path in my submodule?
- Q: DataOps: How to work with Azure DataFactory, and branching? 
- Q: MLOps: Azure Devops and GIT Branching stragey - DEV, TEST, PROD, many models branches? 

[FAQ - FAQ-1](../v2/40-49/41-FAQ-01.md)

## 42) FAQ - Data scientist & Azure ML pipelines

Example quetions: 
- Q: How-to clone repo with submodule to local computer? the folder  `azure-enterprise-scale-ml` is empty? 
- Q: Why can't it find the path in my submodule?
- Q: DataOps: How to work with Azure DataFactory, and branching? 
- Q: MLOps: Azure Devops and GIT Branching stragey - DEV, TEST, PROD, many models branches? 

[FAQ - FAQ-1](../v2/40-49/41-FAQ-01.md)

## 43) FAQ - Data engineering & Azure ML pipelines

Example questions: 
- Q: Why does Azure Datafactory not trigger DataMesh copy to MASTER from PROJECt, when project pipeline is finished?  
- Q: How to setup eventdriven 

[FAQ - FAQ-43](../v2/40-49/41-FAQ-01.md)

## 44) RESOURCES: TABULAR, TEXT, IMAGES, GenAI - Is there any Microsoft Github code examples I can try? 

### ESML Project (Azure Machine Learning: TABULAR, TEXT, IMAGES)

#### Tutorials

- [Tutorials: Github](https://github.com/Azure/azureml-examples/tree/main/tutorials)
- [Create Jobs/Pipelines](https://github.com/Azure/azureml-examples/actions/workflows/sdk-jobs-pipelines-1a_pipeline_with_components_from_yaml-pipeline_with_components_from_yaml.yml)

#### Responsible AI: Train model via Pipeline, and generate Responsible AI
- TABULAR:
    - [Loan: Classification](https://github.com/Azure/azureml-examples/tree/main/sdk/python/responsible-ai/tabular/responsibleaidashboard-finance-loan-classification)
    - [Housing: Classification](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/tabular/responsibleaidashboard-housing-classification-model-debugging/responsibleaidashboard-housing-classification-model-debugging.ipynb)

    - [Healthcare - Covid : Classification](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/tabular/responsibleaidashboard-healthcare-covid-classification/responsibleaidashboard-healthcare-covid-classification.ipynb)
- TEXT: 
    - [Covid 19 Emergency event - Mulitlabel Text: Classification](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/text/responsibleaidashboard-multilabel-text-classification-covid-events.ipynb)
- IMAGE: (NB! GPU's are needed for this scenario)
    - [Fridge items": Classification, Object detection ](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/vision/responsibleaidashboard-image-classification-fridge.ipynb)
    - [object-detection-MSCOCO](https://github.com/Azure/azureml-examples/blob/main/sdk/python/responsible-ai/vision/responsibleaidashboard-object-detection-MSCOCO.ipynb)
    
#### "Try-a-tonne / Hackathon": Responsible AI
- [Create Jobs](https://github.com/Azure/azureml-examples/actions/workflows/sdk-jobs-pipelines-1a_pipeline_with_components_from_yaml-pipeline_with_components_from_yaml.yml)


### ESGenaAI Project: RAG with Azure AI Foundry, Azure AI Search

- [Advanced - code first RAG](https://learn.microsoft.com/en-us/azure/search/tutorial-rag-build-solution)    