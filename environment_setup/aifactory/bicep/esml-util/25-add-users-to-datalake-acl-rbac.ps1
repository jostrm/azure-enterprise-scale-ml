# USAGE: .\aifactory\esml-util\25-add-users-to-datalake-acl-rbac.ps1 -spSecret "abc" -spID "abc" -tenantID "abc" -subscriptionID "abc" -storageAccount "abcd" -adlsgen2filesystem "lake3" -projectXXX "project001" -userObjectIds a,b,c -projectSPObjectID "a" -commonSPObjectID "abc" -commonADgroupObjectID "TODO" -projectADGroupObjectId "TODO"

param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Specifies the secret for service principal")][string]$spSecret,
    [Parameter(Mandatory=$true, HelpMessage="Specifies the object id for service principal, with Storage Blob Data Owner role")][string]$spID,
    [Parameter(Mandatory = $true, HelpMessage = "Tenant ID")][string]$tenantID,
    [Parameter(Mandatory = $true, HelpMessage = "Subscription ID")][string]$subscriptionID,
    [Parameter(Mandatory = $true, HelpMessage = "ESML AIFactory datalake name")][string]$storageAccount,
    [Parameter(Mandatory=$true, HelpMessage="Override the default ESML datalake container called: lake3")][string]$adlsgen2filesystem,
    [Parameter(Mandatory = $true, HelpMessage = "ESMLProject number: project001")][string]$projectXXX,
    [Parameter(Mandatory = $true, HelpMessage = "Array of user Object Ids")][string[]]$userObjectIds,
    [Parameter(Mandatory = $true, HelpMessage = "Project service principle OID esml-project001-sp-oid")][string]$projectSPObjectID,
    [Parameter(Mandatory = $true, HelpMessage = "Common service principle OID common")][string]$commonSPObjectID,
    # optional
    [Parameter(Mandatory = $false, HelpMessage = "Common AD group OID common. Set to TODO to ignore")][string]$commonADgroupObjectID = 'TODO',
    [Parameter(Mandatory = $false, HelpMessage = "Project AD group OID common. Set to TODO to ignore")][string]$projectADGroupObjectId = 'TODO'
)

$userObjectIds += $projectSPObjectID
$ctx = $null

if (-not [String]::IsNullOrEmpty($spSecret)) {
    Write-Host "The spID parameter is not null or empty. trying to authenticate to Azure with Service principal"
    Write-Host "The spID: ${spID}"
    Write-Host "The tenantID: ${tenantID}"
  
    $SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
    $credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
    Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID
    $ctx = New-AzStorageContext -StorageAccountName $storageAccount -UseConnectedAccount
  
    if ($(Get-AzContext).Subscription -ne "") {
      write-host "Successfully logged in as $($(Get-AzContext).Account) to $($(Get-AzContext).Subscription)"
      #$ctx = New-AzStorageContext -StorageAccountName $storageAccount -UseConnectedAccount
      write-host "Set-AzContext to subscription: ${subcriptionID}"
      Set-AzContext -Subscription $(Get-AzContext).Subscription
    }
    else {
      Write-Host "Failed to login to Azure with Service Principal. Exiting..."
    }
} else {
    # The $spID parameter is null or empty
    Write-Host "The spID parameter is null or empty. Running under other authentication that SP"
}

Write-Host "userObjectIds again: $userObjectIds"
# userObjectIds again: 64fd2935-96c6-4a50-9d47-a3bd59adffba esml-project001-sp-oid

if (-not [String]::IsNullOrEmpty($ctx)) {
    Write-Host "ctx is not null or empty."
    Write-Host "ctx is  $ctx"
}

# FOLDERS
$active = "active/"
$logging = "logging/"
$master = "master/"
$projects = "projects/"
$myproject = "projects/$projectXXX/"

Write-Host " 1)INIT status: container ACLs for $adlsgen2filesystem"
if ($null -eq $ctx) {
    Write-Host "Could not get ctx $ctx"
    exit 1
}

Write-Host $PSVersionTable.PSVersion
$PSVersionTable.PSVersion
Get-Module -Name Az -ListAvailable | Select-Object -Property Name,Version

$filesystem = Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem

if ($null -eq $filesystem) {
    Write-Host "Could not get filesystem $adlsgen2filesystem"
} 

# Common SP container: Execute (Default)
#$aclContainerEDefault = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
$aclContainerEDefault = $filesystem.ACL

if ($null -eq $aclContainerEDefault) {
    Write-Host "NULL -  aclContainerEDefault $aclContainerEDefault"
    Write-Host "Possible reason A - You have not installed the POwershell module: Install-Module Az.Storage -Repository PSGallery -Scope CurrentUser -Force"
    Write-Host "Possible reason B - The storage account is note reachable networking wise, from the build agent / executing machine. Check firewall rules on storage account, or use a buildagent inside vNet"
    Write-Host "Possible reason C - Either wrong Powershell version (tested on 7.2.18) or Az module version for Get-AzDataLakeGen2Item (tested on Az 5.2.0, Az 7.3.0). Run as inline with: pwsh -Command {} "
    Write-Host "Possible reason D - Service principal role:: Blob Storage Data Owner, is needed. The exectuting service principal / user, needs to have RBAC role to read the ACLs on the datalake filesystem, meaning role: Blob Storage Data Owner"
    Write-Host "FAILURE will happen here: This command will fail - Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId _commonSPObjectID -Permission --x -DefaultScope -InputObject _aclContainerEDefault "
    Write-Host " - Since null on _aclContainerEDefault"
    Write-Host "ERROR message will be: Cannot bind argument to parameter 'InputObject' because it is null."
}
if ($null -eq $commonSPObjectID) {
    Write-Host "NULL -  commonSPObjectID $commonSPObjectID"
} 

$aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $commonSPObjectID -Permission --x -DefaultScope -InputObject $aclContainerEDefault
Write-Host "DEBUG 3"
$aclContainerEDefault = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $commonSPObjectID -Permission --x -InputObject $aclContainerEDefault
Write-Host "DEBUG 4"

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