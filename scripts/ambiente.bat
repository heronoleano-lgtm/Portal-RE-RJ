@echo off
REM Localiza o Python (não instala nada) e carrega o proxy local, pedindo a senha sem exibi-la.
set PY=
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python 3.9+ nao encontrado. Solicite a instalacao a TI ou use o Python ja disponivel na maquina.
  exit /b 1
)
if exist "%~dp0..\config\proxy_local.bat" call "%~dp0..\config\proxy_local.bat"
if defined MOTOR_PROXY_USER if not defined MOTOR_PROXY_PASS (
  for /f "usebackq delims=" %%s in (`powershell -NoProfile -Command "$p=Read-Host 'Senha do proxy' -AsSecureString; [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))"`) do set "MOTOR_PROXY_PASS=%%s"
)
exit /b 0
