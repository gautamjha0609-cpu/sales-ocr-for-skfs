@echo off
REM Double-click: reads new photos in input\ and rebuilds the month workbook(s) in output\
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up Python packages...
  py -3 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
".venv\Scripts\python.exe" -m skfs_ocr run %*
echo.
echo Done. Workbook and check report are in the output folder.
pause
