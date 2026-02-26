# Enterprise Grade & Scale

The AI Factory is designed for production enterprise workloads from day one — not retrofitted.

---

## WAF Alignment

Every architectural decision follows [Microsoft's Well-Architected Framework (WAF)](https://learn.microsoft.com/en-us/azure/well-architected/ai/personas):

| WAF Pillar | AI Factory Implementation |
|---|---|
| **Reliability** | Multi-environment isolation (Dev / Stage / Prod), retry settings, diagnostics |
| **Security** | Private endpoints on all services, CMK support, Entra ID RBAC, Defender for AI |
| **Cost Optimization** | Feature flags reduce cost in lower environments; shared ACR option |
| **Operational Excellence** | Full IaC (Bicep), pipeline orchestration (ADO/GHA), diagnostic setting levels |
| **Performance Efficiency** | AKS auto-scaling, AML cluster scaling, configurable SKUs per environment |

---

## Scale Sets

The AI Factory uses a **scale set** concept to support organisations with many teams:

- Each scale set suffix (e.g. `-001`) represents one deployment of the common infrastructure.
- Within a scale set, up to **200–300 AI Factory projects** can be created, each isolated by project number (`project_number_000`).
- Multiple scale sets can be deployed for larger organisations.

---

## Multi-environment Architecture

Environments are deployed to separate Azure subscriptions (recommended) and share no network by default:

```
┌─────────────────────────────────────────────────────┐
│  Subscription: DEV                                  │
│  ┌─────────────────────────────────────────────┐   │
│  │  AI Factory Common (vNet, shared services)  │   │
│  │  ┌──────────────┐  ┌──────────────┐         │   │
│  │  │  Project 001 │  │  Project 002 │  ...     │   │
│  │  └──────────────┘  └──────────────┘         │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  Subscription: STAGE                                │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  Subscription: PROD                                 │
└─────────────────────────────────────────────────────┘
```

---

## Landing Zone Options

| Mode | When to use |
|---|---|
| **Traditional Hub/Spoke** | Standard enterprise networking with a central hub VNet |
| **VWAN Hub** | Azure Virtual WAN for global connectivity |
| **Standalone** | Fully self-contained with its own VNet — ideal for PoC |
| **Hybrid (public + private)** | Public access via VPN / IP whitelist / Bastion alongside private endpoints |
