@echo off
cd /d "%~dp0"
python -m origins.report imparato > nul
start "" "logs\imparato.html"
