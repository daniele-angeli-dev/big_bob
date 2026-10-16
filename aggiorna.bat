@echo off
setlocal
cd /d "%~dp0"
echo === Aggiornamento di BIG-BOB ===
where git >nul 2>nul
if errorlevel 1 (
  echo Serve Git per Windows: scaricalo da https://git-scm.com/download/win , installalo e rilancia aggiorna.bat.
  pause
  exit /b 1
)
if not exist ".git" (
  echo Primo collegamento al repository: GitHub potrebbe chiederti di accedere nel browser.
  git init -q
  git remote add origin https://github.com/daniele-angeli-dev/big_bob.git
)
git fetch -q origin main
if errorlevel 1 (
  echo ERRORE: non riesco a scaricare laggiornamento. Controlla la connessione e laccesso a GitHub.
  pause
  exit /b 1
)
git reset -q --hard origin/main
git branch -q -M main 2>nul
git branch -q --set-upstream-to=origin/main main 2>nul
echo Versione installata:
git log -1 --format="  %%h  %%s  (%%cd)" --date=format:"%%d/%%m/%%Y %%H:%%M"
echo Aggiorno le librerie...
python -m pip install -q -r requirements.txt
python setup_mcp.py
python tests\test_core.py
python tests\test_controller.py
python tests\test_sim.py
python collegamenti.py installa
echo.
echo Fatto. I tuoi dati (data, config.json, logs, captures) non sono stati toccati.
echo Se BIG-BOB era aperto, chiudilo e riaprilo con avvia_BIG-BOB.bat
pause
