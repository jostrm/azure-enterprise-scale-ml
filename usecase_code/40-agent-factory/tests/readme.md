# Agent Factory regression and contract tests

These tests verify the code behind the examples, rather than representing
another deployed use case. They use synthetic inputs, fake Azure transports,
temporary files and optionally real SDKs with mocked HTTP responses.

## Use case summary

- Use case type: Not applicable; validation support for RAG with LLM and its deployment tools
- Data type: Tabular | Document (synthetic CSV/text/JSON test inputs)
- Number of source data sets: 0 external datasets read by the offline suite
- Data sources: No master-lake path; inline synthetic fixtures, temporary files and [fixtures](fixtures/readme.md)
- Inference type: Not applicable; Batch describes test execution only, not model inference
- Technology used in full chain: Python unittest | Mocked Azure Data Factory / Storage / AI Search / Microsoft Foundry APIs | Optional installed framework SDKs | Bicep CLI and PowerShell for infrastructure/pipeline contracts

## Prerequisites

Use Python 3.13, PowerShell and the parent operator's pinned requirements.
Ordinary tests use mocks/local files and do not need Azure login, a consumer
config, deployed agents or a VPN. Keep the full repository available for tests
that inspect infrastructure files outside this use-case tree; a consumer copy
also needs its purple submodule present.

Optional checks have additional prerequisites: existing PyYAML for YAML
contracts, `pwsh` for executing the local pipeline intent gate, and Azure CLI
with Bicep (or standalone Bicep) for local template compilation. Missing
optional tools can skip checks; skips are not evidence those contracts passed.

## How to set up the Python environment

From this `tests` folder, move to the parent. Create this environment once, or
reuse the one from [shared setup](../readme.md#how-to-set-up-the-python-environment).

```powershell
Set-Location ..
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

Use the explicit interpreter rather than installing packages globally or
activating an unrelated application/framework environment.

## How to run the code

Run from **`40-agent-factory`**, not from inside `tests`. Start with a focused
offline group; these examples use the existing `unittest` runner:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_core tests.test_cli tests.test_storage_selection -q
```

For a RAG-only change:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_rag_cli tests.test_rag_sources tests.test_rag_materialization tests.test_rag_indexing -q
```

To run all root-suite tests, including infrastructure/pipeline contracts:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expected output is a `unittest` summary (`OK`, possibly with explicitly listed
skips) and exit code zero. Failures/errors are not successful deployment
validation. The separate `40-aifactory-agent\tests` suite is not included in this
root discovery command; it belongs to that application's own environment.

### Optional hosted SDK contracts

Normal `tests.test_hosted` checks packaging/orchestration with fakes. Its optional
real-SDK payload cases use `AIFACTORY_VALIDATE_SDKS=1` and require all SDKs
imported by those cases in a separately prepared, compatible validation
environment. The root operator requirements alone are insufficient; do not
merge every framework's runtime pins into the operator environment. Review the
imports in `test_hosted.py` and the
[runtime manifests](../41-single-agent/hosted-agent/readme.md) before enabling
these maintainer checks.

With that existing validation environment selected explicitly:

```powershell
$SdkPython = "C:\path\to\agent-factory-sdk-validation-venv\Scripts\python.exe"
$PreviousSdkValidation = $env:AIFACTORY_VALIDATE_SDKS
try {
    $env:AIFACTORY_VALIDATE_SDKS = "1"
    & $SdkPython -m unittest tests.test_hosted -q
}
finally {
    $env:AIFACTORY_VALIDATE_SDKS = $PreviousSdkValidation
}
```

These use installed SDKs with mocked HTTP, not live agent requests. Infrastructure
tests compile Bicep locally when tooling is available; they do not deploy it.
Pipeline tests exercise local validation scripts, not actual cloud pipelines.

Passing these tests does not establish live Azure permissions, connectivity,
agent availability or answer-quality consistency. Those require separately
scoped live calls. Production dataset and lake-path context is documented in
[43-data](../43-data/readme.md), not inferred from fixture names.
