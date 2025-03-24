# End-2-End setup tutorial (3 steps): AIFactory + 1 ESMLProject

> [!IMPORTANT]
> See the new bootstrap template repository - even more automated way to setup Enterprise Scale AIFactory's. (This section is still valid and good to read)
> [Enterprise Scale AIFactory - Template repo using the AI Factory as submodule](https://github.com/jostrm/azure-enterprise-scale-ml-usage)

## Prerequisites
[Prerequisites](../10-19/12-prerequisites-setup.md)

## Setup options: 
- Option A) [Setup AIFactory - Infra Automation (AzureDevops YAML + BICEP)](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md)
    - [Azure Devops - YAML](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md)
    - [Azure Devops - Classic](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/readme.md)
- Option B) [Setup AIFactory - Infra Automation (GithubActions+BICEP)](../../../environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/readme.md)
    - [Github Actions](../../../environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/readme.md)
- *Option C) [Setup AIFactory - Infra Automation (GithubActions+Terraform)](../10-19/13-setup-aifactory-gha.md)
    - TODO: Joakim

### Very detailed setup info with screenshots (Azure Devops classic)

[Setup AIFactory - Infra Automation (AzureDevops classic + BICEP)](../10-19/13-setup-aifactory.md)

## Result: 
This is what you will get:

[AIFactory overview](../10-19/15-aifactory-overview.md)

[AIFactory architecture diagrams](../10-19/11-architecture-diagrams.md) 

## Advanced Configuration: Standalone VS Hub-connected centralized private DNS zones

### When to choose What? 
Recommended approach is to combine `BYOvNet` with `Hub-Connected & Centralized private DNZ zones`. This enables all 4 access modes: `Peering, VPN, Bastion, Whitelistlisting user IP's` and separates the networking from the AI Factory common area, to your centralized Hub (Hub/Spoke).
- **Scenarios**: Production scenario.

But if you want simplicty or want to setup an AI Factory in an isolated bubble - not involving your Hub, choose `Standalone` mode. 
- Standalone mode is still secured with private networking, and you can reach the UI portals (Azure AI Foundry, Azure Machine Learning) via either: `VPN, Bastion, Whitelistlisting user IP's`
- **Scenarios**: 
    1) Testing out the AI Factory accelerator
    2) Setup an AIFactory for a temporary workshop, that needs to have high security.
    3) If it is not possible to connect it to your HUB, for various reasons.

### Standalone
For `Standalone mode` using the *AI Factory common resource group* for both `Virtual Network, Network Security Groups, Private DNS zones` set the values as below: `true, subscriptionId and resourcegroupNam` where your centralized Private DNS zones resides. This is usually your Hub subscriptiom and platform-connectivity resource group.

```json
        "centralDnsZoneByPolicyInHub": {
            "value": false
        },
        "privDnsSubscription_param": {
            "value": ""
        },
        "privDnsResourceGroup_param": {
            "value": ""
        },
```

### Hub-Connected & Centralized private DNZ zones
For `Hub-connected mode` using your own *Hub resource group* for both `Private DNS zones` 
Set values as below, e.g. where your centralized Private DNS zones resides. This is usually your Hub subscription and platform-connectivity resource group.

[Docs-link: 10-esml-globals-4-13_21_22.json](../../../environment_setup/aifactory/parameters/10-esml-globals-4-13_21_22.json)  | [Local-repo-link](../../../../aifactory/parameters/10-esml-globals-4-13_21_22.json)

```json
        "centralDnsZoneByPolicyInHub": {
            "value": true
        },
        "privDnsSubscription_param": {
            "value": "1asdfasdf-1234-134fd-123-1243123412341"
        },
        "privDnsResourceGroup_param": {
            "value": "rg-platform-connectivity"
        },

```

## Config: BYOvNet
For `Bring your own vNet`, e.g. NOT using the *AI Factory common resource group* for `Virtual Network, Network Security Groups` location, set the parameters as below. 

[Docs-link: 10-esml-globals-override.json](../../../environment_setup/aifactory/parameters/10-esml-globals-override.json)  | [Local-repo-link](../../../../aifactory/parameters/10-esml-globals-override.json)

```json
        "vnetResourceGroup_param": {
            "value": "rg-where-vnet-resides"
        },
        "vnetNameFull_param": {
            "value": "vnet-name-inside-of-resourcegroup"
        },
```

## Config: EntraID groups to Personas

How-to Create EntraID groups, Connect to Personas, Add info to seeding keyvault: 

[Ask your AI Factory core team to read this](../10-19/16-ad-groups-personas.md)

## Config: WebApp (post deplpoyment of WebApp)

### Authentication (Webapp)
- **Identity provider:** Microsoft EntraID
- **Client secret setting**:  
    - Service principal: Project specific, see project keyvault `esml-project-sp-003` 
- **Issuer URL**: https://sts.windows.net/`your_tenantId`/v2.0
    - See project keyvault for tenant id.
- **Tenant requirement**
    - Allow requestes only from the issuer tenant

### Authentication (In EntraID) - API permissions
- The service principle,Authentication page for,  `esml-project-sp-003, Needs to have API permissions, delegated, in Microsoft Graph:
    - **User.Read**
        - Sign in an read user profile
    - **offline_access**
        - Maintain data you have given it access to (such as login token, if offline)

### Authentication (In EntraID) - Redirect URL
Redirect url is on the same page, where checkbox is, and should be: 
 
https://`webapp-prj003-your-web-app-name-001`.azurewebsites.net/.auth/login/aad/callback

### Networking (WebApp)
- You can choose to run the WebApp within the subnet: `snet-esml-cmn-001-scoring` 
