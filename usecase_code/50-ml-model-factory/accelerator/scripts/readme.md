# scripts

**Purpose:** Expose command entry points and pipeline preparation/evaluation/monitoring wrappers.

**Owner:** Maintainer-owned execution code.

**Edit/run guidance:** Users run these scripts with configuration arguments; they do not normally modify them.

**Status:** Maintained scaffold; local/cloud execution is explicit, never automatic.

`online_score.py` is the Azure ML custom-code scoring entry point (`init`/`run`) bundled by
`serving-render`; it delegates to the same `OnlineService` that `online-test` runs locally.

[Model-factory guide](../../readme.md)
