# Documentation - Executive summary

**Governance related** - relevant for central IT, networking team (CoreTeam: 10-29)

* [End-2-End setup tutorial - AIFactory + 1 ESMLProject](#24-end-2-end-setup-tutorial-aifactory-4-8-hours) - Estimated setup time: 4-8h
* [Infra:AIFactory: Static documentation (CoreTeam)](#11-infraaifactory-static-documentation-coreteam)
* [Infra:AIFactory: Flow diagrams (CoreTeam)](#12-infraaifactory-flow-diagrams-coreteam)
* [Infra:AIFactory: Roles & Permissions for users (CoreTeam)](#13-infraaifactory-roles--permissions-for-users-coreteam)
* [Infra:AIFactory: Onboarding of CoreTeam users and ProjectMembers via Pipelines (CoreTeam)](#21-infraaifactory-onboarding-of-coreteam-users-and-projectmembers-via-pipelines-coreteam)
* [Datalake template: Setup Datalake & Onboard ProjectTeam permissions (CoreTeam)](#22-datalake-template-setup-datalake--onboard-projectteam-via-pipelines)
* [Templates: CoreTeam usage for DataOps via PIPELINE templates (CoreTeam)](#23-templates-dataops-coreteam-usage-for-dataops-via-pipeline-templates)

**Consumer related** - relevant for developers, data scientists, data engineers (ProjectTeam: 30-39)

* [End-2-End config tutorial - ESML Project, ESGenAI Project](#39-end-2-end-setup-esml-project-esgenai-project) - Estimated config time: 1-2h
* [Usage: Dashboard, Available Tools & Services, DataOps, MLOps, Access options to AIFactory (ProjectTeam)](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam)
* [How-to guide: Get access to the AIFactory:RBAC & Networking (ProjectTeam)](#31-how-to-guide-get-access-to-the-aifactoryrbac--networking-projectteam)
* [Overview: Dashboards, Services & Acceleration in AIFactory (ProjectTeam, CoreTeam)](#32-overview-dashboards-services--acceleration-in-aifactory-projectteam-coreteam)
* [Setup: Install AzureML SDK v1+v2 and ESML accelerator library](#33-setup-install-azureml-sdk-v1v2-and-esml-accelerator-library)
* [Setup: DataLake access to project folder: How-to onboard your own data](#34-setup-datalake-access-to-project-folder-how-to-onboard-your-own-data)
* [Setup: ESML SDK accelerated Notebook templates](#35-setup-esml-sdk-accelerated-notebook-templates)
* [How-to guide: DataOps](#36-how-to-guide-dataops)
* [How-to guide: MLOps](#37-how-to-guide-mlops)
* [How-to guide: LLMOps & RAG Chat Agent](#38-how-to-guide-llmops--rag-chat-agent)

# 10) AI Factory (ESML) - About the documentation
This is the main page for all documentation, with links to underlying specifics. The docs pages is sorted within a number series, by role and by component.

### Rolebased:  The docs pages is sorted within a number series conneted to role, and focus area.

*Example: Series 10-29 is targeting the AIFactory CoreTeam, e.g. governance of the AIFactory. Series 30-39 is relevant for AIFactory ProjectTeams, e.g. the consumers of the AIFactory services & accelerators.*

| Doc series | Role | Focus | Details|
|------------|-----|--------|--------|
| [10-19](#10-ai-factory-esml---about-the-documentation) | `CoreTeam`|`Governance`| Setup of AI Factory. Governance. Infrastructure, networking. Permissions |
| [20-29](#20-infraaifactory-onboarding-roles--permission-described-coreteam) | `CoreTeam` | `Usage`| User onboarding & AI Factory usage. DataOps for the CoreTeam's data ingestion team |
| [30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) | `ProjectTeam` | `Usage`| Dashboard, Available Tools & Services, DataOps, MLOps, Access options to the private AIFactory |
| [40-49](#40-faq) | `All`|`FAQ`| Various frequently asked questions. Please look here, before contacting an ESML AIFactory mentor. |

### Component based: There are 4 main components of an ESML AIFactory. 
All 4 can be used, or optionally cherry picked. The 1st component, Infra:AI Factory, is a pre-requsite. Below the 4 components are seen. 

This table will be used in the documentation to clarify WHAT a section covers, and for WHOM/Role

| Component | In section | Focus in section | Role| Doc series
|-----------|------------|----------------|-------|----|
| 1) Infra:AIFactory | Y | - | CoreTeam | [10-19](#10-ai-factory-esml---about-the-documentation) |
| 2) Datalake template | Y | - | All | [20-29](#20-infraaifactory-onboarding-roles--permission-described-coreteam),[30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) |
| 3) Templates for: DataOps, MLOps, *LLMOps | Y | - | All | [20-29](#20-infraaifactory-onboarding-roles--permission-described-coreteam),[30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) |
| 4) Accelerators: ESML SDK (Python, PySpark), RAG Chatbot, etc  | Y | - |ProjectTeam | [30-39](#30-usage-dashboard-available-tools--services-dataops-mlops-access-options-to-aifactory-projectteam) |


![](./10-19/images/10-aifactory-4-components-2024-small.png)


## 11) `Infra:AIFactory`: Static documentation (CoreTeam)
Here you will see the definition of an AIFactory via diagrams, and how to setup an AIFactory. 

- Pre-Requisites: To setup an AIFactory
    - Service Principal (IaC purpose) & Permission
    - Azure subscriptions
- High-Level Diagram
- Low-Level Diagram
    - List of services that will be provisioned using ESML/AI Factory Pipeline
    - Integration between different services
    - Network Connectivity
        - Network topology: Hub/Spoke | VirtualWan (Vwan Hub)
        - Firewall
        - User access: Direct via corp network, VPN from home, Bastion "jumphost" for admins

## 12) `Infra:AIFactory`: Flow diagrams (CoreTeam)

Flow diagram which can explains the architectural flows of the complete solution(AI Factory, MLOps Accelerator)

- AI Factory Flow Diagram: from DATA to VALUE
- MLOps Flow Diagram

## 13) `Infra:AIFactory`: Roles & Permissions for users (CoreTeam)
EntraID Service Principal (Automation & Ops purpose) & Permission:: 

The `CoreTeam` has has its own Service Principal, for unattended Automation & DataOps (source to lake) purpose. 
- Example: For elevated access to sources and datalake, compared to project teams limited access.

Each `ProjectTeam` has its own Service Principal, for unatteded Automation & DataOps (lake only) and MLOps purpose. 
- Example: For running its DataOps or MLOps pipelines unattended. Reading & Writing to their limited space in the datalake.

### CoreTeam Service Principal
    - Name: 
    - Permissons: 
### ProjectTeam Service Principal
    - Name: 
    - Permissons: 

# 20) `Infra:AIFactory`: Onboarding, Roles & Permission described (CoreTeam)

| Component | In section | Focus in section | Role in section | Index
|-----------|------------|----------------|-------|----|
| 1) Infra:AIFactory | Y | Usage & Onboard teams | CoreTeam:Infra | [21](#21-infraaifactory-onboarding-of-coreteam-users-and-projectmembers-via-pipelines-coreteam) |
| 2) Datalake template | Y | Setup | CoreTeam:Infra | [22](#22-datalake-template-setup-datalake--onboard-projectteam-via-pipelines) |
| 3) Templates for: DataOps, MLOps, *LLMOps | Y | DataOps | CoreTeam: DataIngestion | [23](#23-templates-dataops-coreteam-usage-for-dataops-via-pipeline-templates) |
| 4) Accelerators: ESML SDK (Python, PySpark), RAG Chatbot, etc  | N | - | - | - |

User onboarding, permissions and usage howto. There are 2 roles in the AIFactory, here the different permissions roles have is explained.
 - AIFactory CoreTeam: 
 - AIFactory ProjectTeam: 

## 21) `Infra:AIFactory`: Onboarding of CoreTeam users and ProjectMembers via PIPELINES (CoreTeam)
Roles and permissions. 

### Option A) GitHub Actions workflow
- Workflows: 
    - 1) BICEP+GithubActions
    - 2) Terraform+GithubActions
### Option B) Azure Devops workflow
- Workflows: 
    - 1) BICEP+GithubActions
    - 2) Terraform+GithubActions

## 22) `Datalake template`: Setup Datalake & Onboard ProjectTeam via PIPELINES
Here you can find HOWTO guides for the ESML CoreTeam, how to setup the Datalake structure, and how to provide a ProjectTeam access to their datalake projectfolder, by running a pipeline (ADO, GHA)

## 23) `Templates: DataOps`: CoreTeam usage for DataOps via PIPELINE templates
Here you can find HOWTO guides for the ESML CoreTeam,  its Dataingestion team within the CoreTeam. 

## 24) `End-2-End setup tutorial: AIFactory (4-8 hours)`
Here is an end-2-end setup turorial. 
- Estimated time is 2-4 hours, to have the full AIFactory automation configured
- AIFactory Common DEV + the 1st ESMLProject (type: ESML)

After the setup, you can simply click on a pipeline to provision 1 or 250 AIFactory project architectures, of type ESML or ESGenAI.

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

1) Talk to your AIFactory CoreTeam. Ask them to onboard you, as per section [20)](#20-users---onboarding-roles--permission-ai-factory---coreteam)

2) Depending on your AIFactory setup, you may need to take additional actions to get network access.
- A) AIFactory, isolated mode (not peered): [HOWTO - Bastion acccess TODO-LINK](../v2/30-39/31-jumphost-vm-bastion-access.md)
- B) AIFactory, peered mode, corp network: - No action needed. Line of sight exists
- C) AIFactory, peered mode, corp VPN: - No action needed. Line of sight exists

## 32) Overview: Dashboards, Services & Acceleration in AIFactory (ProjectTeam, CoreTeam)

### 32.1 Dashboards in the AI Factory

There are multiple ESML AIFactory dashboards available, that the coreteam shared to you. 

Here you can find information, and HOWTO select them, and customize them further [TODO-LINK]

### 32.2 Azure services available in the AI Factory
There are Azure services packaged both for DataOps, MLOps, and Generative AI. 

Here you can see an overview of the services - both in a list, and as architectural diagrams [TODO-LINK]

### 32.3 Supported & Accelerated use cases (AI Factory - ProjectTeam)
Here you can find information about supported use cases, and accelerated use cases.

[HOWTO - Supported use cases & Accelerated use cases](../v2/30-39/32-use_cases-where_to_start.md)

## 33) Setup: Install AzureML SDK v1+v2 and ESML accelerator library
Here you see HOWTO install AzureML SDK v1+v2 and ESML accelerator library, locally, or at an Azure Machine Learning Compute Instance.

[HOWTO - install AzureML SDK v1+v2 and ESML accelerator library](../v2/30-39/33-install-azureml-sdk-v1+v2.md)

## 34) Setup: DataLake access to project folder: How-to onboard your own data

[HOWTO - DataLake access to project folder: Onboard own data](../v2/30-39/34-datalake-access.md)

## 35) Setup: ESML SDK accelerated Notebook templates
The ESML AIFactory comes with Notebook templates, generic notebooks (not examples). See below: How to clone them, and configure them, to accelerate your projects.
It also comes with DEMO data, per project team. 

**Pre-requisite:** Get Datalake access - See section [34](#34-how-to-guide-get-access-to-datalake---project-folder-onboard-own-data)

[HOWTO - Quickstart: Copy AI Factory notebook templates](../v2/30-39/33-install-azureml-sdk-v1+v2.md)

[HOWTO - Quickstart: Configure templates, and data settings - train model with own data](../v2/30-39/35-setup-aifactory-notebook-templates-py.md)

## 36) How-to guide: DataOps
## 37) How-to guide: MLOps
## 38) How-to guide: LLMOps & RAG Chat Agent
## 39) End-2-End setup: ESML Project, ESGenAI Project

**ESML Project:** Here is an end-2-end setup tutorial, for DataOps and MLOps
- Estimated time to setup is 1-2 hours
- ESML project configured with both DataOps and MLOps - retrained on "data changed" and on "code changed"
- Retraining DEMO-model on "data changed" and on "code changed" (CI/CD trigger)
- Deployed as online endpoint, and batch endpoint

[TODO - Link]

**ESGenAI Project:** Here is an end-2-end setup tutorial, for ESML GenAI project
- Estimated time to setup is 1-2 hours
- ESGenAI project configured with "on your data" with Azure AI Search, Promptflow with multiple indexed. 
- Re-indexed on "code changed" (CI/CD trigger on promptflow) and redeployed endpoint
- Deployed as an online endpoint, with possibility to scale with multiple backends (round-robin)
- Batch Evaluation & Live Monitoring

[TODO - Link]

# 40) FAQ
- Q: How-to clone repo with submodule to local computer? the folder  `azure-enterprise-scale-ml` is empty? 
- Q: Why can't it find the path in my submodule?
- Q: DataOps: How to work with Azure DataFactory, and branching? 
- Q: MLOps: Azure Devops and GIT Branching stragey - DEV, TEST, PROD, many models branches? 

[FAQ - FAQ-01](../v2/40-49/41-FAQ-01.md)

