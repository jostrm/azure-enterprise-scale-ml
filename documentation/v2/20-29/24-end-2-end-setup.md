# End-2-End setup tutorial (3 steps): AIFactory + 1 ESMLProject

> [!IMPORTANT]
> See the new bootstrap template repository - even more automated way to setup Enterprise Scale AIFactory's. (This section is still valid and good to read)
> [Enterprise Scale AIFactory - Template repo, using the AI Factory as submodule](https://github.com/jostrm/azure-enterprise-scale-ml-usage)

## Prerequisites
[Prerequisites](../10-19/12-prerequisites-setup.md)

## Config: Standalone VS Hub-connected centralized private DNS zones
### Standalone
For `Standalone mode` using the *AI Factory common resource group* for both `vNet and Private DNS zones` set the values as below: `true, subscriptionId and resourcegroupNam` where your centralized Private DNS zones resides. This is usually your Hub subscriptiom and platform-connectivity resource group.

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
For `Hub-connected mode` for Private DNS zones set the values as below: `true, subscriptionId and resourcegroupName` where your centralized Private DNS zones resides. This is usually your Hub subscription and platform-connectivity resource group.

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
For `Bring your own vNet`, e.g. NOT using the *AI Factory common resource group* for `vNet` location, set the parameters as below- 

[Docs-link: 10-esml-globals-override.json](../../../environment_setup/aifactory/parameters/10-esml-globals-override.json)  | [Local-repo-link](../../../../aifactory/parameters/10-esml-globals-override.json)

```json
        "vnetResourceGroup_param": {
            "value": "rg-where-vnet-resides"
        },
        "vnetNameFull_param": {
            "value": "vnet-name-inside-of-resourcegroup"
        },
```

## Setup options: 
- Option A) [Setup AIFactory - Infra Automation (AzureDevops+BICEP)](../10-19/13-setup-aifactory.md)
    - [Azure Devops - YAML](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/readme.md)
    - [Azure Devops - Classic](../../../environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-ado-pipelines/readme.md)
- Option B) [Setup AIFactory - Infra Automation (GithubActions+BICEP)](../10-19/13-setup-aifactory-gha.md)
    - [Github Actions](../../../environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/readme.md)
- *Option C) [Setup AIFactory - Infra Automation (GithubActions+Terraform)](../10-19/13-setup-aifactory-gha.md)
    - TODO: Joakim

<!--
2) [Provision AIFactory Common](../20-29/24-create-AIFactory-common.md)
3) ! TODO: jostrm TBA !  [WIP - Provision 1st AIFactory Project](../20-29/24-create-AIFactory-project.md)
    - ! TODO: jostrm TBA !  [WIP - Configure 1st AIFactory Project](../20-29/24-create-AIFactory-project.md)

-->
## Result: 
This is what you will get:

[AIFactory overview](../10-19/15-aifactory-overview.md)

[AIFactory architecture diagrams](../10-19/11-architecture-diagrams.md) 