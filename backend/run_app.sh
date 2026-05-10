#!/bin/bash

echo "=========================================="
echo "       MockMaster Setup + Run"
echo "=========================================="

# Go to script directory
cd "$(dirname "$0")"

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip

# Install requirements
if [ -f "requirements.txt" ]; then
    echo "Installing requirements..."
    pip install -r requirements.txt
else
    echo "requirements.txt not found!"
    exit 1
fi

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null
then
    echo ""
    echo "WARNING: ffmpeg is not installed."
    echo "Audio analysis may fail."
    echo ""
fi

# Start FastAPI
echo ""
echo "Starting server..."
echo ""

uvicorn backend.main:app --reload