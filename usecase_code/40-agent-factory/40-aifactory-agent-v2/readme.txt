AI Factory Agent v2 - placeholder

This folder currently contains only this README. There is no Python package,
requirements file, main.py, deployment entry point or runnable v2 agent here.
The folder name is not evidence that a second implementation has shipped.

Prerequisites
-------------
None for this placeholder. To use the implemented documentation-grounded agent
and private web application, open ..\40-aifactory-agent\readme.md.

How to set up the Python environment
------------------------------------
Do not create an environment in this empty folder. The implemented sibling
uses Python 3.12 and its own requirements.lock.txt (not the parent operator's
Python 3.13 environment). From this folder, its initial setup is:

    Set-Location ..\40-aifactory-agent
    py -3.12 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r .\requirements.lock.txt
    .\.venv\Scripts\python.exe -m pip install -e ..\..\..\environment_setup\azurefactory-cli

Create that environment only once and adjust the CLI path for a consumer copy.

How to run the code
------------------
There is no v2 code to run. From the implemented sibling selected above:

    .\.venv\Scripts\python.exe -m aifactory_agent --help

Then follow that sibling's "How to run the code" for config.local.json,
browser-based Azure sign-in, authorized deploy-agent/ingest operations, ask,
and optional serve. Help is offline; the application is not a local mock and
requires the private Azure services and user grants documented there.

For prompt/hosted framework examples instead, start at ..\readme.md.