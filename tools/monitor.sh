#!/bin/bash
export AIRIS_DB_PASSWORD='your_password'

python3 /iris-v3/tools/iris-monitor.py & python3 /iris-v3/tools/iris-drive-monitor.py
