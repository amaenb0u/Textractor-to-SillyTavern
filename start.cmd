@echo off
echo Activating environment and starting bridge...
call "Textractor-to-SillyTavern\Scripts\activate.bat"
python textractor_raw_bridge.py
pause