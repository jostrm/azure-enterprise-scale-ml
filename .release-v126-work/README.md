# Working state of the release/v1.26 run

Scratch tooling and base-commit measurements of the cloud chat that builds `release/v1.26`
(base `ebd300db`). Nothing here is part of the product. This session branch is deleted when the
run is finished.

- `tools/`: clean CI-like environment wrapper (`cienv.sh`), main-suite and component-suite runners,
  static workflow metrics (`wf_metrics.py`), Bicep build metrics and ARM comparison (`bicep_metrics.py`),
  and the proof scripts for the compaction (`proof_c.py`, `proof_e.sh`, `junit_compare.py`).
- `baseline/`: results on the base commit (JUnit files, workflow metrics, Bicep entry metrics,
  the classified wait inventory).

The tools expect `/home/user/tools`, `/home/user/venvs` and `/home/user/results` in the cloud sandbox.
