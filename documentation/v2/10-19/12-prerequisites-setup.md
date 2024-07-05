# Prerequisites - Before setting up an AIFactory

## Step 1) Create Azure Devops (or Github) projects
- **Purpose:** Where the AIFactory acceleration code resides
- **Role needed:** Central IT / Azure Devops aministrator
- **Mandatory:** Yes.

- **What:** CODE repository: Create your Azure Devops project to store the AIFactory acceleration code (IaC, and templates)
- '**TODO**: Create 2 GIT repositories, in your Azure Devops:
    - ESML-AIFactory-Common
    - ESML-AIFactory-Project001

## Step 2) - Created Azure subscriptions & Enterprise Scale landing zones
- **Purpose:** To have the AIFactory DEV, TEST, PROD environments
- **Role needed:** Central IT / Cloud Team
- **Mandatory:** DEV is mandatory. 1 Subscription
- A) Create Subscriptions:
    - Option A (Recommended to try out the AIFactory): Create 1 Azure subscription to act as the Dev environment. The AIFactory can simulate Test, Prod workflows (MLOps, LLMOps) with only a Dev
    - Option B (Recommended for productional use): For full AIFactory, create 3 Azure subscriptions (Dev, Stage, Prod)
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

## Step 5) Onboard a Microsoft EntraID user, with access to the Azure Devops created in step 1, and with OWNER permission on the Subscriptions created in Step 2, 
- **Purpose:** Efficiency. To be able to troubleshoot, manually login to Azure.
- **Role needed:** Microsoft EntraID administrator: Central IT / Cloud Team
- **Mandatory:** No. But at least to be OWNER on the resource Groups that ESML AIFactory has created.
- **TODO**: 
    1) Create user in Microsoft EntraID
    2) Delegate access to Azure Devops project, with role BASIC. (Not role: STAKEHOLDER)
        - Access to GIT in that Azure Devops project is required.
    3) Create user in Microsoft EntraID, Delgate either permission A or B
        - A) Delegate OWNER permission on the Subscriptions created in Step 2
        - B) Delegate OWNER permission on the Resource Groups created in the Subscriptions created in Step
            - For this, you need to have SETUP the AIFactory first. 
            - Downside: Lower means to trouble shoot during the setup phase.


### INFO: Service principals - purpose and permissions exaplained: 
### SP AIFactory specific (IaC purpose): 
Used for AIFactory orchestration service principal: Create 1 service principal with OWNER permission to the subscriptions: Dev, Test, Prod.
- Purpose: For Azure Devops / Github Action to be able to provision the AIFactory, and AIFactory projects, and set permissions for users and services (RBAC, ACL, Keyvault Access Policys) to services, datalake folders, keyvaults.

### SP project specific (Permission purpose): 
One to many project specific service principals, one per AIFactory project, add add its information to the AIFactory seeding keuvalt.
Tip is to create 5 or 10 in one go, to have for later. 

- Purpose: The seeding keyvault will be read, by the AIFactory specific service principal. This will be as low permissions that MLOps, LLMOps, and end-users needs.
    - Datalake permissions: It only has access to the project specific datalake folder. 
    - Services: It only has access to the project specific services, under the projects resource groups, such as resource groups for project001 in DEV, TEST, PROD environments
    - Example: `dc-heroes-esml-project001-weu-dev-001-rg`, `dc-heroes-esml-project001-weu-test-001-rg`, `dc-heroes-esml-project001-weu-prod-001-rg` 

## Network topology - Hub & Spoke & DNS Zones

1) Private DNS Zones: Centrally in HUB or in AIFactory spoke:
    - Option A (Recommended to try out the AIFactory):  Run the AI Factory standalone with its own Private DNS Zone. Default behaviour, no change needed
    - Option B (Recommended for productional use): Create a policy to create the private DNS zones in your HUB, and set the AIFactory config flag `centralDnsZoneByPolicyInHub` to `true`
        - The flag `centralDnsZoneByPolicyInHub` can be seen in [this AIFactory config file:e](../../../environment_setup/aifactory/parameters/10-esml-globals-4-13_21_22.json)

### centralDnsZoneByPolicyInHub: Configure Azure PaaS services to use private DNS zones
[How-to: Create Azure Policy that adds private link records to centralized private DNZ zones automatically](https://www.azadvertizer.net/azpolicyinitiativesadvertizer/Deploy-Private-DNS-Zones.html)

### User access from on-premises: Custom DNS Server hosted onpremises
[How-to: Private DNZ zones to forward - for Azure Machine Learning portal & services to work](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-custom-dns?tabs=azure-cli&view=azureml-api-2#example-custom-dns-server-hosted-on-premises)


    



