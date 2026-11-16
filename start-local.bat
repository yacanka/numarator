@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "ERRORLEVEL="
set "ROOT_DIR=%~dp0"
set "VENV_PYTHON=%ROOT_DIR%backend\.venv\Scripts\python.exe"

pushd "%ROOT_DIR%"
if errorlevel 1 goto :directory_error
if not exist "%ROOT_DIR%launcher.py" goto :missing_launcher

if not exist "%VENV_PYTHON%" goto :try_py
"%VENV_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 goto :run_venv

:try_py
py.exe -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 goto :run_py
python.exe -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 goto :run_python
python3.exe -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul
if not errorlevel 1 goto :run_python3

echo ERROR: Python 3.11+ was not found.
echo Install Python 3.11+ from https://www.python.org/downloads/windows/
echo Enable the Python launcher or add Python to PATH, then run this file again.
set "EXIT_CODE=1"
goto :finished

:run_venv
"%VENV_PYTHON%" "%ROOT_DIR%launcher.py" quickstart --environment development %*
set "EXIT_CODE=%ERRORLEVEL%"
goto :finished

:run_py
py.exe -3 "%ROOT_DIR%launcher.py" quickstart --environment development %*
set "EXIT_CODE=%ERRORLEVEL%"
goto :finished

:run_python
python.exe "%ROOT_DIR%launcher.py" quickstart --environment development %*
set "EXIT_CODE=%ERRORLEVEL%"
goto :finished

:run_python3
python3.exe "%ROOT_DIR%launcher.py" quickstart --environment development %*
set "EXIT_CODE=%ERRORLEVEL%"
goto :finished

:missing_launcher
echo ERROR: launcher.py was not found. Extract the complete Numarator project first.
set "EXIT_CODE=1"
goto :finished

:directory_error
echo ERROR: Could not open the Numarator project folder.
set "EXIT_CODE=1"
goto :failed

:finished
popd
if "%EXIT_CODE%"=="0" exit /b 0

:failed
echo.
echo Numarator could not start. Review the error above.
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
