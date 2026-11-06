@echo off
chcp 65001 >nul
REM Arraste o arquivo DB5186*.xlsx sobre este atalho
cd /d "%~dp0"
if "%~1"=="" (echo Arraste o arquivo .xlsx da base sobre este atalho. & goto :fim)
call "%~dp0scripts\ambiente.bat" || goto :fim
%PY% backend\cli.py importar "%~1"
:fim
pause
