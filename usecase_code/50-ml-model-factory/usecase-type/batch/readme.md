# batch

**Purpose:** Run scheduled or on-demand bulk inference and save predictions to storage.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates exist for 42 of 42 leaf combinations below; each leaf README lists its route, prerequisites and limitations.

[Scenario configuration](../../user-config/model/scenarios/readme.md) | [Shared execution code](../../accelerator/readme.md) | [Start here](../../readme.md)

## References and examples

## Serving behavior

Batch jobs process multiple records/files and write predictions to storage. Reviewed compute can scale from zero and return to zero; storage/networking charges can still apply.
