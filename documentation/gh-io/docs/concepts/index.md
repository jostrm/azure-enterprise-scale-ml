# AI Factory Concepts

The Enterprise Scale AI Factory is built around four foundational concepts that together deliver an enterprise-grade, scalable, and secure AI platform.

---

## The Four Pillars

| Concept | Description |
|---|---|
| [AI Factory Intelligence](intelligence.md) | Built-in automation, dynamic networking, RBAC, and persona-based access control |
| [Enterprise Grade & Scale](enterprise-scale.md) | WAF-aligned, private networking, multi-environment (Dev/Stage/Prod), scale sets for 200–300 projects |
| [Templates — IaC](templates/iac.md) | Bicep-based Infrastructure-as-Code for repeatable, auditable deployments |
| [Templates — DataOps / MLOps / GenAIOps](templates/dataops.md) | Project templates for data, ML, and GenAI workloads |

---

## Design Philosophy

- **Project-based isolation**: Each team/use-case gets its own floor with isolated networking, RBAC, and data access.
- **Feature flags**: Services are toggled on/off — deploy a minimal baseline first, add services incrementally as your project evolves.
- **Bring Your Own**: Supports BYO vNet, BYO subnets, BYO Terraform, and BYO existing services.
- **Dual orchestrator**: Works identically with **GitHub Actions** or **Azure DevOps Pipelines**.
