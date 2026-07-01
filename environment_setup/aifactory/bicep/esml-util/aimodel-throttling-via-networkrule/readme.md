# Instructions

I want you to create code to have Fondry model deployments, exisitng deployments, throttled/capped, if consumption is exceeding a threshold. 

# Requirements: 
- It should work to deploy centrally, on a vNet or Private DMS zoje.  without the teams needing to change anything in their Foundry instance
- It should works real-time, looks at consumption.
- It should block reqeusets, if overconsuming on resource group, or subscriptiom level

## Chain of solution
Azure Monitor -> Consumption Alert ->  Logic App / Function -> Disable network access
 
## Example of process
Example: If Monthly tokens is > 50M -> then we remove DNS mapping/disable private endpoint access
...We return "429 Too Many Requests"

# How to find names of resources in the AI Factory

It depends if user uses Azure Devops or Github

If Azure devops, then the Variables.yaml should be used. It is located under their "aifactory" folder at this location with real values: aifactory\esml-infra\azure-devops\bicep\yaml\variables\variables.yaml
- But hte template you can always use to know what variables exists. This is located here: environment_setup\aifactory\bicep\copy_to_local_settings\azure-devops\esml-yaml-pipelines\variables\variables.yaml

If Github, then the .env file at root should be looked at, a template exists here: environment_setup\aifactory\bicep\copy_to_local_settings\github-actions\.env.template  which you can use to see "which variables", but not the real values.  The real values should be read from root where the .env file is 

## Common resource group

## Project specific resource group


