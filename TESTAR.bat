@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0scripts\ambiente.bat" || goto :fim
%PY% -m unittest discover -s tests -t . -v
:fim
pause
