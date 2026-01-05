
import os
import sys
import json
import boto3
import time
from decimal import Decimal

def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config.json')
    if not os.path.exists(config_path): config_path = 'config.json'
    with open(config_path, 'r') as f:
        return json.load(f)

def reset_test_balance():
    config = load_config()
    region = config['aws']['region']
    table_name = config['aws']['tables'].get('test_account', 'TradingBot_Test_Account')
    
    print(f"Resetting Test Balance in {table_name}...")
    
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    ts = int(time.time() * 1000)
    
    table.put_item(
        Item={
            'account_id': 'test_account',
            'timestamp': ts,
            'balance': Decimal('10000'),
            'updated_at': ts
        }
    )
    print("Balance reset to $10,000.")

if __name__ == "__main__":
    reset_test_balance()
