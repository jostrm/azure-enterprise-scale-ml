# Kong Edge Gateway for AI Factory

Kong Gateway OSS is an optional private edge proxy for the APIM Azure OpenAI pool. It authenticates callers with a Kong key, forwards the caller's `Ocp-Apim-Subscription-Key` to APIM, and preserves the request path, including `/openai/...`.

```text
client -- x-api-key + Ocp-Apim-Subscription-Key --> Kong (private ACI)
       -- Ocp-Apim-Subscription-Key -------------> APIM
       -- managed identity -----------------------> weighted Azure OpenAI pool
```

APIM is deliberately the only Azure OpenAI traffic controller. It applies aggregate and per-caller token limits, selects weighted backends, honors Azure OpenAI `Retry-After`, and opens a per-backend circuit on a `429`.

## Why Kong does not directly load-balance Azure OpenAI

The old content in this folder was an unfinished proof of concept, not a safe deployable gateway. It contained one hard-coded Azure OpenAI endpoint, required a shared Azure OpenAI API key, referenced pipeline files that did not exist, and only limited requests—not tokens.

Kong OSS provides weighted round-robin and can mark a target unhealthy after a `429`, but it does not provide Azure OpenAI token accounting or a `Retry-After`-aware cooldown. Direct multi-subscription routing would also require secure per-backend Azure OpenAI authentication. Routing Kong to APIM retains the complete, supported implementation instead of creating two conflicting quota controllers.

## Deployment

Use either of the opt-in gateway workflows:

| System | Workflow |
|---|---|
| Azure DevOps | `copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-common/infra-ai-gateway.yaml` |
| GitHub Actions | `copy_to_local_settings/github-actions/infra-ai-gateway.yml` |

Set `ENABLE_APIM` to deploy APIM. Set `ENABLE_KONG` only when a private Kong entry point is also required. Kong requires the `kongConsumerApiKey` Azure DevOps secret variable or the `KONG_CONSUMER_API_KEY` GitHub Environment secret.

The workflow deploys Kong, uploads `kong.yaml` to its Azure File Share, then restarts the container to load the declarative configuration. The Kong Admin API only listens on the container loopback interface and is not exposed on the ACI private IP.

## Required client headers

```text
x-api-key: <Kong consumer key>
Ocp-Apim-Subscription-Key: <APIM subscription key>
Content-Type: application/json
```

The consumer key is hidden before forwarding. The APIM subscription key remains intact so APIM can enforce a distinct caller TPM allocation.
