@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
py -3 -c "import sys; sys.exit(sys.version_info < (3,9))" >nul 2>&1
if not errorlevel 1 (
    py -3 web_server.py %*
    goto finished
)
python -c "import sys; sys.exit(sys.version_info < (3,9))" >nul 2>&1
if not errorlevel 1 (
    python web_server.py %*
    goto finished
)
echo Python 3.9 or newer is required. Install Python through your organization's approved software source, then try again.
:finished
if not defined SPACESHIP_TEST_MODE pause
endlocal
