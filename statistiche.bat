@echo off
cd /d "%~dp0"
python -m origins.report stats > nul
start "" "logs\statistiche.html"
