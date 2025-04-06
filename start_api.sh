#!/bin/bash
# Start The Hindu News Summarizer API

# Ensure output directories exist
mkdir -p output
mkdir -p output/translations

# Start the API server
echo "Starting The Hindu News Summarizer API server..."
echo "API will be available at http://0.0.0.0:5000"
echo "Press Ctrl+C to stop the server"

# Use gunicorn in production for better performance
if command -v gunicorn &> /dev/null; then
    gunicorn --bind 0.0.0.0:5000 api:app
else
    # Fallback to Flask's built-in server for development
    python api.py
fi 