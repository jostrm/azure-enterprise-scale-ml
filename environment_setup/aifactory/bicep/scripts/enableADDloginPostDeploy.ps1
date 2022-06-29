$vmName = "vm00001"
$vmRgName = "azsec-corporate-rg"
$extensionName = "AADLoginForWindows"
$publisher = "Microsoft.Azure.ActiveDirectory"

$vm = Get-AzVm -ResourceGroupName $vmRgName -Name $vmName
Set-AzVMExtension -ResourceGroupName $vmRgName `
                    -VMName $vm.Name `
                    -Name $extensionName `
                    -Location $vm.Location `
                    -Publisher $publisher `
                    -Type "AADLoginForWindows" `
                    -TypeHandlerVersion "1.0"