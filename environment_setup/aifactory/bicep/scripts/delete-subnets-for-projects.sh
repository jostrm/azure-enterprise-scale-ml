#!/bin/bash
# =============================================================================
# delete-subnets-for-projects.sh
#
# Deletes the project subnets (and their NSGs) for a RANGE of AI Factory
# projects from a given VNet, ONE project at a time, ONE subnet at a time.
#
# Logic is ported from the tested scripts/delete-services-if-disabled.sh
# (Step 7 = subnets, Step 8 = NSGs):
#   - Project subnets follow the pattern  snt-prj{nnn}-{purpose}
#     (e.g. snt-prj003-aks, snt-prj012-genai); NSGs follow nsg-snt-prj{nnn}-{purpose}.
#   - Matching is CASE-INSENSITIVE (grep -i) because AI Foundry capability-host /
#     network-injection auto-provisioning can rewrite a name in uppercase
#     (e.g. SNT-PRJ012-GENAI). JMESPath contains() is case-sensitive and has no
#     lower() builtin in the jmespath lib azure-cli uses, so we filter in bash.
#   - The filter token requires the trailing dash ('prj012-') so prj012 cannot
#     accidentally match prj0120-* in a shared multi-project VNet.
#   - Project numbers are zero-padded to 3 digits (002, 009, 012, ...).
#
# Per project, the deletion order is:
#   Pass 1: Detach NSG / RouteTable / delegations / serviceEndpoints from subnets
#   Pass 2: Delete each subnet (SEQUENTIALLY - one write op per VNet at a time)
#   Step 3: Delete each NSG (with self-heal re-detach + retry)
#
# If PROJECTS_FROM == PROJECTS_TO (or PROJECTS_TO omitted) only that single
# project is processed.
#
# Usage:
#   ./delete-subnets-for-projects.sh \
#       --projects-from 002 --projects-to 009 \
#       --resource-group <vnet-rg> --vnet-name <vnet-name> \
#       [--subscription <sub-id>] [--skip-nsg] [--whatif]
#
# Example (single project 002):
#   ./delete-subnets-for-projects.sh --projects-from 002 \
#       --resource-group acme-aif-esml-common-weu-dev-001 \
#       --vnet-name vnt-esmlcmn-weu-dev-001 --whatif
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# Git Bash / MSYS on Windows rewrites any argument that looks like a POSIX path
# (e.g. an ARM resource ID starting with '/subscriptions/...') into a Windows
# path like 'C:/Program Files/Git/subscriptions/...', which breaks
# `az resource update --ids <id>`. The tested delete-services-if-disabled.sh
# never hits this because it runs on Linux (ADO). Disable the conversion so the
# resource IDs are passed through verbatim. Harmless on Linux/macOS.
# -----------------------------------------------------------------------------
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

# -----------------------------------------------------------------------------
# Parse arguments
# -----------------------------------------------------------------------------
PROJECTS_FROM=""
PROJECTS_TO=""
RESOURCE_GROUP=""
VNET_NAME=""
SUBSCRIPTION_ID=""
SKIP_NSG="false"
WHATIF="false"

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --projects-from)  PROJECTS_FROM="$2"; shift 2 ;;
    --projects-to)    PROJECTS_TO="$2";   shift 2 ;;
    --resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
    --vnet-name)      VNET_NAME="$2";     shift 2 ;;
    --subscription)   SUBSCRIPTION_ID="$2"; shift 2 ;;
    --skip-nsg)       SKIP_NSG="true";    shift 1 ;;
    --whatif)         WHATIF="true";      shift 1 ;;
    -h|--help)        usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

if [ -z "$PROJECTS_FROM" ] || [ -z "$RESOURCE_GROUP" ] || [ -z "$VNET_NAME" ]; then
  echo "ERROR: --projects-from, --resource-group and --vnet-name are required."
  usage
fi

# If projects-to omitted, operate on the single projects-from project only.
[ -z "$PROJECTS_TO" ] && PROJECTS_TO="$PROJECTS_FROM"

# Force base-10 so zero-padded values like 008/009 don't get parsed as octal.
FROM_INT=$((10#$PROJECTS_FROM))
TO_INT=$((10#$PROJECTS_TO))
if [ "$FROM_INT" -gt "$TO_INT" ]; then
  echo "ERROR: projects-from ($PROJECTS_FROM) must be <= projects-to ($PROJECTS_TO)."
  exit 1
fi

if [ -n "$SUBSCRIPTION_ID" ]; then
  echo "Setting subscription: $SUBSCRIPTION_ID"
  az account set --subscription "$SUBSCRIPTION_ID"
fi

echo "=== Delete Project Subnets + NSGs (range) ==="
echo "Resource group : $RESOURCE_GROUP"
echo "VNet           : $VNET_NAME"
if [ "$FROM_INT" -eq "$TO_INT" ]; then
  echo "Project        : $(printf '%03d' "$FROM_INT") (single)"
else
  echo "Project range  : $(printf '%03d' "$FROM_INT") .. $(printf '%03d' "$TO_INT")"
fi
echo "Delete NSGs    : $([ "$SKIP_NSG" = "true" ] && echo false || echo true)"
[ "$WHATIF" = "true" ] && echo "Mode           : WhatIf (no changes will be made)"
echo ""

# Running totals across the whole project range
deleted_subnets=0
failed_subnets=0
deleted_nsgs=0
failed_nsgs=0

# -----------------------------------------------------------------------------
# Helper: wait until the VNet is back at provisioningState=Succeeded before the
# next PATCH/DELETE. Azure serializes write operations on a single VNet -
# concurrent calls return "Bad Request". Polls up to ~2 minutes.
# (Ported verbatim from delete-services-if-disabled.sh _wait_vnet_idle.)
# -----------------------------------------------------------------------------
_wait_vnet_idle() {
  local _rg="$1" _vn="$2" _label="$3"
  local _max=24 _i=0 _state=""
  while [ "$_i" -lt "$_max" ]; do
    _state=$(az network vnet show -g "$_rg" -n "$_vn" --query "provisioningState" -o tsv 2>/dev/null || echo "")
    if [ "$_state" = "Succeeded" ] || [ -z "$_state" ]; then
      return 0
    fi
    sleep 5
    _i=$((_i + 1))
  done
  echo "    (waited $((_max * 5))s for vnet idle after $_label; last state=$_state - proceeding anyway)"
  return 0
}

# Verify the VNet exists
vnet_exists=$(az network vnet show -g "$RESOURCE_GROUP" -n "$VNET_NAME" --query "name" -o tsv 2>/dev/null || echo "")
if [ -z "$vnet_exists" ]; then
  echo "VNet '$VNET_NAME' not found in resource group '$RESOURCE_GROUP'. Nothing to do."
  exit 0
fi

# -----------------------------------------------------------------------------
# Detach + delete all subnets, then delete the NSGs, for ONE project token.
# -----------------------------------------------------------------------------
remove_project_networking() {
  local token="$1"

  echo "============================================================"
  echo "Project token : '$token' (case-insensitive substring)"
  echo "============================================================"

  # ---------------------------------------------------------------------------
  # Find matching project subnets. Filter in bash (grep -i), NOT in JMESPath,
  # because lower() is not a builtin in the jmespath lib azure-cli uses.
  # ---------------------------------------------------------------------------
  local subnets
  subnets=$(az network vnet subnet list \
    --resource-group "$RESOURCE_GROUP" \
    --vnet-name "$VNET_NAME" \
    --query "[].name" \
    -o tsv 2>/dev/null | tr -d '\r' | grep -i -- "$token" || true)

  if [ -z "$subnets" ]; then
    echo "  No project subnets matched token '$token' in VNet '$VNET_NAME'."
  else
    local match_count
    match_count=$(echo "$subnets" | sed '/^$/d' | wc -l | tr -d ' ')
    echo "  Matched $match_count project subnet(s) in VNet '$VNET_NAME':"
    echo "$subnets" | sed '/^$/d' | sed 's/^/    - /'
    echo ""

    # -------------------------------------------------------------------------
    # PASS 1: Detach NSG / RouteTable / delegations / serviceEndpoints.
    # -------------------------------------------------------------------------
    echo "  --- Pass 1/2: Detaching NSG / RouteTable / delegations from subnets ---"
    _wait_vnet_idle "$RESOURCE_GROUP" "$VNET_NAME" "pre-detach"

    while IFS= read -r subnet_name; do
      [ -z "$subnet_name" ] && continue
      echo "  Detaching from subnet: $VNET_NAME/$subnet_name"

      local cur_nsg cur_rt subnet_id
      cur_nsg=$(az network vnet subnet show -g "$RESOURCE_GROUP" --vnet-name "$VNET_NAME" -n "$subnet_name" --query "networkSecurityGroup.id" -o tsv 2>/dev/null | tr -d '\r' || echo "")
      cur_rt=$(az network vnet subnet show -g "$RESOURCE_GROUP" --vnet-name "$VNET_NAME" -n "$subnet_name" --query "routeTable.id" -o tsv 2>/dev/null | tr -d '\r' || echo "")
      if [ -n "$cur_nsg" ] && [ "$cur_nsg" != "None" ]; then echo "    Currently attached NSG : $cur_nsg"; else echo "    Currently attached NSG : (none)"; fi
      if [ -n "$cur_rt" ] && [ "$cur_rt" != "None" ]; then echo "    Currently attached RT  : $cur_rt"; fi

      subnet_id=$(az network vnet subnet show -g "$RESOURCE_GROUP" --vnet-name "$VNET_NAME" -n "$subnet_name" --query "id" -o tsv 2>/dev/null | tr -d '\r' || echo "")
      if [ -z "$subnet_id" ]; then
        echo "    (could not resolve subnet ARM id - skipping detach)"
        continue
      fi

      if [ "$WHATIF" = "true" ]; then
        echo "    [WhatIf] Would clear NSG / RouteTable / delegations / serviceEndpoints on $subnet_name"
        continue
      fi

      # -----------------------------------------------------------------------
      # WHY `az resource update --set properties.X=null`:
      #   The dedicated flags are bugged:
      #     --network-security-group "" / --route-table "" build an empty-named
      #       resource ID and 404 with InvalidResourceReference.
      #     --delegations "" / --service-endpoints "" create a single empty-named
      #       entry -> ServiceNameOnDelegationNotSpecified.
      #   `az resource update --set properties.X=null` goes through the same
      #   authenticated CLI path as the network commands and works reliably.
      # -----------------------------------------------------------------------
      local _detach_rc=0 _detach_out
      _detach_out=$(az resource update \
        --ids "$subnet_id" \
        --set properties.networkSecurityGroup=null \
              properties.routeTable=null \
              properties.delegations='[]' \
              properties.serviceEndpoints='[]' \
        2>&1) || _detach_rc=$?
      if [ "$_detach_rc" -ne 0 ]; then
        echo "    az resource update PATCH failed (exit=$_detach_rc) - retrying property-by-property..."
        echo "$_detach_out" | sed 's/^/      | /'
        local _prop _val _p_rc _p_out
        for _prop in networkSecurityGroup routeTable delegations serviceEndpoints; do
          _val="null"
          case "$_prop" in
            delegations|serviceEndpoints) _val='[]' ;;
          esac
          _wait_vnet_idle "$RESOURCE_GROUP" "$VNET_NAME" "pre-clear-$_prop"
          _p_rc=0
          _p_out=$(az resource update --ids "$subnet_id" --set "properties.${_prop}=${_val}" 2>&1) || _p_rc=$?
          if [ "$_p_rc" -ne 0 ]; then
            echo "    (could not clear $_prop on $subnet_name - exit=$_p_rc)"
          else
            echo "    Cleared $_prop on $subnet_name"
          fi
        done
      else
        echo "    PATCH accepted (NSG / RT / delegations / serviceEndpoints cleared)"
      fi
      _wait_vnet_idle "$RESOURCE_GROUP" "$VNET_NAME" "post-detach-patch"

      local remaining_nsg
      remaining_nsg=$(az network vnet subnet show -g "$RESOURCE_GROUP" --vnet-name "$VNET_NAME" -n "$subnet_name" --query "networkSecurityGroup.id" -o tsv 2>/dev/null | tr -d '\r' || echo "")
      if [ -n "$remaining_nsg" ] && [ "$remaining_nsg" != "None" ]; then
        echo "    NSG still attached to $subnet_name after PATCH: $remaining_nsg"
      else
        echo "    NSG cleared on $subnet_name (verified by GET)"
      fi
    done <<< "$subnets"

    # -------------------------------------------------------------------------
    # PASS 2: Delete subnets SEQUENTIALLY (one write op per VNet at a time).
    # Subnets with surviving Service Association Links cannot be removed; logged.
    # -------------------------------------------------------------------------
    echo ""
    echo "  --- Pass 2/2: Deleting subnets (sequential) ---"
    _wait_vnet_idle "$RESOURCE_GROUP" "$VNET_NAME" "pre-subnet-delete"

    while IFS= read -r subnet_name; do
      [ -z "$subnet_name" ] && continue
      if [ "$WHATIF" = "true" ]; then
        echo "  [WhatIf] Would delete subnet: $subnet_name from VNet: $VNET_NAME"
        continue
      fi

      echo "  Deleting subnet: $subnet_name from VNet: $VNET_NAME"
      if ! az network vnet subnet delete -g "$RESOURCE_GROUP" --vnet-name "$VNET_NAME" -n "$subnet_name" 2>&1; then
        echo "    Warning: Failed to delete subnet $subnet_name"
        echo "    Diagnosis - remaining references on $subnet_name:"
        az network vnet subnet show -g "$RESOURCE_GROUP" --vnet-name "$VNET_NAME" -n "$subnet_name" \
          --query "{pe:privateEndpoints, ipconfigs:ipConfigurations, sal:serviceAssociationLinks, deleg:delegations, nsg:networkSecurityGroup.id, rt:routeTable.id}" \
          -o json 2>/dev/null || true
        failed_subnets=$((failed_subnets + 1))
      else
        echo "    Subnet $subnet_name deleted"
        deleted_subnets=$((deleted_subnets + 1))
      fi
      # Wait for the VNet to settle before deleting the next subnet, otherwise
      # the next call hits a still-Updating VNet and returns "Bad Request".
      _wait_vnet_idle "$RESOURCE_GROUP" "$VNET_NAME" "delete-$subnet_name"
    done <<< "$subnets"
  fi

  # ---------------------------------------------------------------------------
  # STEP 3: Delete the project NSGs (case-insensitive match), same as Step 8 of
  # delete-services-if-disabled.sh. Pass 1 already detached the subnets, but a
  # silently-failed PATCH can leave an NSG bound -> the delete returns
  # InUseNetworkSecurityGroupCannotBeDeleted, so we self-heal first.
  # ---------------------------------------------------------------------------
  if [ "$SKIP_NSG" = "true" ]; then
    echo ""
    echo "  --- NSG deletion skipped (--skip-nsg) ---"
    return 0
  fi

  echo ""
  echo "  --- Step 3: Deleting Network Security Groups for token '$token' ---"
  local nsgs
  nsgs=$(az network nsg list --resource-group "$RESOURCE_GROUP" --query "[].name" -o tsv 2>/dev/null | tr -d '\r' | grep -i -- "$token" || true)

  if [ -z "$nsgs" ]; then
    echo "  No project NSGs matched token '$token'."
    return 0
  fi

  local nsg_match_count
  nsg_match_count=$(echo "$nsgs" | sed '/^$/d' | wc -l | tr -d ' ')
  echo "  Matched $nsg_match_count project NSG(s):"
  echo "$nsgs" | sed '/^$/d' | sed 's/^/    - /'

  while IFS= read -r nsg_name; do
    [ -z "$nsg_name" ] && continue
    if [ "$WHATIF" = "true" ]; then
      echo "  [WhatIf] Would delete NSG: $nsg_name"
      continue
    fi

    echo "  Deleting NSG: $nsg_name"

    # -------------------------------------------------------------------------
    # SELF-HEAL: re-detach any subnet still referencing this NSG, otherwise the
    # delete returns InUseNetworkSecurityGroupCannotBeDeleted.
    # -------------------------------------------------------------------------
    local still_attached
    still_attached=$(az network nsg show -g "$RESOURCE_GROUP" -n "$nsg_name" --query "subnets[].id" -o tsv 2>/dev/null | tr -d '\r' || echo "")
    if [ -n "$still_attached" ]; then
      echo "    Self-heal: $nsg_name still attached to subnets - detaching now"
      while IFS= read -r subnet_id; do
        [ -z "$subnet_id" ] && continue
        # subnet_id form: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}
        local s_rg s_vnet s_sub
        s_rg=$(echo "$subnet_id"   | awk -F/ '{print $5}')
        s_vnet=$(echo "$subnet_id" | awk -F/ '{print $9}')
        s_sub=$(echo "$subnet_id"  | awk -F/ '{print $11}')
        echo "      Detaching NSG from $s_rg / $s_vnet / $s_sub"
        _wait_vnet_idle "$s_rg" "$s_vnet" "pre-nsg-detach"
        if az resource update --ids "$subnet_id" --set properties.networkSecurityGroup=null >/dev/null 2>&1; then
          echo "      Detach PATCH accepted"
        else
          echo "      Detach PATCH failed"
        fi
        _wait_vnet_idle "$s_rg" "$s_vnet" "post-nsg-detach"
      done <<< "$still_attached"
    fi

    # -------------------------------------------------------------------------
    # Delete NSG with retry. "Bad Request" here is almost always a transient
    # race (parent VNet still Updating after the detach PATCH). Retry/backoff.
    # -------------------------------------------------------------------------
    local nsg_deleted=false attempt
    for attempt in 1 2 3 4; do
      if az network nsg delete -g "$RESOURCE_GROUP" -n "$nsg_name" 2>&1; then
        echo "    NSG $nsg_name deleted (attempt $attempt)"
        nsg_deleted=true
        break
      fi
      if ! az network nsg show -g "$RESOURCE_GROUP" -n "$nsg_name" >/dev/null 2>&1; then
        echo "    NSG $nsg_name no longer present (attempt $attempt)"
        nsg_deleted=true
        break
      fi
      echo "    Attempt $attempt failed for $nsg_name - backing off 20s and retrying"
      sleep 20
    done

    if [ "$nsg_deleted" = "true" ]; then
      deleted_nsgs=$((deleted_nsgs + 1))
    else
      echo "    Warning: Failed to delete NSG $nsg_name after retries"
      failed_nsgs=$((failed_nsgs + 1))
    fi
  done <<< "$nsgs"
}

# -----------------------------------------------------------------------------
# MAIN: loop over the project range, ONE project at a time.
# -----------------------------------------------------------------------------
for n in $(seq "$FROM_INT" "$TO_INT"); do
  token="prj$(printf '%03d' "$n")-"
  remove_project_networking "$token"
  echo ""
done

echo "=== Done ==="
if [ "$WHATIF" = "true" ]; then
  echo "WhatIf mode: no changes were made."
else
  echo "Subnets deleted: $deleted_subnets | Subnets failed/skipped: $failed_subnets"
  echo "NSGs deleted   : $deleted_nsgs | NSGs failed/skipped   : $failed_nsgs"
fi
