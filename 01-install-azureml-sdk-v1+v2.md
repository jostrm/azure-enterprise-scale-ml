# 1) Install ESML+ AMLv1+v2 (with AutoML) - on laptop or DSVM
1) Install/Open miniconda (exists already on DSVM)
    - Install MiniConda (>v 4.7), and open the MiniConda command prompt on your computer
    - https://docs.conda.io/projects/conda/en/latest/user-guide/install/windows.html
2) Open terminal in VS Code, or your MiniConda terminal on your laptop
3) Options:
    - a) AML SDKv1 - CD to `azure-enterprise-scale-ml\environment_setup\user_dev_env_install\AzureML_v1_55\`
    - b) AML SDKv1+SDKv2 - CD to `azure-enterprise-scale-ml\environment_setup\user_dev_env_install\AzureML_v1_55_and_v2_1_15\`
4) RUN `automl_setup.cmd` (If you are on Windows, otherwise on MAC `automl_setup_mac.sh` or on Linux: `automl_setup_linux.sh` )

# 2) Install on Azure Machine Learning - Compute Instance, and run AzureML Notebooks
Here a CONDA installation, without any start-script works, and the Linux YML file.

1) Go to NOTEBOOKS in Azure ML Studio
2) Open terminal. Create a COMPUTE INSTANCE, if needed, to power the terminal (and notebooks)
3) CD `azure-enterprise-scale-ml\environment_setup\user_dev_env_install\AzureML_v1_55`
4) CREATE the CONDA environment, and activate it:
    - conda deactivate
    - conda env list
    - conda env create -f automl_env_linux.yml
    - conda activate testenv

5) Open an ESML Quickstart Notebook - Note: It till not work to run notebook, until STEP 6) is DONE
- Example notebook: `notebook_templates_quickstart\2_PRODUCTION_phase_TRAIN_Pipeline_M10_M11.ipynb`
6) Create a NEW cell at the top. 
    - a) Notebook: CELL: Install the ipykernel package to make your Conda environment available in Jupyter Notebook
        - `pip install --user ipykernel`
    - b) Terminal: Run the below, in terminal - this associates your Conda environment with Jupyter Notebook.
        - `python -m ipykernel install --user --name=azure_automl_esml_v155`
    - c) Restart Jupyter Notebook. Close any sessions. 
        - Reopen and you should see  `azure_automl_esml_v155` as an option in the kernel
        - You may want to hit the REFRESH icon to the right (see image), and it will appear in the COMBOBOX. You may also run d) 
    - d) Optional: You can programmatically select environment wit this command in a CELL, at the top of notebook
        - `%%bashconda activate azure_automl_esml_v155`

It should look like something below: 
<img src="../../esml/images/Install_Readme_ComputeInstance_Conda.png" alt="drawing" width="100%"/>

    



