########
### This script will install the client (data scientist) SDKs on a Windows 11 VM
### Note: This requires WinGet (e.g. not Windows 10, 11. It is not default on Windows Server)
### Description: This script can be kicked off under "Opertaions/Run command/RunPowerShellScript" in the portal when the VM is running.
###It will create the RunAsAdmin.cmd on the Public Desktop and the AzureML_v1_55_and_v2_1_15 stuff created under C:\ProgramData\AzureML_v1_55_and_v2_1_15
### - Once all 4 files is created on the VM, user can login, and can kick off the RunAsAdmin.cmd on the desktop
######## Create Desktop installation file
########################################################################
$cmd_File_Desktop = Join-Path $env:PUBLIC ('Desktop\RunAsAdmin.cmd')
$cmd_File_Desktop_Content = @'
@echo off
::Prepare Winget
::-------------------------

echo Registering Microsoft.DesktopAppInstaller for winget...

cmd /c powershell.exe -NoLogo -NonInteractive -Command "& {Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe}"
echo.

::Upgrade Winget
::-------------------------
echo Updating winget - needs to be above v1.4...
winget upgrade --id Microsoft.Winget.Source

::Install VS Code
::-------------------------
echo Installing Visual Studio Code...
winget install --exact --id Microsoft.VisualStudioCode --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
echo.

::Install VS Code extensions
::-------------------------
::set codecmd="%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"
set codecmd="%ProgramFiles%\Microsoft VS Code\bin\code.cmd"
echo Installing VS Code extension: ms-python.python
cmd /c %codecmd% --install-extension ms-python.python --force
echo.
echo Installing VS Code extension: ms-vscode.powershell
cmd /c %codecmd% --install-extension ms-vscode.powershell --force
echo.
echo Installing VS Code extension: ms-azuretools.vscode-bicep
cmd /c %codecmd% --install-extension ms-azuretools.vscode-bicep --force
echo.
echo Installing VS Code extension: ms-vscode.azurecli
cmd /c %codecmd% --install-extension ms-vscode.azurecli --force
echo.
echo Installing VS Code extension: ms-toolsai.vscode-ai
cmd /c %codecmd% --install-extension ms-toolsai.vscode-ai --force
echo.

::Install Anaconda (miniconda3)
::-------------------------
echo Installing Miniconda...
winget install --exact --id Anaconda.Miniconda3 --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
echo.

::Install GitHub Cli
::-------------------------
echo Installing GitHub Cli...
winget install --exact --id GitHub.cli --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
echo.

::Install Azure Cli
::-------------------------
echo Installing Azure CLI...
winget install --exact --id Microsoft.AzureCLI --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
echo.
::az extension list
::az extension remove -n azure-cli-ml
::az extension remove -n ml
::az extension add -n ml
::az extension update -n ml

::Install Python
::-------------------------
echo Installing Python 3.10...
winget install --exact --id Python.Python.3.10 --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
echo.
set pythonPath=%ProgramFiles%\Python310
::cmd /c "%pythonPath%python.exe" -m pip install --upgrade pip

::Install Python extensions
::-------------------------
set pipcmd="%pythonPath%\Scripts\pip.exe"
echo Installing Python extension: azure-ai-ml
cmd /c %pipcmd% install azure-ai-ml --no-warn-script-location
echo.
echo Installing Python extension: azure-identity
cmd /c %pipcmd% install azure-identity --no-warn-script-location
echo.
echo Installing Python extension: openai
cmd /c %pipcmd% install openai --no-warn-script-location
echo.
echo Installing Python extension: azure-search-documents
cmd /c %pipcmd% install azure-search-documents --no-warn-script-location
echo.
echo Installing Python extension: promptflow
cmd /c %pipcmd% install promptflow --no-warn-script-location
echo.
echo Installing Python extension: llama-index
cmd /c %pipcmd% install llama-index --no-warn-script-location
echo.
echo Installing Python extension: azureml-train-automl
cmd /c %pipcmd% install azureml-train-automl --no-warn-script-location
echo.

::start Anaconda cmd, kick off automl_setup.cmd with "nolaunch" property
echo Setup AzureML v1.55 and v2.1.15
cmd /c "%ProgramData%\AzureML_v1_55_and_v2_1_15\automl_setup.cmd"

pause

::https://learn.microsoft.com/en-us/azure/ai-studio/how-to/develop/sdk-overview
'@

Write-Host ('Creating file: {0}'-f $cmd_File_Desktop)
Out-File -FilePath $cmd_File_Desktop -InputObject $cmd_File_Desktop_Content -Encoding ascii -Force
Write-Host ('File created: {0}' -f (Test-Path $cmd_File_Desktop))


########################################################################
### Create AzureML files
########################################################################
$azureML_directory = Join-Path $env:ProgramData 'AzureML_v1_55_and_v2_1_15'
Write-Host ('Creating directory: {0}'-f $azureML_directory)
[void](New-Item -Type Directory $azureML_directory -Force)
Write-Host ('Directory created: {0}'-f (Test-Path $azureML_directory))

### Create AzureML automl_env.yml
########################################################################
$automl_env_File = Join-Path $azureML_directory 'automl_env.yml'
$automl_env_FileContent = @'
name: azure_automl_esml_v155_v115
channels:
  - conda-forge
  - pytorch
  - main
dependencies:
  # The python interpreter version.
  # Azure ML only supports 3.8 and later.
- pip==22.3.1
- python>=3.9,<3.10
- holidays==0.29
- scipy==1.10.1
- tqdm==4.66.1

- pip:
 #ESML - Required for OUTER LOOP MLOps (aml sdk v1.55)
  - azure-keyvault==4.1.0 
  - azure-keyvault-keys==4.4.0
  - azure-keyvault-secrets==4.3.0
  - azure-keyvault-certificates~=4.3.0
  - seaborn==0.11.1 # ESML optional for reporting (todo remove this dependancy)
  - azure-storage-file-datalake==12.6.0 # ESML required to write files to GEN 2 - Bronze,Silver,Gold
# END ESML
# AzureML v2
  - azure-ai-ml~=1.15.0
  - azure-identity~=1.15.0
# END AzureML v2
# Extra
  - python-dotenv
# Extra end
  # Required packages for AzureML execution, history, and data preparation.
  - azureml-widgets~=1.55.0
  - azureml-defaults~=1.55.0
  - -r https://automlsdkdataresources.blob.core.windows.net/validated-requirements/1.55.0/validated_win32_requirements.txt [--no-deps]
  - matplotlib==3.7.1
  - xgboost==1.3.3
  - prophet==1.1.4
  - pandas==1.3.5
  - cmdstanpy==1.1.0
  - setuptools-git==1.2
'@

Write-Host ('Creating file: {0}'-f $automl_env_File)
Out-File -FilePath $automl_env_File -InputObject $automl_env_FileContent -Encoding ascii -Force
Write-Host ('File created: {0}' -f (Test-Path $automl_env_File))


### Create AzureML automl_setup.cmd
########################################################################
$automl_setup_File = Join-Path $azureML_directory 'automl_setup.cmd'
$automl_setup_FileContent = @'
@echo off
set currentDir=%cd%
cd %~dp0
@CALL "%ProgramData%\miniconda3\condabin\conda.bat" activate %*

set conda_env_name=%1
set automl_env_file=%2
set options=%3
set PIP_NO_WARN_SCRIPT_LOCATION=0

IF "%conda_env_name%"=="" SET conda_env_name="azure_automl_esml_v155_v115"
IF "%automl_env_file%"=="" SET automl_env_file="automl_env.yml"
SET check_conda_version_script="check_conda_version.py"

IF NOT EXIST %automl_env_file% GOTO YmlMissing

IF "%CONDA_EXE%"=="" GOTO CondaMissing

IF NOT EXIST %check_conda_version_script% GOTO VersionCheckMissing

python "%check_conda_version_script%"
IF errorlevel 1 GOTO ErrorExit:

SET replace_version_script="replace_latest_version.ps1"
IF EXIST %replace_version_script% (
  powershell -file %replace_version_script% %automl_env_file%
)

call conda activate %conda_env_name% 2>nul:

if not errorlevel 1 (
  echo Upgrading existing conda environment %conda_env_name%
  call pip uninstall azureml-train-automl -y -q
  call conda env update --name %conda_env_name% --file %automl_env_file%
  if errorlevel 1 goto ErrorExit
) else (
  call conda env create -f %automl_env_file% -n %conda_env_name%
)

python "%conda_prefix%\scripts\pywin32_postinstall.py" -install

call conda activate %conda_env_name% 2>nul:
if errorlevel 1 goto ErrorExit

call python -m ipykernel install --user --name %conda_env_name% --display-name "Python (%conda_env_name%)"

REM azureml.widgets is now installed as part of the pip install under the conda env.
REM Removing the old user install so that the notebooks will use the latest widget.
call jupyter nbextension uninstall --user --py azureml.widgets

echo.
echo.
echo ***************************************
echo * AutoML setup completed successfully *
echo ***************************************

goto end
IF NOT "%options%"=="nolaunch" (
  echo.
  echo Starting jupyter notebook - please run the configuration notebook 
  echo.
  jupyter notebook --log-level=50 --notebook-dir='..\..'
)

goto End

:CondaMissing
echo Please run this script from an Anaconda Prompt window.
echo You can start an Anaconda Prompt window by
echo typing Anaconda Prompt on the Start menu.
echo If you don't see the Anaconda Prompt app, install Miniconda.
echo If you are running an older version of Miniconda or Anaconda,
echo you can upgrade using the command: conda update conda
goto End

:VersionCheckMissing
echo File %check_conda_version_script% not found.
goto End

:YmlMissing
echo File %automl_env_file% not found.

:ErrorExit
echo Install failed

:End
exit
cd %currentDir%
'@

Write-Host ('Creating file: {0}'-f $automl_setup_File)
Out-File -FilePath $automl_setup_File -InputObject $automl_setup_FileContent -Encoding ascii -Force
Write-Host ('File created: {0}' -f (Test-Path $automl_setup_File))


### Create AzureML check_conda_version.py
########################################################################
$check_conda_version_File = Join-Path $azureML_directory 'check_conda_version.py'
$check_conda_version_FileContent = @'
from setuptools._vendor.packaging import version
import platform

try:
    import conda
except Exception:
    print('Failed to import conda.')
    print('This setup is usually run from the base conda environment.')
    print('You can activate the base environment using the command "conda activate base"')
    exit(1)

architecture = platform.architecture()[0]

if architecture != "64bit":
    print('This setup requires 64bit Anaconda or Miniconda.  Found: ' + architecture)
    exit(1)

minimumVersion = "4.7.8"

versionInvalid = (version.parse(conda.__version__) < version.parse(minimumVersion))

if versionInvalid:
    print('Setup requires conda version ' + minimumVersion + ' or higher.')
    print('You can use the command "conda update conda" to upgrade conda.')

exit(versionInvalid)
'@

Write-Host ('Creating file: {0}'-f $check_conda_version_File)
Out-File -FilePath $check_conda_version_File -InputObject $check_conda_version_FileContent -Encoding ascii -Force
Write-Host ('File created: {0}' -f (Test-Path $check_conda_version_File))