@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[IO.File]::ReadAllText('sql_megoldo.ps1',[Text.Encoding]::UTF8) | Invoke-Expression"
echo.
pause
