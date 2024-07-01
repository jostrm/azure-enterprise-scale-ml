
# How to add an AIFactory project - setup & use the `AIFactory seeding Keyvault`
Purpose: We want to split the responsibility of who to create articfacts in Microsoft Entra ID, versus the AIFactory pipeline in Azure Devops / GHA - who reads information about service principals and sets permissions.
- Example: An admininstrator can create 10 service principals, January 1st, that will be stored in a `seeding Keyvault`, and used whenever a project manager wants to order a new AIFactory project during the year, up to 10 projects.

## Create the keyvault and enable BICEP to use is

1) Create an Azure Keyvult, in the AIFactory DEV Azure subscription, in a resource group that ESML Core team administrators has access to.
2) Enable the Keyvault to be used by BICEP, by running below command: 
The below is needed for ADO and BICEP able to use this keyvault: 

 `az keyvault update  --name kv-esml-seeding-001 --enabled-for-template-deployment true
 `
 - Purpose: For AAD ADMIN to add 1-250 project service principles. 2022 we can reuse the SP's from the old projects 1-12.   External keyvault: `kv-esml-common-ext`

## Setup & Use the `Seeding keyvault`: Add information

### Add new AIFactory PROJECT service principal information: Steps: 1-3 (ex:005)
- 1) An ADMIN creates a new service principle in Microsoft Entra ID, and saves in EXTERNAL keyvault `'kv-esml-common-ext'` the 3 values
 	- esml-project005-sp-id
 	- esml-project005-sp-oid
 	- esml-project005-sp-secret
 
- 2) ESML ADMIN, configures the Azure Devope "esml-project" RELEASE pipeline, 4 VARIABLES need to be set. /Edit release/ Note that 2 valus is copied from external keuvaylt. Then run the RELEASE pipeline.

	`project_number_000 = 005`

	`project_service_principal_AppID` = ref001

	`project_service_principal_OID` =  ref002

	`technical_admins_ad_object_id` = ref003

	- ref001= esml-project005-sp-id
	- ref002= esml-project005-sp-id
	- ref003= AD user Object Id's for all project members, in a comma-separeted list: `asdf123,asd24,234f3`

	#### Click "deploy"...wait 30min..DONE!

- 3) AAD ADMIN or ESML ADMIN copies the SP SECRET manually from This EXTERNAL  KEYVAULT(A), to the newly created project specific KEYVAULT (B) `kv-p005-weu-dev-abcym01`

*The SP secret value is for security reason copied manually by the "admin" from External keyvault. (The BICEP can, but will not do that)


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