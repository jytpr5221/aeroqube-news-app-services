@echo off
REM Start The Hindu News Summarizer API

REM Ensure output directories exist
if not exist output mkdir output
if not exist output\translations mkdir output\translations

REM Start the API server
echo Starting The Hindu News Summarizer API server...
echo API will be available at http://0.0.0.0:5000
echo Press Ctrl+C to stop the server

REM Check if gunicorn is available
where gunicorn >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    gunicorn --bind 0.0.0.0:5000 api:app
) else (
    REM Fallback to Flask's built-in server for development
    python api.py
) 