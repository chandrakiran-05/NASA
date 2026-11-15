@echo off
rem Publish the last commit to a Hugging Face Space. Works from any folder.
rem Usage: deploy_hf.cmd <hf-username>/<space-name>   (set HF_TOKEN first)
cd /d "%~dp0"
.venv\Scripts\python.exe deploy\hf\publish_space.py %*
