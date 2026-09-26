@echo off
REM Double-click: rebuild workbooks from the saved JSON only (never calls Claude, costs nothing)
cd /d "%~dp0"
call run.bat --no-api
