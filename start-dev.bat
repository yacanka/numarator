@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "FRONTEND_DIR=%ROOT_DIR%frontend"
set "VENV_DIR=%BACKEND_DIR%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQUIREMENTS_FILE=%BACKEND_DIR%\requirements\development.txt"
set "DJANGO_SETTINGS_MODULE=config.settings.development"
set "BACKEND_URL=http://127.0.0.1:8000"
set "FRONTEND_URL=http://127.0.0.1:5173"

call :print_header
call :validate_directories || goto :failed
call :detect_python || goto :failed
call :validate_node || goto :failed
call :prepare_backend || goto :failed
call :prepare_frontend || goto :failed
call :start_services || goto :failed
call :print_success
exit /b 0

:print_header
echo ============================================================
echo  DocNumber development launcher
echo ============================================================
echo Root      : %ROOT_DIR%
echo Backend   : %BACKEND_DIR%
echo Frontend  : %FRONTEND_DIR%
echo.
exit /b 0

:validate_directories
if not exist "%BACKEND_DIR%\manage.py" call :fail "Backend manage.py was not found."
if errorlevel 1 exit /b 1
if not exist "%FRONTEND_DIR%\package.json" call :fail "Frontend package.json was not found."
if errorlevel 1 exit /b 1
if not exist "%REQUIREMENTS_FILE%" call :fail "Backend development requirements were not found."
if errorlevel 1 exit /b 1
exit /b 0

:detect_python
where py >nul 2>nul
if not errorlevel 1 set "PYTHON_COMMAND=py -3" && exit /b 0
where python >nul 2>nul
if not errorlevel 1 set "PYTHON_COMMAND=python" && exit /b 0
call :fail "Python 3 was not found in PATH. Install Python 3.11+ and retry."
exit /b 1

:validate_node
where node >nul 2>nul
if errorlevel 1 call :fail "Node.js was not found in PATH. Install Node.js 20+ and retry."
if errorlevel 1 exit /b 1
where npm >nul 2>nul
if errorlevel 1 call :fail "npm was not found in PATH. Reinstall Node.js with npm enabled."
if errorlevel 1 exit /b 1
exit /b 0

:prepare_backend
echo [1/5] Preparing Python virtual environment...
if not exist "%VENV_PYTHON%" %PYTHON_COMMAND% -m venv "%VENV_DIR%"
if errorlevel 1 call :fail "Could not create Python virtual environment."
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 call :fail "Could not upgrade pip. Check network or proxy settings."
if errorlevel 1 exit /b 1
"%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS_FILE%"
if errorlevel 1 call :fail "Could not install backend dependencies. Check network or proxy settings."
if errorlevel 1 exit /b 1
call :run_django_checks
exit /b %errorlevel%

:run_django_checks
echo [2/5] Running Django checks and migrations...
pushd "%BACKEND_DIR%"
"%VENV_PYTHON%" manage.py check
if errorlevel 1 popd & call :fail "Django system check failed." & exit /b 1
"%VENV_PYTHON%" manage.py migrate --no-input
if errorlevel 1 popd & call :fail "Database migration failed." & exit /b 1
popd
exit /b 0

:prepare_frontend
echo [3/5] Installing frontend dependencies...
pushd "%FRONTEND_DIR%"
call npm install
if errorlevel 1 popd & call :fail "Could not install frontend dependencies. Check network or proxy settings." & exit /b 1
popd
exit /b 0

:start_services
echo [4/5] Starting backend and frontend in separate windows...
start "DocNumber Backend" /D "%BACKEND_DIR%" cmd /k "set DJANGO_SETTINGS_MODULE=%DJANGO_SETTINGS_MODULE%&& ^"%VENV_PYTHON%^" manage.py runserver 127.0.0.1:8000"
if errorlevel 1 call :fail "Could not start backend terminal."
if errorlevel 1 exit /b 1
start "DocNumber Frontend" /D "%FRONTEND_DIR%" cmd /k "npm run dev -- --host 127.0.0.1"
if errorlevel 1 call :fail "Could not start frontend terminal."
if errorlevel 1 exit /b 1
exit /b 0

:print_success
echo [5/5] Services are starting.
echo Backend : %BACKEND_URL%
echo API docs: %BACKEND_URL%/api/docs/
echo Frontend: %FRONTEND_URL%
echo.
echo Close the two opened terminal windows to stop the services.
exit /b 0

:fail
echo.
echo ERROR: %~1
echo.
exit /b 1

:failed
echo Startup aborted.
exit /b 1
