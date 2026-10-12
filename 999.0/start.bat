@echo off
setlocal

rem ============================================================
rem  Lugwit Netdisk PC client - one click launcher
rem  Enters the rez package env (lugwit_netdisk_client) and runs the
rem  alias netdisk_client = python -m lugwit_netdisk_client.main
rem  Extra args are passed through, e.g.:
rem      start.bat --url http://127.0.0.1:8080 --page /baidu/files --minimized
rem  Keep this file pure ASCII to avoid GBK / UTF-8 mis-parse.
rem ============================================================

rem A stale PYTHONPATH from the outer shell would leak into the rez env.
set "PYTHONPATH="

rem wuwor.bat lives at trayapp\wuwo\wuwor.bat (3 levels up from this dir).
set "WUWOR=%~dp0..\..\..\wuwo\wuwor.bat"
if not exist "%WUWOR%" set "WUWOR=wuwor.bat"

echo [start] wuwor lugwit_netdisk_client -- netdisk_client %*
call "%WUWOR%" lugwit_netdisk_client -- netdisk_client %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [ERROR] start failed, exit code %RC% - see messages above.
    pause
)
exit /b %RC%
