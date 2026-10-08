# Choose an architecture

AI Factory provides two main infrastructure families. Choose the workload first,
then review the services, networking and environment you need.

![AI Factory architectures](assets/images/10-two-architectures-v2.png)

| Family | Choose it for | Typical building blocks |
| --- | --- | --- |
| **ESML** | Machine-learning training, batch scoring and online serving | Azure Machine Learning, data storage, Key Vault, monitoring and selected compute; optional Databricks, Data Factory or AKS. |
| **GenAI-1** | Foundry agents, RAG and generative applications | Foundry, storage, Key Vault, monitoring and the selected private-agent dependencies, such as Search and Cosmos DB. |

Service switches and dependencies vary by route. Do not assume every possible
GenAI project requires the same model or that all optional services are deployed.
The older Foundry Hub flags are not the recommended current Foundry path.

## Build on a shared foundation

A factory can share common network and platform services while projects have
their own resources and settings. A project can have explicit placements in Dev,
Stage and Prod; configuration does not automatically provision all three.

See [factory, scale-set and project concepts](concepts/index.md),
[environment planning](concepts/enterprise-scale.md), and the
[Parameters checklist](parameters/standard.md).

!!! important "Plan changes before applying them"
    Feature flags are inputs to reviewed deployment. They are not a guarantee
    that existing resources remain untouched, or that disabled services are
    deleted automatically.

## Connect to your enterprise environment

Existing hub/spoke, central DNS and BYO network designs require the correct
resource references, permissions, routes and private connectivity. A topology
diagram is not a substitute for checking that setup.

![Enterprise landing-zone context](assets/images/14-eslz-full-1.png)

## Continue with your workload

- [Agent and GenAIOps templates](concepts/templates/genaiops.md)
- [ML Model Factory and MLOps](concepts/templates/mlops.md)
- [DataOps and storage choices](concepts/templates/dataops.md)
- [Create or update through CLI, SDK or REST](factory-tools/19-cli-and-api-and-usage.md)

<details markdown="1">
<summary>More info</summary>

Fabric/OneLake and other existing services can be integration targets, not
automatic additions to every factory. Check the selected workload's documented
storage and authentication contract.

![ESML and Fabric integration concept](assets/images/11-services-highlevel-esml_fabric.png)

Source families are
[`esml-project`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/esml-project)
and [`esml-genai-1`](https://github.com/jostrm/azure-enterprise-scale-ml/tree/main/environment_setup/aifactory/bicep/esml-genai-1),
with shared common infrastructure. Template availability is not proof of
capacity, regional service availability or a successful deployment.

</details>
