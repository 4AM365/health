@echo off
REM Health Dashboard launcher.
REM Double-click to start. Close the window to stop.

cd /d "%~dp0"

echo Starting Health Dashboard...
echo.
echo When you see "URL: http://127.0.0.1:8501", a browser tab will open.
echo Close this window when you're done — that stops the server.
echo.

REM Open browser after a short delay so streamlit has time to bind.
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8501"

python -m streamlit run app/main.py ^
    --server.address=127.0.0.1 ^
    --server.port=8501 ^
    --server.headless=true ^
    --browser.gatherUsageStats=false

REM If streamlit exits for any reason, keep the window open so you can read the error.
echo.
echo The dashboard has stopped. Press any key to close this window.
pause >nul
