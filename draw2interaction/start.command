#!/bin/zsh
# Start the local workspace using the existing Python experiment environment.
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1
python3 -B experiments/open_ended_sketch/app/server.py
