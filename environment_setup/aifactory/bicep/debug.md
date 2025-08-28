# System Prompt
This is system prompt, instructions what you should do as a model. Keep the structure of presentation that 'parse-debug-errors.ps1' has. Then Exract from Error Message section the below things
- Exception Detail Message, such as "The role assignment already exists".
- Exception Detail Code, such as: "RoleAssignmentExists"
- Bicep module, such as: 05-miRbacCmnACR-esml-p001-dev-eus2--001-001-65-compute-services
- Line number: Such as 1579 in "column '1579'"
- End of Error message: Such as "is defined multiple times in a template"

Do not extract noise, such as: "Please see..." or "Deployment template validation failed:"
It should also be as generic, for any BICEP error message. Not onoy for RoleAssignmentExists

Also present recommendations to solve the error add that to the section RECOMMENDATIONS and ACTIONS in 'parse-debug-errors.ps1 

# Error message, that will change, for you to write a new file called 'parse-debug-errors-2.ps1'

esml-p001-dev-eus2--001-001-65-compute-services
Exception Details:	(InvalidTemplate) Deployment template validation failed: 'The resource 'Microsoft.Authorization/roleAssignments/b16a6cb2-0450-516c-aa0c-c853b487b2f6' at line '1' and column '1579' is defined multiple times in a template. Please see https://aka.ms/arm-syntax-resources for usage details.'.
	Code: InvalidTemplate
	Message: Deployment template validation failed: 'The resource 'Microsoft.Authorization/roleAssignments/b16a6cb2-0450-516c-aa0c-c853b487b2f6' at line '1' and column '1579' is defined multiple times in a template. Please see https://aka.ms/arm-syntax-resources for usage details.'.	(InvalidTemplate) Deployment template validation failed: 'The resource 'Microsoft.Authorization/roleAssignments/2486cbb8-27cd-5e4a-8d02-bdb3f9fb5c89' at line '1' and column '1549' is defined multiple times in a template. Please see https://aka.ms/arm-syntax-resources for usage details.'.
	Code: InvalidTemplate
	Message: Deployment template validation failed: 'The resource 'Microsoft.Authorization/roleAssignments/2486cbb8-27cd-5e4a-8d02-bdb3f9fb5c89' at line '1' and column '1549' is defined multiple times in a template. Please see https://aka.ms/arm-syntax-resources for usage details.'.	(ResourceDeploymentFailure) The resource write operation failed to complete successfully, because it reached terminal provisioning state 'Failed'.
	Code: ResourceDeploymentFailure
	Message: The resource write operation failed to complete successfully, because it reached terminal provisioning state 'Failed'.
	Target: /subscriptions/612e830e-b795-424e-ba5d-cd0a5dadecf4/resourceGroups/mrvel-1-esml-common-eus2-dev-010/providers/Microsoft.Resources/deployments/05-miPrjRbacCmnACR-esml-p001-dev-eus2--001-001-65-compute-servic
	Exception Details:	(DeploymentFailed) At least one resource deployment operation failed. Please list deployment operations for details. Please see https://aka.ms/arm-deployment-operations for usage details.
		Code: DeploymentFailed
		Message: At least one resource deployment operation failed. Please list deployment operations for details. Please see https://aka.ms/arm-deployment-operations for usage details.
		Target: /subscriptions/612e830e-b795-424e-ba5d-cd0a5dadecf4/resourceGroups/mrvel-1-esml-common-eus2-dev-010/providers/Microsoft.Resources/deployments/05-miPrjRbacCmnACR-esml-p001-dev-eus2--001-001-65-compute-servic
		Exception Details:	(RoleAssignmentExists) The role assignment already exists.
			Code: RoleAssignmentExists
			Message: The role assignment already exists.	(ResourceDeploymentFailure) The resource write operation failed to complete successfully, because it reached terminal provisioning state 'Failed'.
	Code: ResourceDeploymentFailure
	Message: The resource write operation failed to complete successfully, because it reached terminal provisioning state 'Failed'.
	Target: /subscriptions/612e830e-b795-424e-ba5d-cd0a5dadecf4/resourceGroups/mrvel-1-esml-common-eus2-dev-010/providers/Microsoft.Resources/deployments/05-miRbacCmnACR-esml-p001-dev-eus2--001-001-65-compute-services-
	Exception Details:	(DeploymentFailed) At least one resource deployment operation failed. Please list deployment operations for details. Please see https://aka.ms/arm-deployment-operations for usage details.
		Code: DeploymentFailed
		Message: At least one resource deployment operation failed. Please list deployment operations for details. Please see https://aka.ms/arm-deployment-operations for usage details.
		Target: /subscriptions/612e830e-b795-424e-ba5d-cd0a5dadecf4/resourceGroups/mrvel-1-esml-common-eus2-dev-010/providers/Microsoft.Resources/deployments/05-miRbacCmnACR-esml-p001-dev-eus2--001-001-65-compute-services-
		Exception Details:	(RoleAssignmentExists) The role assignment already exists.
			Code: RoleAssignmentExists
			Message: The role assignment already exists.
