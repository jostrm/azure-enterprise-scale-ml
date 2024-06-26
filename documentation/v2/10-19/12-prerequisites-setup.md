# Prerequisites - Before setting up an AIFactory

## Create Azure Devops / Github projects

1) Create a Azure Devops project
2) Create 2 repositories
- ESML common
- ESML project001

## Azure subscriptions & Enterprise Scale landing zones
1) Subscriptions: 
    - Option A (Recommended to try out the AIFactory): Created at least 1 Azure subscription (Dev)
    - Option B (Recommended for productional use): For full AIFactory, create 3 Azure subscriptions (Dev, Stage, Prod)
2) Resource providers: Enable the resource providers as [specified here](./12-resourceproviders.md)
        - [Tip: You can use the Powershell script to automate this](../../../environment_setup/aifactory/bicep/esml-util/26-enable-resource-providers.ps1)

## How-to guide: Create a Azure keyvault - the so called `seeding keyvault` (IaC purpose)
- [How-to guide: Create & Use the AIFactory seeding keyvault](./12-seeding-keyvault.md)

### Service Principals & Permissions explained: 

## Service principals - purpose and permissions exaplained
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

1) Private DNS Zones
    - Option A (Recommended to try out the AIFactory):  Run the AI Factory standalone with its own Private DNS Zone. Default behaviour, no change needed
    - Option B (Recommended for productional use): Create a policy to create the private DNS zones in your HUB, and set the AIFactory config flag `centralDnsZoneByPolicyInHub` to `true`
        - The flag `centralDnsZoneByPolicyInHub` can be seen in [this AIFactory config file:e](../../../environment_setup/aifactory/parameters/10-esml-globals-4-13_21_22.json)
    



