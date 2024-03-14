Import-Module Az.Storage

$storageAccount ="TODO pass as param - lake"
$spID ="TODO pass as param SP with - Storage Blob Data Owner role" # Storage Blob Data Owner role
$spSecret ="TODO pass as param"
$tenantID ="TODO pass as param"
$adlsgen2filesystem ="TODO pass as param -lake3"
$SecureStringPwd = $spSecret | ConvertTo-SecureString -AsPlainText -Force
$credential = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList $spID, $SecureStringPwd
Connect-AzAccount -ServicePrincipal -Credential $credential -Tenant $tenantID

$ctx = New-AzStorageContext -StorageAccountName $storageAccount -UseConnectedAccount

# USERS OID: Define the users and groups to give access
$projectXXX = "TODO pass as param - project001"
$userObjectIds = @("TODO pass as param OID - aduser-oid", "TODO  project001-sp-oid") # aduser-oid, project001-sp-oid
$commonSPObjectID = "TODO - esml-common-sp OID" # esml-common-sp
$commonADgroupObjectID = "TODO - AD group OID - esml-common-coreteam" # esml-common-coreteam AD group

# SET permissions: USERS
$acl = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -Permission rwx
$aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission r-x -InputObject $acl
$aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -InputObject $aclProjectReadExecute

$aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -Permission rwx -InputObject $acl
$aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -InputObject $aclProjectRWE

#  SET permissions: COMMON SP OID + COMMON AD GROUP
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonADgroupObjectID -Permission rwx
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission "---" -InputObject $aclCommonRWE
$aclCommonRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $commonSPObjectID -Permission rwx -DefaultScope -InputObject $aclProjectRWE

# FOLDERS
$active = "active"
$logging = "logging"
$master = "master"
$projects = "projects"
$myproject = "projects/$projectXXX"

Write-Host " 1)INIT status: container ACLs for $adlsgen2filesystem"
$filesystem = Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem
$filesystem.ACL

# Common SP container: RE: 
$aclContainerE = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
$aclContainerE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $commonSPObjectID -Permission --x -InputObject $aclContainerE
$aclContainerE = Set-AzDataLakeGen2ItemAclObject -AccessControlType group -EntityId $commonADgroupObjectID -Permission --x -InputObject $aclContainerE
$aclContainerE = Set-AzDataLakeGen2ItemAclObject -AccessControlType other -Permission --- -InputObject $aclContainerE
Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerE
$filesystem = Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem

Write-Host " 2) UPDATED status: container ACLs for $adlsgen2filesystem"
$filesystem.ACL

# All users in project
for ($i=0; $i -lt $userObjectIds.Length; $i++) {
    $userID = $userObjectIds[$i]

    # container: PROJECT USER - Execute
    $aclContainerUser = (Get-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem).ACL
    $aclContainerUser = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission --x -InputObject $aclContainerUser
    Update-AzDataLakeGen2Item -Context $ctx -FileSystem $adlsgen2filesystem -Acl $aclContainerUser

    # root: READ & EXECUTE
    $aclProjectReadExecute = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission r-x -DefaultScope -InputObject $aclProjectReadExecute

    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $active -Acl $aclProjectReadExecute # If not resursive, use Update-AzDataLakeGen2Item instead, to commit the ACL
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging -Acl $aclProjectReadExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $master -Acl $aclProjectReadExecute
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects -Acl $aclProjectReadExecute

    # myproject: RWE
    $aclProjectRWE = Set-AzDataLakeGen2ItemAclObject -AccessControlType user -EntityId $userID -Permission rwx -DefaultScope -InputObject $aclProjectRWE
    Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $myproject -Acl $aclProjectRWE
}

Write-Host " 3) USERS OID's for PROJECT FOLDER + $myproject is updated."

# Common SP root: RWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $active -Acl $aclCommonRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $logging -Acl $aclCommonRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $master -Acl $aclCommonRWE
Update-AzDataLakeGen2AclRecursive -Context $ctx -FileSystem $adlsgen2filesystem -Path $projects -Acl $aclCommonRWE

Write-Host " 4) FINISHED! COMMON AD group & COMMON SP ACL's are updated."