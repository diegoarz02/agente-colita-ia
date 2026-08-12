@echo off
REM Arranque manual: borra la marca de "cerrada a proposito" y la despierta.
if exist "%~dp0descansando.flag" del /q "%~dp0descansando.flag"
start "" "C:\venvs\colita\Scripts\pythonw.exe" "%~dp0orbe.py"
