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

## Prerequisites

Python 3.13 and PowerShell are sufficient for the focused monitoring contract
test. No Azure account, sign-in, VPN, model deployment or external dataset is
needed. This JSON file is **test data**, not an executable, a consumer config,
or an input in the monitoring exporter's `knowledge` result format.

## How to set up the Python environment

From this `tests\fixtures` folder, move up to `40-agent-factory`. Reuse the
parent environment if it exists; otherwise create it:

```powershell
Set-Location ..\..
py -3.13 -m venv .venv
```

The focused test below uses the standard library. For the rest of the suite,
install the root `requirements.txt` as described in
[test setup](../readme.md#how-to-set-up-the-python-environment).

## How to run the code

From **`40-agent-factory`**, run the test that generates a report from synthetic
inputs and compares it with this checked-in golden fixture:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_monitoring.py
```

Expect the `unittest` summary to report `OK`. The test reads
`tests\fixtures\monitoring-agent-v1.json`; it does not upload it, query Azure,
overwrite the fixture or claim its values are live telemetry. Do not feed the
finished report back as a raw `knowledge` result to `monitoring-export`.

See [test execution](../readme.md) and the
[exporter usage](../../readme.md#offline-monitoring-ml-reports) for actual
recorded-result inputs.
