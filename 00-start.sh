#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Instructions: 
## 1)Run this file from your own parent repository, not from the azure-enterprise-scale-ml repository.
### Example ./enterprise-scale-ml/00-start.sh
## 2) Then you will have the files below in your repository, to run directory, as ./01-aif-copy-aifactory-templates.sh


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Copy template file and bootstrap files
cp "$SCRIPT_DIR/bootstrap/01-aif-copy-aifactory-templates.sh" "$SCRIPT_DIR/../01-aif-copy-aifactory-templates.sh"
cp "$SCRIPT_DIR/bootstrap/02a-GH-bootstrap-files.sh" "$SCRIPT_DIR/../02a-GH-bootstrap-files.sh"
cp "$SCRIPT_DIR/bootstrap/02b-ADO-bootstrap-files.sh" "$SCRIPT_DIR/../02b-ADO-bootstrap-files.sh"