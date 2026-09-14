# Contributing

This project welcomes contributions and suggestions. Most contributions require you to
agree to a Contributor License Agreement (CLA) declaring that you have the right to,
and actually do, grant us the rights to use your contribution. For details, visit
https://cla.microsoft.com.

When you submit a pull request, a CLA-bot will automatically determine whether you need
to provide a CLA and decorate the PR appropriately (e.g., label, comment). Simply follow the
instructions provided by the bot. You will only need to do this once across all repositories using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/)
or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Infrastructure regression checks

Before changing Bicep, ADO/GHA templates or bootstrap configuration, run the
[AI Factory IaC test suite](environment_setup/unit-tests/test-bicep/README.md).
It provides credential-free unit, syntax, pipeline-contract and real Bicep
parameter-matrix checks, plus setup instructions for automatic push/PR checks.
No Azure deployment is performed by the default suite. Live integration tests
are separate and require explicit opt-in.

The [interactive VisualLearner guide](environment_setup/unit-tests/test-bicep/docs/ci-visual-guide.html)
and [static flow diagram](environment_setup/unit-tests/test-bicep/docs/ci-flow.svg)
explain the test stages, flag-pair matrix and CI activation steps.