param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory = $false, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
    [Parameter(Mandatory=$false, HelpMessage="Specifies the object id for service principal, with Storage Blob Data Owner role")][string]$spID,
    [Parameter(Mandatory = $false, HelpMessage = "Specifies the secret for service principal")][string]$tenantID,
    [Parameter(Mandatory = $false, HelpMessage = "ESMLProject number: project001")][string]$projectXXX,
    # user OID's
    [Parameter(Mandatory = $false, HelpMessage = "ESMLProject number: project001")][string[]]$userObjectIds,
    [Parameter(Mandatory = $false, HelpMessage = "ESMLProject number: project001")][string]$projectADGroupObjectId,
    [Parameter(Mandatory = $false, HelpMessage = "ESMLProject number: project001")][string]$commonSPObjectID,
    [Parameter(Mandatory = $false, HelpMessage = "ESMLProject number: project001")][string]$commonADgroupObjectID,

    # optional override parameters
    [Parameter(Mandatory=$false, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem
)

# USAGE: .\aifactory\esml-util\200-datalake-acl-rbac.ps1 -spSecret "abc"

Import-Module Az.Storage

#### Trouble shoot ####
$storageAccount ="TODO"
$spID ="TODO SP AppID - with Storage Blob Data Owner role" # Storage Blob Data Owner role. (esml-common-sp)
$tenantID ="TODO"
$adlsgen2filesystem ="lake3"
$projectXXX = "project001"
$projectSPObjectID = "TODO ObjectID"
$userObjectIds = @("TODO ObjectID","TODO ObjectID","TODO ObjectID",$projectSPObjectID) # users + project001-sp-oid
$commonSPObjectID = "TODO ObjectID" # esml-common-sp
$commonADgroupObjectID = "TODO" # AD group: esml-common-coreteam 
$projectADGroupObjectId = "TODO" # AD group: esml-project002
#### Trouble shoot END ####

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

if ($commonADgroupObjectID -ne "TODO") {
    $aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonADgroupObjectID -Permission --x -DefaultScope -InputObject $aclContainerEDefault
    $aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonADgroupObjectID -Permission --x -InputObject $aclContainerEDefault
}
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
    #$aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -DefaultScope -InputObject $aclContainerUser
    Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerUser

    # 1) READ & EXECUTE (Default) - active logging
    $aclActiveReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $active).ACL
    $aclActiveReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission rwx -InputObject $aclActiveReadExecute
    $aclActiveReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission rwx -DefaultScope -InputObject $aclActiveReadExecute
    $aclActiveReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -InputObject $aclActiveReadExecute
    $aclActiveReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -DefaultScope -InputObject $aclActiveReadExecute
    # 2) Update permission of a new ACL entry (if ACL entry with same AccessControlType/EntityId/DefaultScope not exist, will add a new ACL entry, else update permission of existing ACL entry)
    $aclActiveReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission rwx -InputObject $aclActiveReadExecute
    $aclActiveReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission rwx -DefaultScope -InputObject $aclActiveReadExecute
    # 3) Set the new acl to the directory
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $active -Acl $aclActiveReadExecute # If not resursive, use Update-AzDataLakeGen2Item instead, to commit the ACL
        # Update-AzDataLakeGen2Item -FileSystem "filesystem1" -Path 'dir1/dir3/' -ACL $acl

    $aclLoggingReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging).ACL
    $aclLoggingReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission r-x -InputObject $aclLoggingReadExecute
    $aclLoggingReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission r-x -DefaultScope -InputObject $aclLoggingReadExecute
    $aclLoggingReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -InputObject $aclLoggingReadExecute
    $aclLoggingReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -DefaultScope -InputObject $aclLoggingReadExecute
    $aclLoggingReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission r-x -InputObject $aclLoggingReadExecute
    $aclLoggingReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission r-x -DefaultScope -InputObject $aclLoggingReadExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging -Acl $aclLoggingReadExecute

    # myproject: EXECUTE (Default) - master, projects
    $aclMasterExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $master).ACL
    $aclMasterExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -DefaultScope -InputObject $aclMasterExecute
    $aclMasterExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -InputObject $aclMasterExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $master -Acl $aclMasterExecute
    
    $aclProjectsExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects).ACL
    #$aclProjectsExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -DefaultScope -InputObject $aclProjectsExecute
    $aclProjectsExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -InputObject $aclProjectsExecute
    Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects -Acl $aclProjectsExecute

    # myproject: RWE (Default) - myproject
    $aclProjectRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject).ACL
    $aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission rwx -DefaultScope -InputObject $aclProjectRWE
    $aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission rwx -InputObject $aclProjectRWE
    #Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclProjectRWE
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclProjectRWE
}

Write-Host " 3) All USERS OID's for PROJECT FOLDER + $myproject is updated."
if ($projectADGroupObjectId -ne "TODO") {
    # container:projectADGroupObjectId: EXECUTE 
    $aclContainerUser = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
    $aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -InputObject $aclContainerUser
    Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerUser

    # container:projectADGroupObjectId: EXECUTE (Default)
    $aclContainerUser = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
    $aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -DefaultScope -InputObject $aclContainerUser
    Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerUser

    # active, logging: READ & EXECUTE (Default)
    $aclActiveADReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $active).ACL
    $aclActiveADReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission rwx -DefaultScope -InputObject $aclActiveADReadExecute
    $aclActiveADReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission rwx -InputObject $aclActiveADReadExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $active -Acl $aclActiveADReadExecute # If not resursive, use Update-AzDataLakeGen2Item instead, to commit the ACL

    $aclLoggingADReadExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging).ACL
    $aclLoggingADReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission r-x -DefaultScope -InputObject $aclLoggingADReadExecute
    $aclLoggingADReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission r-x -InputObject $aclLoggingADReadExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging -Acl $aclLoggingADReadExecute

    # master,projects: EXECUTE (Default)
    $aclMasterADExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $master).ACL
    $aclMasterADExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -DefaultScope -InputObject $aclMasterADExecute
    $aclMasterADExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -InputObject $aclMasterADExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $master -Acl $aclMasterADExecute

    $aclProjectsADExecute = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects).ACL
    $aclProjectsADExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -DefaultScope -InputObject $aclProjectsADExecute
    $aclProjectsADExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission --x -InputObject $aclProjectsADExecute
    Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects -Acl $aclProjectsADExecute
    
    # myproject: RWE (project AD group)
 
    $aclProjectADRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject).ACL
    $aclProjectADRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission rwx -DefaultScope -InputObject $aclProjectADRWE
    $aclProjectADRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectADGroupObjectId -Permission rwx -InputObject $aclProjectADRWE
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclProjectADRWE
 }

Write-Host " 4) PROJECT AD group OID  for PROJECT FOLDER + $myproject is updated."

$aclProjectCmnSPRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject).ACL
$aclProjectCmnSPRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonSPObjectID -Permission rwx -DefaultScope -InputObject $aclProjectCmnSPRWE
$aclProjectCmnSPRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonSPObjectID -Permission rwx -InputObject $aclProjectCmnSPRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclProjectCmnSPRWE

Write-Host " 5) COMMON Service Principle - esml-common-sp (OID for MYPROJECT FOLDER) + $myproject is updated."

$aclMyProjectSPRWE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject).ACL
$aclMyProjectSPRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectSPObjectID -Permission rwx -DefaultScope -InputObject $aclMyProjectSPRWE
$aclMyProjectSPRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $projectSPObjectID -Permission rwx -InputObject $aclMyProjectSPRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclMyProjectSPRWE

Write-Host " 5) PROJECT Service Principle - projectXXX-sp (OID for MYPROJECT FOLDER) + $myproject is updated."

# Common SP root: RWE
if ($projectADGroupObjectId -ne "TODO") {
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
}
Write-Host " 6) FINISHED! COMMON AD group & COMMON SP ACL's are updated."