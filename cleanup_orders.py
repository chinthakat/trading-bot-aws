import os
import sys
import boto3
import json

# Add app directory to path
sys.path.append(os.path.join(os.getcwd(), 'app'))

from persistence import DynamoManager

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

db = DynamoManager(config)

print("--- CANCELING ALL PENDING TEST ORDERS ---")
try:
    # 1. Scan for pending
    response = db.test_orders_table.scan(
        FilterExpression='#st = :pending',
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':pending': 'pending'}
    )
    orders = response.get('Items', [])
    
    if not orders:
        print("No pending orders found.")
    else:
        print(f"Found {len(orders)} pending orders. Canceling...")
        for order in orders:
            order_id = order['order_id']
            symbol = order['symbol']
            price = order['price']
            print(f"Canceling {order_id} ({symbol} @ {price})")
            
            # Update status to canceled
            db.update_order_status(order_id, 'canceled', mode="TEST")
            
        print("--- Done ---")

except Exception as e:
    print(f"Error: {e}")
