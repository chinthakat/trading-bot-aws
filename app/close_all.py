
import os
import sys
import json
import boto3
import time
from datetime import datetime
from decimal import Decimal

# Setup paths
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from services.db_service import SharedDbService

def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

def close_all_positions():
    config = load_config()
    region = config['aws']['region']
    mode = config['trading'].get('mode', 'TEST')
    
    print(f"--- Closing All Positions (Mode: {mode}) ---")
    
    # 1. DynamoDB
    if mode == 'TEST':
        table_name = config['aws']['tables'].get('test_positions', 'TradingBot_Test_Positions')
    else:
        table_name = config['aws']['tables'].get('positions', 'TradingBot_Positions')
        
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    # Scan Open
    response = table.scan(
        FilterExpression='#st = :open OR #st = :req',
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':open': 'open', ':req': 'request_close'}
    )
    items = response.get('Items', [])
    print(f"Found {len(items)} open positions in DynamoDB.")
    
    ts = int(time.time() * 1000)
    
    for item in items:
        pid = item['position_id']
        symbol = item['symbol']
        print(f"Force Closing {pid} ({symbol}) in DynamoDB...")
        
        # We don't have current price easily here without initialization overhead.
        # We'll set exit_price = entry_price (Breakeven) for administrative close.
        entry_price = item['entry_price']
        
        table.update_item(
             Key={'position_id': pid},
             UpdateExpression='SET #st = :closed, exit_price = :ep, exit_time = :et, pnl = :pnl, metadata = :meta',
             ExpressionAttributeNames={'#st': 'status'},
             ExpressionAttributeValues={
                 ':closed': 'closed',
                 ':ep': entry_price, # Breakeven
                 ':et': ts,
                 ':pnl': Decimal('0'),
                 ':meta': 'Force closed via script'
             }
        )
        
    # 2. SQLite (Shared DB)
    print("Clearing Shared DB Positions...")
    try:
        db = SharedDbService()
        db.conn.execute("DELETE FROM positions") # Nuke all active positions from cache
        db.conn.commit()
        print("Shared DB Positions Cleared.")
    except Exception as e:
        print(f"Shared DB Error: {e}")
        
    print("Done. Please restart the bot to reload clean state.")

if __name__ == "__main__":
    close_all_positions()
