# Prerequisites - Before setting up an AIFactory

## Step 1) Create Azure Devops (or Github) projects
- **Purpose:** Where the AIFactory acceleration code resides
- **Role needed:** Central IT / Azure Devops aministrator
- **Mandatory:** Yes.

- **What:** CODE repository: Create your Azure Devops project to store the AIFactory acceleration code (IaC, and templates)
- **TODO**: 
    1) Create a new Azure Devops project (or reuse an existing)
        - [How-to guide](https://learn.microsoft.com/en-us/azure/devops/organizations/projects/create-project?view=azure-devops&tabs=browser): Create Azure Devops project
    2) Create 2 GIT repositories, in your Azure Devops
        - ESML-AIFactory-Common
        - ESML-AIFactory-Project001
        - [How-to guide](https://learn.microsoft.com/en-us/azure/devops/repos/git/creatingrepo?view=azure-devops&tabs=visual-studio-2022) : Create GIT repos

## Step 2) - Create Azure subscriptions & Enterprise Scale landing zones
- **Purpose:** To have the AIFactory DEV, TEST, PROD environments
- **Role needed:** Central IT / Cloud Team
- **Mandatory:** DEV is mandatory. 1 Subscription
- A) Create Subscriptions:
    - Option A (Recommended to try out the AIFactory): Create 1 Azure subscription to act as the Dev environment. The AIFactory can simulate Test, Prod workflows (MLOps, LLMOps) with only a Dev
    - Option B (Recommended for productional use): For full AIFactory, create 3 Azure subscriptions (Dev, Stage, Prod)
    - [How-to guide](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/initial-subscriptions): Create Azure subscriptions
- B) Enable resource providers: Enable the resource providers as [specified here](./12-resourceproviders.md)
    - [Tip: You can use the Powershell script to automate this](../../../environment_setup/aifactory/bicep/esml-util/26-enable-resource-providers.ps1)

## Step 3) Create an Azure keyvault for the admin of Microsoft Entra ID: The so called `seeding keyvault` (IaC purpose), and created Service principals
- **Purpose:** For the admin (usually Central IT), who has access to Microsoft Entra ID to created service principals, to store information, to be consumed by AIFactory IaC pipeline.
- **Role needed:** Central IT / Cloud Team
- **Mandatory: Yes**
- [How-to guide: Create & Use the AIFactory seeding keyvault](./12-seeding-keyvault.md)

## Step 4) Networking: Allocate vNet ranges in your IP-plan: 3 vNets with /16 CIDR size (at least /20)
- **Purpose:** To be able to peer the AIFactory later. 
- **Role needed:** Network team within Central IT / Cloud Team
- **Mandatory:** No. We an setup an AIFactory standalone. But it cannot be peered later on. We need to use Bastion & VM to access it.
- **Mandatory with /16 size:** No. A size /20 will also work, but not recommended for productional use.
- **TODO**: Alloate at 1 or 3 vNet ranges, of size /16

## Step 5) Create 3 service principals, and store informamtion in the seeding keyvault [(see step 3)](#step-3-create-an-azure-keyvault-for-the-admin-of-microsoft-entra-id-the-so-called-seeding-keyvault-iac-purpose-and-created-service-principals)
- **Purpose:** To be used to setup the AIFactory. The information of the service principals: ObjectID, ApplicationID, Secret needs to be stored in the seeding keyvault
    - **SP1: `esml-common-bicep-sp`:** IaC purpose. This service principal will be used as a Service connection in Azure Devops. Used in a pipeline to create the AIFactory.
    - **SP2: `esml-common-sp`:**: DataOps automation purpose. This SP be delegated access by SP1 to AIFactory resources in the Common area of the AIFactory
    - **SP3: `esml-project001-sp`:** MLOps automation purpose. This SP be delegated access by SP1 to AIFactory resources to a proejct specific area of the AIFactory
        - Tip: Create 5 or 10 in one go, and store the seeding keuyvault, to have for later. 
            - Example: `esml-project001-sp,esml-project002-sp,esml-project003-sp`
- **Role needed:** Microsoft EntraID administrator: Central IT / Cloud Team
- **Mandatory:** Yes
- **TODO**: Create the 3 service principals below
### AFactory IaC Service Principal (1st)
    - Name: esml-common-bicep-sp
    - Permissons: OWNER on Subscriptions created in step 2
    - Purpose: For the ESML AIFactory CoreTeam and its data ingestion team, for DataOps pipelines unattended
### Role: CoreTeam Service Principal (2nd)
    - Name: esml-common-sp
    - Permissions: None
    - Purpose: For the ESML AIFactory CoreTeam and its data ingestion team, for DataOps pipelines unattended
### Role: ProjectTeam Service Principal (3rd)
    - Name: esml-project001-sp
    - Permissions: None
    - Purpose: For the ESML AIFactory project teams, to be able to run their MLOps and LLMOps pipelines unattended

[Read more](./12-permissions-users-ad-sps.md) here aobut the permisssions and service principals

## Step 6) Onboard a Microsoft EntraID user, with access to the Azure Devops created in step 1, and with OWNER permission on the Subscriptions created in Step 2, 
- **Purpose:** Efficiency. To be able to troubleshoot, manually login to Azure.
- **Role needed:** Microsoft EntraID administrator: Central IT / Cloud Team
- **Mandatory:** No. But at least to be OWNER on the resource Groups that ESML AIFactory has created.
- **TODO**: 
    1) Create user in Microsoft EntraID
        - [How-to guide](https://learn.microsoft.com/en-us/entra/fundamentals/how-to-create-delete-users) : Create user
    2) Delegate access to Azure Devops project, with role BASIC. (Not role: STAKEHOLDER)
        - Access to GIT in that Azure Devops project is required.
        - [How-to guide](https://learn.microsoft.com/en-us/azure/devops/organizations/security/add-users-team-project?view=azure-devops&tabs=preview-page) : Delegate user access
    3) Delegate either permission as option A or B to user. (A downside with option B is lower means to trouble shoot during the setup phase)
        - Option A) Delegate OWNER permission on the Subscriptions created in [Step 2](#step-2---created-azure-subscriptions--enterprise-scale-landing-zones)
        - Option B) Delegate OWNER permission on the Resource Groups created by the AIFactory via the service principal `esml-common-bicep-sp` [created in step 5](#step-5-create-3-service-principals-where-1-of-them-has-owner-permission-on-the-subscriptions-created-in-step-2-and-store-informamtion-in-the-seeding-keyvault-see-step-3)
            - Note: To delegate a user access to the resource groups, you need to have [SETUP the AIFactory first](./13-setup-aifactory.md)
                - Resource groups that will be created looks similar as this: `dc-heroes-esml-project001-weu-dev-001-rg`, `dc-heroes-esml-project001-weu-test-001-rg`, `dc-heroes-esml-project001-weu-prod-001-rg` 

# MORE INFO: Service principals & permissions exaplained: 

- [Read more](./12-permissions-users-ad-sps.md) here aobut the permisssions and service principals.
- [Read more](./12-seeding-keyvault.md) abou the *Seeding Keyvault* in the AIFactory


# MORE INFO: Network topology - Hub & Spoke & DNS Zones

[Read more](./14-networking-privateDNS.md) here about networking


    



