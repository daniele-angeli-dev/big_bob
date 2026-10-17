@echo off
cd /d "%~dp0"
python -m origins.report biblioteca statistiche > nul
start "" "logs\biblioteca.html"
