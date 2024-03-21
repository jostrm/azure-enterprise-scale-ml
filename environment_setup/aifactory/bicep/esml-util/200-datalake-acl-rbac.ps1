param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the object id for service principal, with Storage Blob Data Owner role")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $true, HelpMessage = "ESMLProject number: project001")][string]$projectXXX,
    # OID's: User OID's including project SP OID, project AD group, Common SP, Common AD group
    [Parameter(Mandatory = $true, HelpMessage = "ESMLProject number: project001")][string[]]$userObjectIds,
    [Parameter(Mandatory = $true, HelpMessage = "ESMLProject number: project001")][string]$projectADGroupObjectId,
    [Parameter(Mandatory = $true, HelpMessage = "ESMLProject number: project001")][string]$commonSPObjectID,
    [Parameter(Mandatory = $true, HelpMessage = "ESMLProject number: project001")][string]$commonADgroupObjectID,

    # optional parameter: If other name on filesystem/container
    [Parameter(Mandatory=$false, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem
)

Import-Module Az.Storage

# $storageAccount ="TODO: esml datalake name"
# $spID ="TODO AppID for SP with Storage Blob Data Owner role" # Storage Blob Data Owner role
# $spSecret ="TODO - do not check in SECRET" # TODO: Pass as parameter
# $tenantID ="TODO tenantID"
# $adlsgen2filesystem ="lake3"
# $projectXXX = "TODO project001" #project001, project002, etc
# $userObjectIds = @("TODO objectID of user1","TODO objectID of user2","TODO objectID of project001-sp-oid") # users + project001-sp-oid
# $projectADGroupObjectId = "TODO objectID of projectXXX-AD-group" # AD group: esml-project002
# $commonSPObjectID = "TODO objectID of esml-common-sp" # esml-common-sp
# $commonADgroupObjectID = "TODO objectOD of esml-common AD group for coreteam" # AD group: esml-common-coreteam 

$SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
$credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID
$ctx = New-AzStorageContext -StorageAccountName $storageAccount -UseConnectedAccount

# FOLDERS
$active = "active/"
$logging = "logging/"
$master = "master/"
$projects = "projects/"
$myproject = "projects/$projectXXX/"

Write-Host " 1)INIT status: container ACLs for $adlsgen2filesystem"
$filesystem = Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem
$filesystem.ACL

# Common SP container: Execute (Default)
$aclContainerEDefault = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
$aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $commonSPObjectID -Permission --x -DefaultScope -InputObject $aclContainerEDefault
$aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $commonSPObjectID -Permission --x -InputObject $aclContainerEDefault
$aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonADgroupObjectID -Permission --x -DefaultScope -InputObject $aclContainerEDefault
$aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonADgroupObjectID -Permission --x -InputObject $aclContainerEDefault
$aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission --- -InputObject $aclContainerEDefault
Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerEDefault
$filesystem = Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem

Write-Host " 2) UPDATED status: container ACLs for $adlsgen2filesystem"
$filesystem.ACL

# All users in project
for ($i=0; $i -lt $userObjectIds.Length; $i++) {
    $userID = $userObjectIds[$i]

    # container: PROJECT USER - EXECUTE - container
    $aclContainerUser = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
    $aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -InputObject $aclContainerUser
    $aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -DefaultScope -InputObject $aclContainerUser
    Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerUser

    # 1) READ & EXECUTE (Default) - active logging
    $aclProjectReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject).ACL
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission r-x -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission r-x -DefaultScope -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -DefaultScope -InputObject $aclProjectReadExecute
    # 2) Update permission of a new ACL entry (if ACL entry with same AccessControlType/EntityId/DefaultScope not exist, will add a new ACL entry, else update permission of existing ACL entry)
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission r-x -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission r-x -DefaultScope -InputObject $aclProjectReadExecute
    # 3) Set the new acl to the directory
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $active -Acl $aclProjectReadExecute # If not resursive, use Update-AzDataLakeGen2Item instead, to commit the ACL
        # Update-AzDataLakeGen2Item -FileSystem "filesystem1" -Path 'dir1/dir3/' -ACL $acl

    $aclProjectReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging).ACL
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission r-x -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission r-x -DefaultScope -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -DefaultScope -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission r-x -InputObject $aclProjectReadExecute
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission r-x -DefaultScope -InputObject $aclProjectReadExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging -Acl $aclProjectReadExecute

    # myproject: EXECUTE (Default) - master, projects
    $aclProjectExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $master).ACL
    $aclProjectExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -DefaultScope -InputObject $aclProjectExecute
    $aclProjectExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -InputObject $aclProjectExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $master -Acl $aclProjectExecute
    
    $aclProjectExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects).ACL
    $aclProjectExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -DefaultScope -InputObject $aclProjectExecute
    $aclProjectExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -InputObject $aclProjectExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects -Acl $aclProjectExecute

    # myproject: RWE (Default) - myproject
    $aclProjectRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject).ACL
    $aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission rwx -DefaultScope -InputObject $aclProjectRWE
    $aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission rwx -InputObject $aclProjectRWE
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclProjectRWE
}

Write-Host " 3) All USERS OID's for PROJECT FOLDER + $myproject is updated."

 # container:projectADGroupObjectId: EXECUTE 
 $aclContainerUser = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
 $aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -InputObject $aclContainerUser
 Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerUser

 # container:projectADGroupObjectId: EXECUTE (Default)
 $aclContainerUser = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
 $aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -DefaultScope -InputObject $aclContainerUser
 Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerUser

 # active, logging: READ & EXECUTE (Default)
 $aclProjectReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $active).ACL
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission r-x -DefaultScope -InputObject $aclProjectReadExecute
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission r-x -InputObject $aclProjectReadExecute
 Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $active -Acl $aclProjectReadExecute # If not resursive, use Update-AzDataLakeGen2Item instead, to commit the ACL

 $aclProjectReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging).ACL
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission r-x -DefaultScope -InputObject $aclProjectReadExecute
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission r-x -InputObject $aclProjectReadExecute
 Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging -Acl $aclProjectReadExecute

 # master,projects: EXECUTE (Default)
 $aclProjectReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $master).ACL
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -DefaultScope -InputObject $aclProjectReadExecute
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -InputObject $aclProjectReadExecute
 Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $master -Acl $aclProjectReadExecute

 $aclProjectReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects).ACL
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -DefaultScope -InputObject $aclProjectReadExecute
 $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -InputObject $aclProjectReadExecute
 Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects -Acl $aclProjectReadExecute
 
 # myproject: RWE
 $aclProjectRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject).ACL
 $aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission rwx -DefaultScope -InputObject $aclProjectRWE
 Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclProjectRWE

Write-Host " 4) PROJECT AD group OID  for PROJECT FOLDER + $myproject is updated."

# Common SP root: RWE
$aclCommonRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $active).ACL
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -DefaultScope -InputObject $aclCommonRWE
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -InputObject $aclCommonRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $active -Acl $aclCommonRWE

$aclCommonRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging).ACL
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -DefaultScope -InputObject $aclCommonRWE
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -InputObject $aclCommonRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging -Acl $aclCommonRWE

$aclCommonRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $master).ACL
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -DefaultScope -InputObject $aclCommonRWE
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -InputObject $aclCommonRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $master -Acl $aclCommonRWE

$aclCommonRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects).ACL
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -DefaultScope -InputObject $aclCommonRWE
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $projectADGroupObjectId -Permission rwx -InputObject $aclCommonRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects -Acl $aclCommonRWE


Write-Host " 5) FINISHED! COMMON AD group & COMMON SP ACL's are updated."