@echo off
::Prepare Winget
::-------------------------
echo Checking winget availability...
where winget >nul 2>&1
if %errorlevel% equ 0 (
    echo winget is already available, skipping registration...
) else (
    echo Registering Microsoft.DesktopAppInstaller for winget...
    cmd /c powershell.exe -NoLogo -NonInteractive -Command "& {Import-Module -Name Appx;Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe}" 2>nul
    if %errorlevel% neq 0 (
        echo Warning: winget registration failed, but continuing anyway...
    )
)
echo.

::Install VS Code
::-------------------------
echo Checking Visual Studio Code installation...
if exist "%ProgramFiles%\Microsoft VS Code\Code.exe" (
    echo VS Code already installed, skipping...
) else (
    echo Installing Visual Studio Code...
    winget install --exact --id Microsoft.VisualStudioCode --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo Warning: VS Code installation failed, but continuing...
    )
)
echo.

::Install VS Code extensions
::-------------------------
::set codecmd=%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd
set codecmd=%ProgramFiles%\Microsoft VS Code\bin\code.cmd
echo Installing VS Code extension: ms-python.python
cmd /c "%codecmd%" --install-extension ms-python.python --force
echo.
echo Installing VS Code extension: ms-vscode.powershell
cmd /c "%codecmd%" --install-extension ms-vscode.powershell --force
echo.
echo Installing VS Code extension: ms-azuretools.vscode-bicep
cmd /c "%codecmd%" --install-extension ms-azuretools.vscode-bicep --force
echo.
echo Installing VS Code extension: ms-vscode.azurecli
cmd /c "%codecmd%" --install-extension ms-vscode.azurecli --force
echo.
echo Installing VS Code extension: ms-toolsai.vscode-ai
cmd /c "%codecmd%" --install-extension ms-toolsai.vscode-ai --force
echo.

::Install Anaconda (miniconda3)
::-------------------------
echo Installing Miniconda...
if exist "C:\ProgramData\miniconda3" (
    echo Miniconda directory exists, attempting upgrade...
    winget upgrade --exact --id Anaconda.Miniconda3 --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
) else (
    winget install --exact --id Anaconda.Miniconda3 --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
)
echo.

::Install GitHub Cli
::-------------------------
echo Checking GitHub CLI installation...
where gh >nul 2>&1
if %errorlevel% equ 0 (
    echo GitHub CLI already installed, skipping...
) else (
    echo Installing GitHub Cli...
    winget install --exact --id GitHub.cli --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
)
echo.

::Install Azure Cli
::-------------------------
echo Checking Azure CLI installation...
where az >nul 2>&1
if %errorlevel% equ 0 (
    echo Azure CLI already installed, skipping...
) else (
    echo Installing Azure CLI...
    winget install --exact --id Microsoft.AzureCLI --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
)
echo.
::az extension list
::az extension remove -n azure-cli-ml
::az extension remove -n ml
::az extension add -n ml
::az extension update -n ml

::Install Python
::-------------------------
echo Checking Python 3.10 installation...
set pythonPath=%ProgramFiles%\Python310
if exist "%pythonPath%\python.exe" (
    echo Python 3.10 already installed, skipping...
) else (
    echo Installing Python 3.10...
    winget install --exact --id Python.Python.3.10 --scope machine --silent --disable-interactivity --accept-package-agreements --accept-source-agreements
)
echo.
echo Upgrading pip to latest version...
"%pythonPath%\python.exe" -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo Warning: pip upgrade failed, but continuing with existing version...
)
echo.

::Install Python extensions
::-------------------------
echo Installing Python packages (this may take a few minutes)...
echo Installing all Python packages with compatible dependency resolution...
"%pythonPath%\python.exe" -m pip install ^
    azure-ai-ml ^
    azure-identity ^
    openai ^
    azure-search-documents ^
    llama-index ^
    azureml-train-automl ^
    "azure-ai-projects>=2.0.0" ^
    "azure-ai-agents>=1.1.0" ^
    python-dotenv ^
    "azure-storage-blob>=12.28.0" ^
    "networkx>=3.0" ^
    "opentelemetry-sdk<1.39.0,>=1.22.0" ^
    --no-warn-script-location
echo.

::start Anaconda cmd, kick off automl_setup.cmd with "nolaunch" property
echo Setup AzureML v1.55 and v2.1.15
cmd /c "%ProgramData%\VirtualDesktop\AzureML_v1_55_and_v2_1_15\automl_setup.cmd"

pause

::https://learn.microsoft.com/en-us/azure/ai-studio/how-to/develop/sdk-overview