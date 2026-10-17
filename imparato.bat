@echo off
cd /d "%~dp0"
python -m origins.report biblioteca imparato > nul
start "" "logs\biblioteca.html"
