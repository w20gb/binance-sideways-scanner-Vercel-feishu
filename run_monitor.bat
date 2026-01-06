@echo off
echo ===================================================
echo Wyckoff Anomaly Detection Monitor - One Click Start
echo ===================================================
echo.
echo [1/2] Checking dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies. Please check network.
    pause
    exit /b
)
echo.
echo [2/2] Starting Monitor...
python wyckoff_monitor.py
echo.
echo Program stopped.
pause
