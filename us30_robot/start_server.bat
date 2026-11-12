@echo off
REM Porneste creierul Python al robotului US30 si il reporneste automat daca se opreste.
REM Dublu-click pe acest fisier. Pentru oprire definitiva: inchide fereastra.
title US30 Matrix - server
cd /d "%~dp0"
:loop
echo [%date% %time%] Pornesc serverul...
python run.py serve
echo [%date% %time%] Serverul s-a oprit. Repornesc in 10 secunde (inchide fereastra pentru oprire)...
timeout /t 10 /nobreak >nul
goto loop
