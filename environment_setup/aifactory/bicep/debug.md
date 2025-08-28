# System Prompt
This is system prompt, instructions what you should do as a model. Keep the structure of presentation that 'parse-debug-error-template.ps1' has. Then Exract from Error Message section the below things
- Exception Detail Message, such as "The role assignment already exists".
- Exception Detail Code, such as: "RoleAssignmentExists"
- Bicep module, such as: 05-miRbacCmnACR-esml-p001-dev-eus2--001-001-65-compute-services
- Line number: Such as 1579 in "column '1579'"
- End of Error message: Such as "is defined multiple times in a template"

Do not extract noise, such as: "Please see..." or "Deployment template validation failed:"
It should also be as generic, for any BICEP error message. Not onoy for RoleAssignmentExists

Also present recommendations to solve the error add that to the section RECOMMENDATIONS and ACTIONS in 'parse-debug-error-template.ps1 

# Error message, that will change, for you to write a new file called 'parse-debug-error-1.ps1'
	Exception Details:	(ContainerAppOperationError) Failed to provision revision for container app 'aca-a-prj001eus2devqoygy-001'. 
	Error details: The following field(s) are either invalid or missing. Field 'template.containers.main.image' 
	is invalid with details: 'Invalid value: "acrcommonqoygyeus2001dev.azurecr.io/containerapps-default:latest": GET https://acrcommonqoygyeus2001dev.eastus2.data.azurecr.io?c=REDACTED&d=REDACTED&h=REDACTED&l=REDACTED&p=REDACTED&r=REDACTED&s=REDACTED&t=REDACTED&v=REDACTED: DENIED: requested access to the resource is denied';..
								Code: ContainerAppOperationError
								Message: Failed to provision revision for container app 'aca-a-prj001eus2devqoygy-001'. 
								Error details: The following field(s) are either invalid or missing. 
								Field 'template.containers.main.image' is invalid with details: 
								'Invalid value: "acrcommonqoygyeus2001dev.azurecr.io/containerapps-default:latest": 
								GET https://acrcommonqoygyeus2001dev.eastus2.data.azurecr.io?c=REDACTED&d=REDACTED&h=REDACTED&l=REDACTED&p=REDACTED&r=REDACTED&s=REDACTED&t=REDACTED&v=REDACTED:
								DENIED: requested access to the resource is denied';..	
								(InvalidTemplate) Deployment template validation failed: 
								'The resource 'Microsoft.Authorization/roleAssignments/2486cbb8-27cd-5e4a-8d02-bdb3f9fb5c89' at line '1' and column '1549' 
								is defined multiple times in a template. Please see https://aka.ms/arm-syntax-resources for usage details.'.
	Code: InvalidTemplate
