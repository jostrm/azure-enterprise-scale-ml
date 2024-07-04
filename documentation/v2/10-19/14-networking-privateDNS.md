## Network topology - Hub & Spoke & DNS Zones

You can choose to have Private DNS Zones Centrally in HUB (recommended) or in the AIFactory spoke, in its common resource group (default):
    - Option A (Recommended to try out the AIFactory):  Run the AI Factory standalone with its own Private DNS Zone. Default behaviour, no change needed
    - Option B (Recommended for productional use): Create a policy to create the private DNS zones in your HUB, and set the AIFactory config flag `centralDnsZoneByPolicyInHub` to `true`
        - The flag `centralDnsZoneByPolicyInHub` can be seen in [this AIFactory config file:e](../../../environment_setup/aifactory/parameters/10-esml-globals-4-13_21_22.json)

## How-to: Understand how the secure Azure Machine Learning workspaces is setup in the AIFactory automation

In the ESML AIFactory the Azure Machine Learning workspaces are setup accoring to the SDK v1 specification. Since this is the highest security setup (no ARM used. No public IP)

[Read more here - how to secure Azure Machine Learning (SDK v1)](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-create-secure-workspace-vnet?view=azureml-api-1)

It is also possible to use SDK v2 - this since the SDK v2 networking is more forgiging, uses ARM and allows more public communication. 

[Read more here - how to secure Azure Machine Learning (SDK v2)](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-create-secure-workspace-vnet?view=azureml-api-2)

## How-to: Configure Azure PaaS services to use private DNS zones (centralDnsZoneByPolicyInHub:true)

Now when we know [that the ESML AIFactory are using secure Azure Machine Learning workspaces, with private link, and private DNS zones](#how-to-understand-how-the-secure-azure-machine-learning-workspaces-is-setup-in-the-aifactory-automation). 

And when you have tested that it works to access and use everything via Bastion and the VM - jumping into the secure AIFactory, you may want to access the AIFactory and Azure machine learning workspaces and AI Studio, without having to login on a VM via Bastion?

To do that, we need to peer the AIFactory spoke vNet to your HUB. And the private endpoints needs to create A-records in the HUB's private DNS zones (or create confitional forwarding manually)
- E.g. we want to avoid having the private DNS zones locally, which will work, but is not optimal, since manual work is needed, whenever an AIFactory projecte is created. 
- E.g. It is not recommended for productional and scalability reasons to use local Private DNS zones.

The [solution](#solution---private-dns-zones-custom-dns--azure-policy) is seen below: 

### Challenge more info - Private DNS zones: Avoid manual work?
If you do not have central Privat DNS Zones, the DNS forwarding will not work until you also add conditional forwarding manually. 
- You will have to then create ~40 conditional forwarding, for all your onpremises DNS server, to have it working
- The records needs to exists also in the HUB's private DNS zone and Custom DNS server - a manual task for each AIFactory project that is created.           
- If the storage account with private endpoint, and users are using both public or private access, it will not work, since users are not in DNS zone.

### SOLUTION - Private DNS zones: Custom DNS + Azure Policy
If user are on-premises and tries to connect to a public Azure Machine Learning workspace or storage account, the on-premies DNS will ping the Custom DNS server that will call Azure to provide DNS, that in turn will know the public IP. This will work, if the below actions are taken. 

- Action 1: The custom DNS Server, needs to be in the central HUB
- Action 2: A Policy can be assigned on MGMT group (or subscription) that for every type or private DNS zones (for PaaS) will create records, in the DNS Zone.				
    - [How-to: Create Azure Policy that adds private link records to centralized private DNZ zones automatically](https://www.azadvertizer.net/azpolicyinitiativesadvertizer/Deploy-Private-DNS-Zones.html)
- Action 3: Create a central private endpoint for all, somewhere.This, since our Azure portals (such as Azure ML portal) are global, we need a private endpoint to that portalt. 
    - If you have traditional Hub/Spoke topology, create it in the Hub. 				
    - If you have WWAN - you have a central vNet to the WWAN-hub, where Pivate DNS resolvers and DNS forward can live (for 1 or many if multi region) in WWAN hub.
    - [How-to: Private DNZ zones to forward - for Azure Machine Learning portal to work](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-custom-dns?tabs=azure-cli&view=azureml-api-2#example-custom-dns-server-hosted-on-premises)

### How-to: Give user access from corp on-premises network - Custom DNS Server hosted onpremises
This is needed to avoid Bastion and VM being the only way to access the secure AIFactory

[How-to: Private DNZ zones to forward - for Azure Machine Learning portal & services to work](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-custom-dns?tabs=azure-cli&view=azureml-api-2#example-custom-dns-server-hosted-on-premises)

E.g. the below scenario is what we want to achieve: 

![](./images/14-networking-dns-server.png)

