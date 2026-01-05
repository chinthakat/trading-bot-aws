
import boto3
import json
from decimal import Decimal
import time

def reset_test_balance():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table = dynamodb.Table('TradingBot_Test_Account')
    
    timestamp = int(time.time() * 1000)
    
    # Reset to 10,000
    item = {
        'account_id': 'test_account',
        'timestamp': timestamp,
        'balance': Decimal("10000.00"),
        'total_fees': Decimal("0.00"),
        'updated_at': timestamp
    }
    
    print("Resetting Test Account Balance to $10,000...")
    table.put_item(Item=item)
    print("Reset Complete.")

if __name__ == "__main__":
    reset_test_balance()
