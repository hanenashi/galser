@echo off
setlocal
REM ---- Config ----
set PORT=8000

REM Launch server in the current folder
REM If Python 3 is not on PATH, adjust the next line to your python.exe
start "" cmd /c "python server.py --port %PORT%"

REM Open browser to localhost
REM start "" "http://127.0.0.1:%PORT%/"

echo.
echo Gallery server started on http://127.0.0.1:%PORT%/
echo If you want to reach it from your phone, use your PC's LAN IP:
ipconfig | findstr /R /C:"IPv4 Address"
echo.
echo Press any key to close this starter window (server keeps running)...
pause >nul
endlocal
