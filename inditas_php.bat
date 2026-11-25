@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PHP=
for %%P in ("C:\xampp\php\php.exe" "D:\xampp\php\php.exe" "E:\xampp\php\php.exe") do if exist %%~P if not defined PHP set PHP=%%~P
if not defined PHP (
    echo Nem talalom a XAMPP php.exe fajlt.
    echo Masold a sql_megoldo.php fajlt a C:\xampp\htdocs mappaba, es nyisd meg: http://localhost/sql_megoldo.php
    pause
    exit /b
)
echo A szerver indul. A bongeszoben ez az oldal nyilik meg: http://localhost:8080/sql_megoldo.php
echo (Leallitas: zard be ezt az ablakot.)
start "" /min cmd /c "timeout /t 2 >nul & explorer http://localhost:8080/sql_megoldo.php"
"%PHP%" -S localhost:8080 -t .
pause
