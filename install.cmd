@echo off
echo Creating Python virtual environment...
python -m venv "Textractor-to-SillyTavern"
echo.
echo Activating environment...
call "Textractor-to-SillyTavern\Scripts\activate.bat"
echo.
echo Installing requirements...
pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Installing Playwright Chromium...
playwright install chromium
echo.
echo Installation complete! Use start.cmd to run.
pause