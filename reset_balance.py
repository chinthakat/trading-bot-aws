
import boto3
import time
import json
from decimal import Decimal
import os
import sys

# Add app to path to access persistence if needed, but we can just use Boto3 directly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def reset_test_account():
    dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-2')
    
    # 1. Reset Balance
    print("Resetting Balance...")
    account_table = dynamodb.Table('TradingBot_Test_Account')
    timestamp = int(time.time() * 1000)
    account_table.put_item(
        Item={
            'account_id': 'test_account',
            'balance': Decimal('10000.0'),
            'updated_at': timestamp,
            'timestamp': timestamp,
            'equity': Decimal('10000.0'),
            'pnl': Decimal('0.0')
        }
    )
    print("Balance reset to $10,000")

    # 2. Clear Test Positions
    print("Clearing Open Test Positions...")
    pos_table = dynamodb.Table('TradingBot_Test_Positions')
    scan = pos_table.scan(
        FilterExpression="#st = :open OR #st = :req",
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':open': 'open', ':req': 'request_close'}
    )
    with pos_table.batch_writer() as batch:
        for item in scan.get('Items', []):
            # We can either delete or mark closed. Deleting for clean slate.
            batch.delete_item(Key={'position_id': item['position_id']})
            print(f"Deleted position {item['position_id']}")

    # 3. Clear Pending Test Orders
    print("Clearing Pending Test Orders...")
    ord_table = dynamodb.Table('TradingBot_Test_Orders')
    scan_ord = ord_table.scan(
        FilterExpression="#st = :pending",
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':pending': 'pending'}
    )
    with ord_table.batch_writer() as batch:
        for item in scan_ord.get('Items', []):
            batch.delete_item(Key={'order_id': item['order_id']})
            print(f"Deleted order {item['order_id']}")

    # 4. Clear Signals locally (Shared DB)? 
    # The Shared DB is in /dev/shm, assumes restart will clear it.
    # But if we don't restart, we should clear it. 
    # We will assume user restarts bot after this.

    print("Reset Complete.")

if __name__ == "__main__":
    reset_test_account()
