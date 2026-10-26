@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw mouse_battery_tray.py
) else (
    python mouse_battery_tray.py
)
