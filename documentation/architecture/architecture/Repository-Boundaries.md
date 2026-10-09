---
id: repository-boundaries
status: observed
sources:
  - 00-start.sh
  - 01-start-v125-and-above.sh
  - bootstrap/01-aif-copy-aifactory-templates.sh
  - esmlfac/adapter.py
  - esml-v2/esml_build.py
  - documentation/v2/30-39/37-mlops.md
  - usecase_code/50-ml-model-factory/readme.md
  - usecase_code/20-agent-foundry/_legacy/README.md
tests:
  - esml-v2/tests/test_esml_packaging.py
  - usecase_code/50-ml-model-factory/accelerator/tests/test_layout.py
graph_symbols:
  - esmlfac/adapter.py::class:ESMLFactory
  - esml-v2/esml_build.py::function:_source
reviewed_source: '3e9102ee + working tree; observed 2026-10-07'
---
# Repository boundaries

| Boundary | Evidence-backed interpretation |
|---|---|
| `bootstrap`, root launchers | Maintained launch/control adapters, copying, enrollment, runner and registered lifecycle helpers. Running them is not a documentation operation. |
| `environment_setup/aifactory` | Maintained canonical configuration, Bicep, provider pipeline templates and infrastructure scripts. `copy_to_local_settings` is template source, not an installed consumer instance. |
| `copy_my_subfolders_to_my_grandparent` | Maintained distributable DataOps/MLOps/GenAIOps, settings and notebook templates; copied destinations become consumer-owned. Not merely disposable generated output. |
| `esml`, `esmlfac`, `esmlrt` | Retained SDK-v1-era implementation and contracts. `ESMLFactory` imports controllers/comparison/scoring from `esmlrt`; these are real code, not empty folders, but not the new v2 API. |
| `esml-v2` | Maintained `azure-esml-sdk` / `azure_esml` pipeline factory. Bundles canonical model-factory engines when building, not a second maintained implementation. |
| `healthmodel`, `mcp` | Active working source for health modeling and repository MCP. Unpublished code is not installed-service evidence. |
| `usecase_code/40-agent-factory` | Shared operator plus separately configured runtime/examples; `40-aifactory-agent` is the current grounded Factory application reviewed here. |
| `usecase_code/50-ml-model-factory/accelerator` | Maintainer-owned engines, scripts, schemas and tests in the **current relocated layout**. Former root `src` and `tests` paths must not be cited as current. |
| Model-factory `user-config`, project copies | User-editable scenarios, storage and backend choices; examples are not customer authorization. |
| `data/out`, `ml-environment`, `dist`, caches, run outputs | Generated/local runtime artifacts, not architecture authority or retrieval corpus. No customer data copied here. |
| `documentation/v1`, `esml/z`, explicit `_legacy` examples | Historical context; check current entry points before using instructions. `documentation/v2` is not uniformly current merely because of its name. |

The old `30-machine-learning/README.md` is an empty coverage gap; do not infer a maintained engine from its directory name. Parallel/versioned example folders likewise require a traced entry point before being declared active replacements.

“Purple” means shared accelerator source; “orange” means customer/consumer configuration and project copies. A source checkout, a copied consumer template and an installed wheel are different revisions unless explicitly verified.

See [[Bootstrap-and-Layouts]], [[Engines-and-Pipelines]], [[Packaging-and-Release]], [[Evidence-and-Gaps]], [[System-Context]] and [[Index]].

Authority: [current ML layout](../../../usecase_code/50-ml-model-factory/readme.md), [v2 and legacy compatibility](../../v2/30-39/37-mlops.md).
