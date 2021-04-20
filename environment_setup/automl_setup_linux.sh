#!/bin/bash

# TODO: export PATH: https://www.anaconda.com/blog/how-to-get-ready-for-the-release-of-conda-4-4
# $(System.DefaultWorkingDirectory)/_devops-for-ai-CI/devops-for-ai/environment_setup/install_requirements.sh

CONDA_ENV_NAME=$1
AUTOML_ENV_FILE=$2
OPTIONS=$3
PIP_NO_WARN_SCRIPT_LOCATION=0
CHECK_CONDA_VERSION_SCRIPT="check_conda_version.py"

ls -l
echo "2_Currentd dir:" $PWD
#echo "##vso[task.prependpath]$CONDA/bin"
#echo "##vso[task.prependpath]$env:CONDA\Scripts" # Bin might be enough

conda init bash
conda init powershell # modifies the configs for the shells...to find conda in path
echo "Anna"

if [ "$CONDA_ENV_NAME" == "" ]
then
  CONDA_ENV_NAME="azure_automl"
fi

if [ "$AUTOML_ENV_FILE" == "" ]
then
  AUTOML_ENV_FILE="automl_env_linux.yml"
fi

if [ ! -f $AUTOML_ENV_FILE ]; then
    echo "File $AUTOML_ENV_FILE not found"
    exit 1
fi


#if [ ! -f $CHECK_CONDA_VERSION_SCRIPT ]; then
#    echo "File $CHECK_CONDA_VERSION_SCRIPT not found"
#    exit 1
#fi

#python "$CHECK_CONDA_VERSION_SCRIPT"
#if [ $? -ne 0 ]; then
#    exit 1
#fi

# automl_setup_linux.sh: line 51: activate: No such file or directory

#TODO: not nessisary...does not exists
sed -i 's/AZUREML-SDK-VERSION/latest/' $AUTOML_ENV_FILE

if conda activate $CONDA_ENV_NAME 2> /dev/null
then
   echo "Upgrading existing conda environment" $CONDA_ENV_NAME
   pip uninstall azureml-train-automl -y -q
   conda env update --name $CONDA_ENV_NAME --file $AUTOML_ENV_FILE &&
   jupyter nbextension uninstall --user --py azureml.widgets
else
   echo "Conda version"
   conda --version
   ls -l
   echo "2_Currentd dir:" $PWD
   conda env create -f $AUTOML_ENV_FILE -n $CONDA_ENV_NAME &&
   
   conda env list
   # conda activate $CONDA_ENV_NAME  # https://github.com/conda/conda-build/issues/3371
   
   #Not tested yet
   #eval "$(conda shell.bash hook)"

   eval "$(command conda 'shell.bash' 'hook' 2> /dev/null)"
   #conda init bash
   conda activate $CONDA_ENV_NAME # Since I run v 4.9.2 (newer than 4.4)

   #source activate $CONDA_ENV_NAME # For conda versions older than 4.4 the command 'source activate' 

   #source activate $CONDA_ENV_NAME &&
   #python -m ipykernel install --user --name $CONDA_ENV_NAME --display-name "Python ($CONDA_ENV_NAME)" &&
   #jupyter nbextension uninstall --user --py azureml.widgets &&
   echo "" &&
   echo "" &&
   echo "***************************************" &&
   echo "* AutoML setup completed successfully *" &&
   echo "***************************************"
   #if [ "$OPTIONS" != "nolaunch" ]
   #then
      #echo "" &&
      #echo "Starting jupyter notebook - please run the configuration notebook" &&
      #echo "" &&
      #jupyter notebook --log-level=50 --notebook-dir '../..'
   #fi
fi

if [ $? -gt 0 ]
then
   echo "Installation failed"
fi


