@echo off
cd /d "%~dp0"
echo Installo le dipendenze Python...
python -m pip install -r requirements.txt
if errorlevel 1 (echo. & echo ERRORE: serve Python 3.10+ nel PATH. Scaricalo da python.org & pause & exit /b 1)
python setup_mcp.py
python tests\test_core.py
python tests\test_controller.py
python tests\test_sim.py
python tests\test_originsmeta.py
python collegamenti.py installa
echo.
echo Fatto. Da ora avvii BIG-BOB dall'icona sul desktop o dal menu Start.
pause
