@echo off
REM ============================================================
REM  BankOps AI Command Center - Stop All Servers
REM ============================================================

echo.
echo Stopping BankOps AI Command Center servers...
echo.

REM --- Kill processes on port 8000 (backend) ---
echo Stopping backend (port 8000)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /pid %%a /f >nul 2>nul && echo   Killed PID %%a
)

REM --- Kill processes on port 5173 (frontend) ---
echo Stopping frontend (port 5173)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    taskkill /pid %%a /f >nul 2>nul && echo   Killed PID %%a
)

echo.
echo All servers stopped.
pause
