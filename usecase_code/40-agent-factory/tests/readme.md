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

Run from `40-agent-factory`:

```powershell
python -m unittest discover -s tests
```

The optional hosted SDK contract tests use `AIFACTORY_VALIDATE_SDKS=1` and
require the runtime dependencies in an isolated environment. Infrastructure
tests compile Bicep locally when tooling is available; they do not deploy it.
Pipeline tests exercise local validation scripts, not actual cloud pipelines.

Passing these tests does not establish live Azure permissions, connectivity,
agent availability or answer-quality consistency. Those require separately
scoped live calls. Production dataset and lake-path context is documented in
[43-data](../43-data/readme.md), not inferred from fixture names.
