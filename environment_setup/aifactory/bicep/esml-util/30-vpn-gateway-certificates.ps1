# The following example creates a self-signed root certificate named 'P2SRootCert' 
# that's automatically installed in 'Certificates-Current User\Personal\Certificates'. 
# You can view the certificate by opening certmgr.msc, or Manage User Certificates.
# https://learn.microsoft.com/en-us/azure/vpn-gateway/vpn-gateway-certificates-point-to-site#rootcert

$params = @{
    Type = 'Custom'
    Subject = 'CN=P2SAIFactoryRootCert'
    KeySpec = 'Signature'
    KeyExportPolicy = 'Exportable'
    KeyUsage = 'CertSign'
    KeyUsageProperty = 'Sign'
    KeyLength = 2048
    HashAlgorithm = 'sha256'
    NotAfter = (Get-Date).AddMonths(24)
    CertStoreLocation = 'Cert:\CurrentUser\My'
}
$cert = New-SelfSignedCertificate @params

# CLIENT
$params = @{
    Type = 'Custom'
    Subject = 'CN=P2SAIFactoryChildCert'
    DnsName = 'P2SChildCertAIF'
    KeySpec = 'Signature'
    KeyExportPolicy = 'Exportable'
    KeyLength = 2048
    HashAlgorithm = 'sha256'
    NotAfter = (Get-Date).AddMonths(18)
    CertStoreLocation = 'Cert:\CurrentUser\My'
    Signer = $cert
    TextExtension = @(
     '2.5.29.37={text}1.3.6.1.5.5.7.3.2')
}
New-SelfSignedCertificate @params