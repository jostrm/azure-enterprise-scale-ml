#!/bin/bash

# ANSI color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# OPTION 1: ZWVmZDAwZmFjY2ZmODNkNWZmNTg3ODQ3
#--parameters adminPassword="$(date +%s | sha256sum | base64 | head -c 32 ; echo)" \

# OPTION 2: *B03i*ivpM%E%!payASIiP=y
#--parameters adminPassword="$(cat /dev/urandom | tr -dc 'A-Za-z0-9_!@#$%^&*()\-+=' | head -c24 ; echo)" \

# OPTION 3: 1ZZck02NQTNhRDMYTDA0hz8MIxkZDmM2

# Generate parts of the password to ensure complexity
upper=$(head /dev/urandom | tr -dc 'A-Z' | head -c 1)
lower=$(head /dev/urandom | tr -dc 'a-z' | head -c 1)
digit=$(head /dev/urandom | tr -dc '0-9' | head -c 1)
special=$(head /dev/urandom | tr -dc '!@#$%^&*()_+-=[]{}|;:,.<>?' | head -c 1)

# Generate the rest of the password
rest=$(date +%s | sha256sum | base64 | head -c 28)

# Combine all parts
password="$upper$lower$digit$special$rest"

# Shuffle the password to ensure randomness
password=$(echo $password | fold -w1 | shuf | tr -d '\n')

# Ensure the password length is within the specified range (8-123 characters)
password=$(echo $password | head -c 32)

# Output the password
echo $password