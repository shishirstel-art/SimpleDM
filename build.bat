@echo off
echo === SimpleDM exe builder ===
where python >nul 2>nul
if errorlevel 1 goto nopython
python -m pip install --upgrade pip
python -m pip install requests libtorrent pyinstaller
python -m PyInstaller --noconsole --onefile --name SimpleDM --collect-all libtorrent app.py
echo.
echo Done. Your program is here: dist\SimpleDM.exe
pause
exit /b 0
:nopython
echo Python not found. Install it from python.org and tick Add Python to PATH, then run this file again.
pause
exit /b 1
