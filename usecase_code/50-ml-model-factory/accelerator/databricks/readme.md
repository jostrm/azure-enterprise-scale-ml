# databricks

**Purpose:** Shared Databricks notebook sources for training, batch scoring, streaming scoring and online Model Serving.

**Owner:** Maintainer-owned backend code.

**Edit/run guidance:** Pass project settings/widgets from `user-config/databricks`; do not hardcode customer clusters, data references or secrets here. All notebooks use Databricks widgets and keep the `# Databricks notebook source` format.

**Status:** Maintained shared notebooks; they run only inside an existing Databricks job or cluster that you configure and start explicitly.

## Notebook contracts

- `train.py` trains/evaluates custom tabular, forecasting and image scenarios. Image training requires reviewed images/annotations on a Unity Catalog `/Volumes/...` directory and runs the shared vision engine on the driver (GPU cluster recommended). It exits and publishes task value `model_uri`.
- `batch_score.py` scores pinned `runs:/.../model` or numeric `models:/name/version` pyfuncs into Delta tables. It supports custom forecasting and image `image_base64` payloads; AutoML forecasting is refused because observed history belongs on the Azure ML scoring route.
- `stream_score.py` scores Event Hubs Kafka streams without printing secrets. Checkpoints must be stable and credential-free; image events should stay small or use URI-reference designs upstream because Event Hubs has per-event size limits.
- `serve.py` registers an evaluated run into Unity Catalog and creates/updates a Databricks Model Serving endpoint, with optional dataframe_split smoke query.

[Model-factory guide](../../readme.md)
