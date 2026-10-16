@echo off
rem Finestra classica (senza grafica Arena), da usare se la nuova non parte
cd /d "%~dp0"
start "" pythonw app.py --classica
