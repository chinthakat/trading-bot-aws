#!/bin/bash
# start_bot.sh
# Kills existing processes and starts the Trading Bot Cluster

# 1. Kill explicit
pkill -9 -f python3
pkill -9 -f streamlit

# 2. Wait
sleep 2

# 3. Start Core Service (Background)
nohup python3 app/bot.py > logs/core.log 2>&1 &
CORE_PID=$!
echo "Core Service PID: $CORE_PID"

# 4. Wait for Core to Init
sleep 5

# 5. Start Dashboard (Background)
nohup python3 -m streamlit run app/dashboard.py > logs/dashboard.log 2>&1 &
DASH_PID=$!
echo "Dashboard PID: $DASH_PID"

echo "Bot Cluster Started."
