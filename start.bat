@echo off
REM ============================================================
REM  BankOps AI Command Center - One-Click Start Script
REM  SYNTHETIC DEMO ONLY - Not a real banking system
REM ============================================================

setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
set "VENV_PY=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "VENV_PIP=%BACKEND_DIR%\.venv\Scripts\pip.exe"

echo.
echo ============================================================
echo   BankOps AI Command Center - Starting Demo
echo   SYNTHETIC DATA ONLY - Not a real banking system
echo ============================================================
echo.

REM --- Step 1: Check prerequisites ---
echo [1/6] Checking prerequisites...

where python >nul 2>nul
if errorlevel 1 (
    echo   ERROR: Python is not installed or not on PATH.
    echo   Please install Python 3.12+ from https://python.org
    pause
    exit /b 1
)
echo   Python: OK

where node >nul 2>nul
if errorlevel 1 (
    echo   ERROR: Node.js is not installed or not on PATH.
    echo   Please install Node.js 20+ from https://nodejs.org
    pause
    exit /b 1
)
echo   Node.js: OK

where npm >nul 2>nul
if errorlevel 1 (
    echo   ERROR: npm is not installed or not on PATH.
    echo   Please install Node.js 20+ from https://nodejs.org
    pause
    exit /b 1
)
echo   npm: OK

REM --- Step 2: Create venv and install backend deps if needed ---
echo.
echo [2/6] Setting up backend...

if exist "%VENV_PY%" goto backend_ready

echo   Creating Python virtual environment...
pushd "%BACKEND_DIR%"
python -m venv .venv
if errorlevel 1 (
    echo   ERROR: Failed to create virtual environment.
    pause
    popd
    exit /b 1
)
echo   Installing backend dependencies (this may take a few minutes)...
"%VENV_PIP%" install --upgrade pip
"%VENV_PIP%" install -r requirements-dev.txt
if errorlevel 1 (
    echo   ERROR: Failed to install backend dependencies.
    pause
    popd
    exit /b 1
)
popd
echo   Backend dependencies installed.
goto step3

:backend_ready
echo   Virtual environment already exists.

:step3
REM --- Step 3: Create .env if missing ---
echo.
echo [3/6] Checking environment configuration...

if exist "%PROJECT_ROOT%\.env" goto env_ready
if not exist "%PROJECT_ROOT%\.env.example" goto env_warning
copy "%PROJECT_ROOT%\.env.example" "%PROJECT_ROOT%\.env" >nul
echo   Created .env from .env.example
goto step4

:env_warning
echo   WARNING: No .env.example found. Using defaults.
goto step4

:env_ready
echo   .env already exists.

:step4
REM --- Step 4: Run migrations and seed data ---
echo.
echo [4/6] Running database migrations and seeding synthetic data...

pushd "%BACKEND_DIR%"
echo   Running Alembic migrations...
"%VENV_PY%" -m alembic upgrade head
if errorlevel 1 (
    echo   ERROR: Migration failed.
    pause
    popd
    exit /b 1
)

echo   Seeding synthetic demo data (idempotent - safe to re-run)...
"%VENV_PY%" -m app.cli seed
if errorlevel 1 (
    echo   ERROR: Seeding failed.
    pause
    popd
    exit /b 1
)
popd
echo   Database ready.

REM --- Step 5: Install frontend deps if needed ---
echo.
echo [5/6] Setting up frontend...

if exist "%FRONTEND_DIR%\node_modules" goto frontend_ready

echo   Installing frontend dependencies (this may take a few minutes)...
pushd "%FRONTEND_DIR%"
npm ci
if errorlevel 1 (
    echo   npm ci failed, trying npm install...
    npm install
    if errorlevel 1 (
        echo   ERROR: Failed to install frontend dependencies.
        pause
        popd
        exit /b 1
    )
)
popd
echo   Frontend dependencies installed.
goto step6

:frontend_ready
echo   Frontend dependencies already installed.

:step6
REM --- Step 6: Start both servers ---
echo.
echo [6/6] Starting servers...
echo.

echo   Starting backend (FastAPI) on http://127.0.0.1:8000
start "BankOps Backend (port 8000)" cmd /k "cd /d "%BACKEND_DIR%" && "%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

echo   Waiting for backend to start...
set "WAIT_COUNT=0"

:wait_backend
timeout /t 2 /nobreak >nul
curl -sf http://127.0.0.1:8000/health >nul 2>nul
if not errorlevel 1 goto backend_up
set /a WAIT_COUNT+=1
if !WAIT_COUNT! lss 15 (
    echo   ...waiting (!WAIT_COUNT!/15)
    goto wait_backend
)
echo   WARNING: Backend health check timed out. It may still be starting.
echo   You can check http://127.0.0.1:8000/docs manually.
goto start_frontend

:backend_up
echo   Backend is ready.

:start_frontend
echo   Starting frontend (Vite) on http://127.0.0.1:5173
start "BankOps Frontend (port 5173)" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"

echo   Waiting for frontend to start...
set "WAIT_COUNT=0"

:wait_frontend
timeout /t 2 /nobreak >nul
curl -sf http://127.0.0.1:5173/ >nul 2>nul
if not errorlevel 1 goto frontend_up
set /a WAIT_COUNT+=1
if !WAIT_COUNT! lss 10 (
    echo   ...waiting (!WAIT_COUNT!/10)
    goto wait_frontend
)
echo   WARNING: Frontend health check timed out. It may still be starting.
goto show_summary

:frontend_up
echo   Frontend is ready.

:show_summary
echo.
echo ============================================================
echo   Both servers are running!
echo.
echo   Frontend (Dashboard):  http://127.0.0.1:5173
echo   Backend (API docs):    http://127.0.0.1:8000/docs
echo.
echo   Demo password:         BankOpsDemo^!2026
echo   Recommended login:     ops.analyst  (or ops.manager for approvals)
echo.
echo   To stop: close the two server windows, or run stop.bat
echo ============================================================
echo.

timeout /t 3 /nobreak >nul
start http://127.0.0.1:5173

echo Opening browser... The dashboard should appear shortly.
echo.
echo This window can be closed. The servers run in their own windows.
pause
endlocal
