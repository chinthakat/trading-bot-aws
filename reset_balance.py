
import boto3
import time
from decimal import Decimal

region = 'ap-southeast-2'
dynamodb = boto3.resource('dynamodb', region_name=region)

def reset_test_account():
    print("Resetting Test Account Balance to $10,000...")
    table = dynamodb.Table('TradingBot_Test_Account')
    
    # Insert new record with current timestamp
    timestamp = int(time.time() * 1000)
    item = {
        'account_id': 'test_account',
        'timestamp': timestamp,
        'balance': Decimal("10000.00"),
        'equity': Decimal("10000.00"),
        'total_fees': Decimal("0.00"),
        'updated_at': timestamp
    }
    table.put_item(Item=item)
    print(f"✓ Account Reset at {timestamp}")

if __name__ == "__main__":
    reset_test_account()
