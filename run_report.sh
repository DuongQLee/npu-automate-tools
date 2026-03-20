#!/bin/bash

export PATH="/home/moreh/.cargo/bin:/home/moreh/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

cd /home/moreh/npu-automate-tools || exit 1

git pull origin main
uv sync
uv run create_daily_report/main.py "$@"
