#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

az login --tenant ""

vNetName= ""
subNetName= ""
amlWorkspace= ""

az ml compute create --name csi001 --resource-group rg --workspace-name ${amlWorkspace} --vnet-name ${vNetName} --subnet ${subNetName} --type ComputeInstance --set enable_node_public_ip=False