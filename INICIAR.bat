@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0scripts\ambiente.bat" || goto :fim
echo Abrindo o portal em http://localhost:8750 ...
start "" http://localhost:8750
%PY% backend\cli.py iniciar
:fim
pause
