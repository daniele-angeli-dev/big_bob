@echo off
cd /d "%~dp0"
echo Installo le dipendenze Python...
python -m pip install -r requirements.txt
if errorlevel 1 (echo. & echo ERRORE: serve Python 3.10+ nel PATH. Scaricalo da python.org & pause & exit /b 1)
python setup_mcp.py
python tests\test_core.py
python tests\test_controller.py
python tests\test_sim.py
echo.
echo Fatto. Avvia BIG-BOB con avvia_BIG-BOB.bat
pause
