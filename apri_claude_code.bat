@echo off
cd /d "%~dp0"
where claude >nul 2>&1 && (claude & goto :eof)
if exist "%USERPROFILE%\.local\bin\claude.exe" ("%USERPROFILE%\.local\bin\claude.exe" & goto :eof)
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe" ("%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe" & goto :eof)
echo Claude Code non e' installato: riapri BIG-BOB, lo installa da solo.
pause
