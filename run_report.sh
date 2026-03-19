#!/bin/bash

# Navigate to the persistent directory
cd /home/moreh/npu-automate-tools || exit

# Pull the latest changes from your repo
git pull origin main

# Sync dependencies instantly using uv
uv sync

# Run the Python script, passing along any arguments (like -d 0 or -d -1 0)
uv run create_daily_report/main.py "$@"
