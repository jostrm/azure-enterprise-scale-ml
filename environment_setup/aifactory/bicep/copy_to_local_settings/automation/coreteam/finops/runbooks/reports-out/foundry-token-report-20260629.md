# Automation for the AI Factory

## Reports: Foundry models and token
Model: GPT 5.1 - RG `gh-esml-project004-sdc-dev-001-rg` - window 30d - generated 2026-06-29 16:51

### 2) Current workload telemetry (from logs)

| Workload - telemetry | Value | Unit |
|---|---|---|
| Total users with access | 50000 | users |
| INPUT tokens per minute | 0 | TPM |
| OUTPUT tokens per minute | 0 | TPM |
| REQUESTS per minute | 0 | RPM |
| Total tokens (window) | 0 | tokens |
| EA Discount | 29% | |
| Cache rate | 35% | |
| Input rate (\$/1M) | 0.27 | |
| Cached rate (\$/1M) | 0.099 | |
| Output rate (\$/1M) | 7.81 | |

### 3) Derived workload information

| Derived | Value | Unit |
|---|---|---|
| Average TPM | 0 | TPM |
| Requests per day | 0 | req/day |
| Monthly tokens (30d) | 0 | tokens |
| Est. monthly PAYGO cost | 0 | USD |

# Recommendations

## Based on PAYGO usage, is PTU an option

| GPT 5.1 PTU Recommendation | Value | Note |
|---|---|---|
| PTUs (avg, ~35% cache) | 0 | 4750 input TPM/PTU |
| -> resulting TPM | 0 | normalized |
| PTU to handle spikes | False | else spillover PAYGO |
| AI Gateway loadbalancer | True | |

