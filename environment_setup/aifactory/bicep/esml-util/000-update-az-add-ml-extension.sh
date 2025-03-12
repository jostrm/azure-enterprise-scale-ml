#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

az version

az upgrade

az extension remove --name ml
az extension add --name ml --version 2.34.0 # 2.35.0
az extension add --name ai-examples --version 0.2.5
az extension add --name ssh --version 2.0.6

az version

# az extension remove --name storage-preview
# az extension update --name ml # 2.35.0
# az extension update --name bastion # 1.4.0