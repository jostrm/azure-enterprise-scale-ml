# Conda version
- 4.14.0
# Pip version
- 22.2.2
# Python version
- 3.8.13
# Azure ML and AutoML version (pulled: 2023-01-12)
- SDK: 1.48
- Environment: v 1.26 (mcr.microsoft.com/azureml/curated/azureml-automl:126 )
# Tested OK or NOT - history: fresh install on DSVM, with MiniConda, started in Admin mode
- STATUS: 
 - OK (2023-01-12) to train with AutoMLRun
 - ERROR (2023-01-12) to train with AutoMLStep in Pipeline
 - SUCCESS: Needed to find compatible docker image to create Environment. v126 was the one.

 
    
