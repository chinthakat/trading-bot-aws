#!/bin/bash
# Stop existing
pkill -9 -f "python3 -m app.core_service"
pkill -9 -f "python3 -m app.strategy_runner"
pkill -9 -f "streamlit"
pkill -9 -f "python3" # Cleanup generic wrappers if any, carefully. Actually safer to target specifically.
# But 'streamlit' matches.


# Start Core
echo "Starting Core Service..."
nohup python3 -m app.core_service > core.log 2>&1 &
CORE_PID=$!
echo "Core PID: $CORE_PID"

# Wait for Core to Init DB
sleep 5

# Start Strategies
python3 -c "
import json
import subprocess
import os

try:
    with open('config.json') as f:
        cfg = json.load(f)
        strategies = cfg['trading']['active_strategies']
        symbols = cfg['trading']['symbols']
        
        for name, s in strategies.items():
            if s['enabled']:
                for symbol in symbols:
                    # Log File
                    clean_symbol = symbol.replace('/', '')
                    log_file = f'strat_{name}_{clean_symbol}.log'
                    
                    # Command
                    # json.dumps for params might contain spaces/quotes, so single-quote the json string
                    params_json = json.dumps(s['params'])
                    cmd = f\"nohup python3 -m app.strategy_runner --strategy {name} --symbol {symbol} --params '{params_json}' > {log_file} 2>&1 &\"
                    
                    print(f'Starting {name} for {symbol} >> {log_file}')
                    subprocess.Popen(cmd, shell=True)

except Exception as e:
    print(f'Error starting strategies: {e}')
"

# Start Dashboard
echo "Starting Dashboard..."
nohup streamlit run app/dashboard.py > dashboard.log 2>&1 &

echo "Bot Cluster Started."
