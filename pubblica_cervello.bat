@echo off
rem Pubblica o aggiorna il cervello comune di BIG-BOB sul tuo account Cloudflare (solo per chi gestisce il server).
cd /d "%~dp0"
chcp 65001 > nul
python cloud\pubblica.py
