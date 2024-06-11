# 1) Install ESML+ AMLv1+v2 (with AutoML) - on laptop or DSVM
1) Install/Open miniconda (exists already on DSVM)
    - Install MiniConda (>v 4.7), and open the MiniConda command prompt on your computer
    - https://docs.conda.io/projects/conda/en/latest/user-guide/install/windows.html
2) Open terminal in VS Code, or your MiniConda terminal on your laptop
    - Option a) Download the latest install folder `AzureML_v1_55_and_v2_1_15.zip`
    - Option b) Clone your repo, containing the `azure-enterprise-scale-ml` repo
3) Go to the install folder in  `azure-enterprise-scale-ml`:
    - Option a) AML SDKv1+SDKv2 - CD to `azure-enterprise-scale-ml\environment_setup\install_sdk\user_dev_env_install\AzureML_v1_55_and_v2_1_15`
        - [Link to AzureML_v1_55_and_v2_1_15](../../user_dev_env_install/AzureML_v1_55_and_v2_1_15/)
    - Option b) AML SDKv1 - CD to `azure-enterprise-scale-ml\environment_setup\install_sdk\user_dev_env_install\AzureML_v1_55`
        - [Link to AzureML_v1_55 ](../../user_dev_env_install/AzureML_v1_55/)
4) RUN `automl_setup.cmd`If you are on Windows (10 or 11)
    - Windows: `automl_setup.cmd` 
        - Choose this optiom for BUILD AGENT. 
            - Tip: Choose the already created VM called `dsvm-cmn-swe-dev-001`
        - Choose this options for you USERS LAPTOP, if Windows 10 or 11.
            - Tip & Fallback: You always have a project specific Windows DSVM `dsvm-project001-swe-dev-001`
    - MAC `automl_setup_mac.sh`, if your data scientist has this OS on laptop
    - LINUX `automl_setup_linux.sh`, if your data scientist has this OS on laptop
