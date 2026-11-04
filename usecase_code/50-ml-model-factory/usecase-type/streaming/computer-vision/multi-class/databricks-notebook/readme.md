# databricks notebook

**Purpose:** Process arriving events continuously or in micro-batches. This branch covers `computer-vision/multi-class/databricks-notebook`.

**Owner:** User-facing examples.

**Edit/run guidance:** Customize project copies and their configuration; do not duplicate shared engine code.

**Status:** Executable notebook templates over shared engines; cloud steps are explicit, charged operations behind switches that default to false and need the listed prerequisites.

[Scenario configuration](../../../../../user-config/model/scenarios/readme.md) | [Shared execution code](../../../../../accelerator/readme.md) | [Start here](../../../../../readme.md)

<!-- usecase-catalog:start -->

## Implementation

**Examples:** [image-multiclass-databricks.ipynb](image-multiclass-databricks.ipynb)

**Training:** Databricks job task `train-evaluate` running the shared accelerator notebook on an existing cluster.

**Serving:** Databricks task `stream-score`: Event Hubs (Kafka) Structured Streaming into Delta.

**Prerequisites**

- Review the scenario's dataset status, license and notes; gated datasets stay blocked until approved.
- An existing Databricks workspace and cluster with the shared notebooks and factory wheel imported; Unity Catalog objects and permissions per `user-config/databricks`.
- An Event Hubs namespace, hub and consumer group, Data Receiver RBAC for the consumer identity, and durable checkpoint storage.

**Limitations**

- Base64 image events must respect Event Hubs message size limits; large images need storage URI references and a reviewed adapter.
- Databricks models live in Databricks MLflow/Unity Catalog, not in the Azure ML registry.
- Templates are not evidence of a completed Kaggle, Azure or Databricks run.

Generated from the use-case catalog (`python -m ml_model_factory usecases`); edit the catalog, not this block.

<!-- usecase-catalog:end -->

## References and examples

# Documentation

## Databricks machine learning
https://learn.microsoft.com/en-us/azure/databricks/en/machine-learning/

## Databricks - Train and deploy ML model

https://learn.microsoft.com/en-us/azure/databricks/en/getting-started/ml-get-started

## Databricks - Train and deploy DL model
https://learn.microsoft.com/en-us/azure/databricks/en/mlflow/mlflow3-dl-workflow

## Databricks docs - best practices
https://learn.microsoft.com/en-us/azure/databricks/en/notebooks/best-practices

## Databricks - Azure Event Hubs

https://learn.microsoft.com/en-us/azure/databricks/en/ldp/event-hubs

## Azure Databricks MLOps with MLflow
https://github.com/Azure-Samples/azure-databricks-mlops-mlflow
