# Synthetic monitoring report fixture

`monitoring-agent-v1.json` is an example of the
`aifactory.monitoring/v1` report contract. Its factory/agent identifiers, dates,
document count and reference count are test values, not measurements from a
running deployment or another RAG corpus.

## Use case summary

- Use case type: Not applicable; an offline report-contract fixture for RAG with LLM tooling
- Data type: Tabular (structured aggregate metrics serialized as JSON)
- Number of source data sets: 0; this fixture is not a training or retrieval dataset
- Data sources: No master-lake path; local `monitoring-agent-v1.json`
- Inference type: Not applicable; no inference or Azure calls
- Technology used in full chain: Python unittest | Local JSON | Agent Factory monitoring exporter

In particular, the fixture's `document_count=19` must not be reported as the
ten-item helpdesk corpus size. Its `healthy` status reflects supplied fixture
checks only. Data drift and concept drift remain `not_supported`.

See [test execution](../readme.md) and
[the exporter](../../agent_factory/monitoring.py).
