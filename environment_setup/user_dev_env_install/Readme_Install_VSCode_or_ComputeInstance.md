# 1) Install on local developer laptop
1) Open terminal in VS Code, or your MiniConda terminal on your laptop
2) CD to `azure-enterprise-scale-ml\environment_setup\user_dev_env_install\AzureML_v1_55\`
3) RUN `automl_setup.cmd` (If you are on Windows, otherwise on MAC `automl_setup_mac.sh` or on Linux: `automl_setup_linux.sh` )

# 2) Install on Azure Machine Learning - Compute Instance, and run AzureML Notebooks
Here a CONDA installation, without any start-script works, and the Linux YML file.

1) Go to NOTEBOOKS in Azure ML Studio
2) Open terminal. Create a COMPUTE INSTANCE, if needed, to power the terminal (and notebooks)
3) CD `azure-enterprise-scale-ml\environment_setup\user_dev_env_install\AzureML_v1_55`
4) CREATE the CONDA environment
    - conda deactivate
    - conda env list
    - conda env create -f automl_env_linux.yml
    - conda activate testenv

5) Open an ESML Quickstart Notebook, and see if it works
- Example notebook: `notebook_templates_quickstart\2_PRODUCTION_phase_TRAIN_Pipeline_M10_M11.ipynb`


