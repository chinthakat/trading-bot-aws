
import boto3
import json
import os
import sys
from decimal import Decimal

# Add app directory to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))
from persistence import DynamoManager

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def inspect_latest_candle():
    config = load_config()
    db = DynamoManager(config)
    symbol = config['trading']['symbols'][0]
    
    print(f"Checking latest candle for {symbol}...")
    
    # Get latest
    items = db.get_price_history(symbol, limit=1)
    if not items:
        print("No items found.")
        return

    latest = items[0]
    print(f"Latest Candle Keys: {list(latest.keys())}")
    
    expected = ['bb_high', 'bb_mid', 'bb_low']
    found = [k for k in expected if k in latest]
    missing = [k for k in expected if k not in latest]
    
    print(f"Found Indicators: {found}")
    print(f"Missing Indicators: {missing}")
    print("Full Item:", latest)

if __name__ == "__main__":
    inspect_latest_candle()
