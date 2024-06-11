param projectNumber string
param locationSuffix string
param env string

param amlName string
param adfName string
param projectServicePrincipleOID string
param adfPrincipalId string
param technicalContactId string

param technicalAdminsObjectID string // Comma separated

var technicalAdminsObjectID_array = array(split(technicalAdminsObjectID,','))
var technicalAdminsObjectID_array_safe = technicalAdminsObjectID == 'null'? []: technicalAdminsObjectID_array

//-- Needed if connnecting from Databricks to Azure ML workspace
module rbackSPfromDBX2AML '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/machinelearningRBAC.bicep' = {
  name: 'rbacDBX2AazureMLwithProjectSP${projectNumber}${locationSuffix}${env}'
  params: {
    amlName:amlName
    projectSP:projectServicePrincipleOID // Note: SP OID: it must be the OBJECT ID of a service principal, not the OBJECT ID of an Application, different thing, and I have to agree it is very confusing.
    adfSP:adfPrincipalId
    projectADuser:technicalContactId
    additionalUserIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [

  ]
}

module rbacADFfromUser '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/datafactoryRBAC.bicep' = {
  name: 'rbacADFFromAMLorProjSP${projectNumber}${locationSuffix}${env}'
  params: {
    datafactoryName:adfName
    userPrincipalId:technicalContactId
    additionalUserIds: technicalAdminsObjectID_array_safe
  }
  dependsOn: [

  ]
}
