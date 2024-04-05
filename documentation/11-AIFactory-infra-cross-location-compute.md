# Howto - Have an Azure ML Workspace (AML) in WestEurope, and a compute cluster in another region, UK South
https://learn.microsoft.com/en-us/azure/machine-learning/how-to-secure-training-vnet?view=azureml-api-2&preserve-view=true&tabs=cli%2Crequired#compute-cluster-in-a-different-vnetregion-from-workspace

Create a new private endpoint for your workspace in the VNet that will contain the compute cluster 

1) To add a new private endpoint using the Azure portal, select your workspace and then select Networking. Select Private endpoint connections, + Private endpoint and use the fields to create a new private endpoint.

2) When selecting the Region, select the same region as your virtual network.
3) When selecting Resource type, use Microsoft.MachineLearningServices/workspaces.
4) Set the Resource to your workspace name.
5) Set the Virtual network and Subnet to the VNet and subnet that you created for your compute clusters.
6) Finally, select Create to create the private endpoint.

Note: To add a new private endpoint using the Azure CLI, use the az network private-endpoint create. For an example of using this command, see Configure a private endpoint for Azure Machine Learning workspace.

7) Do the same for: Keyvault, Storage, ACR, 

# 1a) Create a vNet Peering, from Compute vNet to AML vNet
1) Peering Link Name source: peering-prj001-uks-vnet-to-weu-workspace-vnet

2) Out of the 4 checkboxes, check 3 of them: 
- Allow 'vnt-esmlcmn-uks-dev-001' to access 'vnt-esmlcmn-weu-dev-001'
- Allow 'vnt-esmlcmn-uks-dev-001' to receive forwarded traffic from 'vnt-esmlcmn-weu-dev-001'
- Allow gateway or route server in 'vnt-esmlcmn-uks-dev-001' to forward traffic to 'vnt-esmlcmn-weu-dev-001

3) Peering Link Name target: peering-prj001-weu-vnet-workspace-to-uks-compute-vnet
4) Out of the 4 checkboxes, check 3 of them, top 3.
5) Then allow services: Configure the following Azure resources to allow access from both VNets.
    - The default storage account for the workspace. 
    - The Azure Container registry for the workspace.
    - The Azure Key Vault for the workspace.

# 1b) Create network links in Private DNS Zones
Name: link-api-uks-vnet-to-weu-workspace-vnet
Name: link-notebooks-uks-vnet-to-weu-workspace-vnet

- privatelink.api.azureml.ms
- privatelink.notebooks.azure.net

# 1c) 
- Allow storage, ACR, Keyvailt,  access from both vNets

# 2) Alt b: Create a Private endpoints from AML workspace and the services, to the vNet with the compute
- Create a private endpoint for each resource in the VNet for the compute cluster:
- Example: 
    - Private endpoints: 
        - pend-prj001-aml-from-weu-to-vnt-uks
        - pend-prj001-storage-blob-from-weu-to-vnt-uks
        - pend-prj001-storage-file-from-weu-to-vnt-uks
        - pend-prj001-storage-table-from-weu-to-vnt-uks
        - pend-prj001-storage-queue-from-weu-to-vnt-uks
        - pend-prj001-storage-acr-from-weu-to-vnt-uks
        - pend-prj001-storage-keyvault-from-weu-to-vnt-uks

- Note: To add a new private endpoint using the Azure CLI, use the `az network private-endpoint create`

# 3) Note that the IP ranges cannot overlap, if peering 2 vNets

