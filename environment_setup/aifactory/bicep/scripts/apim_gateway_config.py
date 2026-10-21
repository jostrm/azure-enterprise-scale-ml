"""Strict, offline consumer configuration for the AI Factory APIM runner."""

import copy
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


class GatewayError(Exception):
    """Only controlled messages, never CLI output or consumer values."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise GatewayError(code, message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def json_document(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "config-invalid", "Duplicate JSON keys are not allowed.")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=pairs)
    except (ValueError, TypeError):
        raise GatewayError("config-invalid", "Expected a valid JSON document.") from None


GUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}"
RESOURCE_NAME = r"[A-Za-z0-9][A-Za-z0-9_.()-]{0,89}"
SKUS = {"Developer", "Basic", "Standard", "Premium", "BasicV2", "StandardV2", "PremiumV2"}
RID_TYPES = {
    "subnet": r"Microsoft\.Network/virtualNetworks/" + RESOURCE_NAME + r"/subnets/" + RESOURCE_NAME,
    "nsg": r"Microsoft\.Network/networkSecurityGroups/" + RESOURCE_NAME,
    "route": r"Microsoft\.Network/routeTables/" + RESOURCE_NAME,
    "zone": r"Microsoft\.Network/privateDnsZones/privatelink\.azure-api\.net",
    "backend": r"Microsoft\.CognitiveServices/accounts/[A-Za-z0-9][A-Za-z0-9-]{1,62}",
}
TOP_KEYS = {
    "schemaVersion", "environment", "tenantId", "subscriptionId", "resourceGroup", "location",
    "serviceName", "serviceMode", "sku", "skuCapacity", "publisherName", "publisherEmail",
    "ownershipId", "tags", "network", "api",
}
NETWORK_KEYS = {
    "integrationSubnetId", "createIntegrationSubnet", "integrationSubnetPrefix",
    "networkSecurityGroupId", "routeTableId", "privateEndpointSubnetId", "privateEndpointName",
    "privateDnsMode", "privateDnsZoneId",
}
API_KEYS = {
    "apiId", "apiPath", "backendPoolName", "aggregateTokensPerMinute", "callerTokensPerMinute",
    "retryCount", "assignOpenAIUserRole", "managedIdentityPrincipalId", "azureOpenAIBackends",
}


def keys(value, allowed, required=()):
    require(isinstance(value, dict), "config-invalid", "Expected a configuration object.")
    require(set(value) <= allowed, "config-invalid", "Unknown configuration field; check schema spelling.")
    require(set(required) <= set(value), "config-invalid", "A required configuration field is missing.")


def text(value, pattern, label):
    require(isinstance(value, str) and re.fullmatch(pattern, value, re.ASCII) is not None,
            "config-invalid", f"Invalid {label}; use the documented controlled format.")
    require(value not in {".", ".."} and not value.endswith("."), "config-invalid",
            f"Invalid {label}; trailing dots are not allowed.")
    return value


def guid(value, label):
    value = text(value, GUID, label).lower()
    require(value != "00000000-0000-0000-0000-000000000000", "config-invalid",
            f"{label} cannot be the zero GUID.")
    return value


def integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, "config-invalid",
            f"{label} must be an integer in the documented range.")
    return value


def boolean(value, label):
    require(type(value) is bool, "config-invalid", f"{label} must be a JSON boolean.")
    return value


def resource_id(value, kind):
    pattern = r"/subscriptions/" + GUID + r"/resourceGroups/" + RESOURCE_NAME + r"/providers/" + RID_TYPES[kind]
    require(isinstance(value, str) and re.fullmatch(pattern, value, re.IGNORECASE | re.ASCII),
            "config-invalid", f"Invalid {kind} resource ID; use an exact Azure resource ID without URL data.")
    require(all(part not in {".", ".."} and not part.endswith(".") for part in value.split("/") if part),
            "config-invalid", "Resource ID path segments cannot contain traversal or trailing dots.")
    guid(value.split("/")[2], "resource subscription")
    return value


def ipv4_prefix(value, integration=False):
    try:
        prefix = ipaddress.ip_network(value, strict=True)
    except (TypeError, ValueError):
        raise GatewayError("network-invalid", "Subnet prefix must be a canonical IPv4 CIDR.") from None
    require(prefix.version == 4 and (not integration or prefix.prefixlen <= 27), "network-invalid",
            "Integration subnet must be IPv4 /27 or larger; IPv6 is not supported by this runner.")
    return prefix


def same_id(left, right):
    return isinstance(left, str) and isinstance(right, str) and left.lower() == right.lower()


def endpoint(value):
    require(isinstance(value, str), "config-invalid", "Backend endpoint must be an HTTPS Azure OpenAI URL.")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname
                 and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}\.openai\.azure\.com", parsed.hostname)
                 and parsed.netloc == parsed.hostname and parsed.path in {"", "/"}
                 and not parsed.query and not parsed.fragment and value.isascii()
                 and not re.search(r"[\s\x00-\x1f\x7f]", value))
    except ValueError:
        valid = False
    require(valid, "config-invalid", "Backend endpoint must be a public-cloud Azure OpenAI HTTPS origin without credentials or URL data.")
    return "https://" + parsed.hostname


def validate_config(data, environment, expected=None):
    expected = expected or {}
    keys(data, TOP_KEYS, {"schemaVersion", "environment", "tenantId", "subscriptionId",
                        "resourceGroup", "location", "serviceName", "api"})
    c = copy.deepcopy(data)
    require(type(c["schemaVersion"]) is int and c["schemaVersion"] == 1, "config-invalid", "schemaVersion must be 1.")
    require(environment in {"dev", "stage", "prod"} and c["environment"] == environment,
            "target-mismatch", "The selected environment must exactly match the configuration.")
    for key, env in (("tenantId", "AZURE_TENANT_ID"), ("subscriptionId", "AZURE_SUBSCRIPTION_ID")):
        c[key] = guid(c[key], key)
        if expected.get(env):
            require(c[key] == guid(expected[env], env), "target-mismatch",
                    "Pipeline tenant/subscription and consumer target differ; cross-target fallback is forbidden.")
    text(c["resourceGroup"], RESOURCE_NAME, "resourceGroup")
    text(c["serviceName"], r"[A-Za-z][A-Za-z0-9-]{0,48}[A-Za-z0-9]", "serviceName")
    text(c["location"], r"[a-z][a-z0-9]{1,39}", "location")
    c.setdefault("serviceMode", "existing")
    require(isinstance(c["serviceMode"], str) and c["serviceMode"] in {"existing", "managed"},
            "config-invalid", "serviceMode must be existing or managed.")
    c.setdefault("sku", "StandardV2")
    require(isinstance(c["sku"], str) and c["sku"] in SKUS, "config-invalid", "Unsupported APIM SKU.")
    integer(c.setdefault("skuCapacity", 1), 1, 1000, "skuCapacity")
    if c["sku"] == "StandardV2":
        integer(c["skuCapacity"], 1, 10, "StandardV2 skuCapacity")
    tags = c.setdefault("tags", {})
    require(isinstance(tags, dict) and len(tags) <= 49, "config-invalid", "tags must be an object with at most 49 entries.")
    for key, value in tags.items():
        text(key, r"[A-Za-z0-9][A-Za-z0-9_. -]{0,127}", "tag name")
        text(value, r"[A-Za-z0-9_. @()+/-]{0,256}", "tag value")
        require(key.lower() != "aifactory-gateway-owner", "config-invalid", "The ownership tag is controlled by ownershipId.")
    if c["serviceMode"] == "managed":
        require(c["sku"] == "StandardV2", "config-invalid", "Managed provisioning supports StandardV2 only.")
        require(all(key in c for key in ("publisherName", "publisherEmail", "ownershipId", "network")),
                "config-invalid", "Managed services require publisherName, publisherEmail, ownershipId and network.")
    if "publisherName" in c:
        text(c["publisherName"], r"[A-Za-z0-9][A-Za-z0-9 ._()-]{0,99}", "publisherName")
    if "publisherEmail" in c:
        text(c["publisherEmail"], r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", "publisherEmail")
    if "ownershipId" in c:
        text(c["ownershipId"], r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", "ownershipId")
    if "network" in c:
        n = c["network"]
        keys(n, NETWORK_KEYS, {"integrationSubnetId", "networkSecurityGroupId",
                              "privateEndpointSubnetId", "privateEndpointName"})
        for key, kind in (("integrationSubnetId", "subnet"), ("privateEndpointSubnetId", "subnet"),
                          ("networkSecurityGroupId", "nsg"), ("routeTableId", "route"), ("privateDnsZoneId", "zone")):
            if key in n:
                resource_id(n[key], kind)
                require(same_id(n[key].split("/")[2], c["subscriptionId"]), "target-mismatch",
                        "All managed network resources must be in the selected subscription.")
        boolean(n.setdefault("createIntegrationSubnet", False), "createIntegrationSubnet")
        require(c["serviceMode"] == "managed" or not n["createIntegrationSubnet"], "config-invalid",
                "Existing mode cannot create or change service networking.")
        if n["createIntegrationSubnet"]:
            require("integrationSubnetPrefix" in n, "config-invalid", "Creating a subnet requires integrationSubnetPrefix.")
        if "integrationSubnetPrefix" in n:
            ipv4_prefix(n["integrationSubnetPrefix"], integration=True)
        require(not same_id(n["integrationSubnetId"], n["privateEndpointSubnetId"]), "network-invalid",
                "Integration and private endpoints require separate subnets.")
        require(same_id(re.split("/subnets/", n["integrationSubnetId"], flags=re.I)[0],
                        re.split("/subnets/", n["privateEndpointSubnetId"], flags=re.I)[0]),
                "network-invalid", "Integration and private endpoint subnets must use the same existing VNet.")
        text(n["privateEndpointName"], NAME, "privateEndpointName")
        n.setdefault("privateDnsMode", "policy")
        require(isinstance(n["privateDnsMode"], str) and n["privateDnsMode"] in {"policy", "existingZone"},
                "config-invalid", "Invalid privateDnsMode.")
        require(("privateDnsZoneId" in n) == (n["privateDnsMode"] == "existingZone"), "config-invalid",
                "privateDnsZoneId is required only for existingZone; policy mode never writes a zone group.")
    a = c["api"]
    keys(a, API_KEYS, {"apiId", "apiPath", "backendPoolName", "aggregateTokensPerMinute", "azureOpenAIBackends"})
    for key in ("apiId", "backendPoolName"):
        text(a[key], NAME, key)
    text(a["apiPath"], r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,79})*", "apiPath")
    integer(a["aggregateTokensPerMinute"], 1, 2147483647, "aggregateTokensPerMinute")
    integer(a.setdefault("callerTokensPerMinute", 10000), 1, 2147483647, "callerTokensPerMinute")
    integer(a.setdefault("retryCount", 2), 1, 50, "retryCount")
    boolean(a.setdefault("assignOpenAIUserRole", False), "assignOpenAIUserRole")
    if "managedIdentityPrincipalId" in a:
        a["managedIdentityPrincipalId"] = guid(a["managedIdentityPrincipalId"], "managedIdentityPrincipalId")
    backends = a["azureOpenAIBackends"]
    require(isinstance(backends, list) and 1 <= len(backends) <= 30, "config-invalid", "Provide between 1 and 30 backends.")
    names, ids = set(), set()
    for b in backends:
        keys(b, {"name", "endpoint", "resourceId", "weight", "priority"}, {"name", "endpoint", "resourceId", "weight"})
        text(b["name"], NAME, "backend name")
        b["endpoint"] = endpoint(b["endpoint"])
        resource_id(b["resourceId"], "backend")
        integer(b["weight"], 1, 1000, "backend weight")
        integer(b.setdefault("priority", 1), 1, 100, "backend priority")
        require(b["name"].lower() not in names and b["resourceId"].lower() not in ids,
                "config-invalid", "Backend names and resource IDs must be unique.")
        require(b["name"].lower() != a["backendPoolName"].lower(), "config-invalid", "Backend name cannot equal pool name.")
        names.add(b["name"].lower())
        ids.add(b["resourceId"].lower())
    return c


def legacy_config(environment, env):
    require(env.get("ENABLE_APIM", "").lower() == "true", "config-invalid",
            "Without --config, ENABLE_APIM=true and the legacy APIM_GATEWAY variables are required.")

    def number(name, default=None):
        value = env.get(name, str(default) if default is not None else "")
        require(bool(re.fullmatch(r"[0-9]+", value)), "config-invalid", "A legacy numeric APIM_GATEWAY variable is missing or invalid.")
        return int(value)

    def flag(name, default="false"):
        value = env.get(name, default).lower()
        require(value in {"true", "false"}, "config-invalid", "Legacy APIM_GATEWAY booleans must be true or false.")
        return value == "true"

    api = {
        "apiId": env.get("APIM_GATEWAY_API_ID", "azure-openai-gpt55"),
        "apiPath": env.get("APIM_GATEWAY_API_PATH", "openai"),
        "backendPoolName": env.get("APIM_GATEWAY_BACKEND_POOL_NAME", "aoai-gpt55-pool"),
        "aggregateTokensPerMinute": number("APIM_GATEWAY_AGGREGATE_TPM"),
        "callerTokensPerMinute": number("APIM_GATEWAY_CALLER_TPM", 10000),
        "retryCount": number("APIM_GATEWAY_RETRY_COUNT", 2),
        "assignOpenAIUserRole": flag("APIM_GATEWAY_ASSIGN_OPENAI_USER_ROLE"),
        "azureOpenAIBackends": json_document(env.get("APIM_GATEWAY_BACKENDS_JSON", "[]")),
    }
    if env.get("APIM_GATEWAY_MANAGED_IDENTITY_PRINCIPAL_ID"):
        api["managedIdentityPrincipalId"] = env["APIM_GATEWAY_MANAGED_IDENTITY_PRINCIPAL_ID"]
    return {
        "schemaVersion": 1, "environment": environment,
        "tenantId": env.get("AZURE_TENANT_ID", ""),
        "subscriptionId": env.get("APIM_GATEWAY_SUBSCRIPTION_ID") or env.get("AZURE_SUBSCRIPTION_ID", ""),
        "resourceGroup": env.get("APIM_GATEWAY_RESOURCE_GROUP", ""),
        "location": env.get("AZURE_LOCATION", ""),
        "serviceName": env.get("APIM_GATEWAY_SERVICE_NAME", ""),
        "serviceMode": "existing", "sku": env.get("APIM_GATEWAY_SKU", "StandardV2"),
        "skuCapacity": number("APIM_GATEWAY_SKU_CAPACITY", 1),
        "tags": json_document(env.get("APIM_GATEWAY_TAGS_JSON", "{}")), "api": api,
    }


def load_config(path, environment, env):
    if path:
        try:
            require(Path(path).stat().st_size <= 1024 * 1024, "config-invalid", "Configuration exceeds the 1 MiB limit.")
            value = json_document(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError):
            raise GatewayError("config-invalid", "Cannot read the consumer configuration.") from None
    else:
        value = legacy_config(environment, env)
    c = validate_config(value, environment, env)
    # The MCP and Kong pipeline steps locate the APIM through the apimGateway* variables.
    for key, name in (("subscriptionId", "APIM_GATEWAY_SUBSCRIPTION_ID"), ("resourceGroup", "APIM_GATEWAY_RESOURCE_GROUP"),
                      ("serviceName", "APIM_GATEWAY_SERVICE_NAME")):
        require(not env.get(name) or same_id(env[name], c[key]), "target-mismatch",
                "The apimGateway* variables name a different APIM than the configuration file; align them or leave them empty.")
    return c
