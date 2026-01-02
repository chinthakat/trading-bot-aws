
import boto3
import time
import uuid
import sys
import os
import json
from decimal import Decimal
from datetime import datetime

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

table_name = config['aws']['tables']['test_orders']
positions_table_name = config['aws']['tables']['test_positions']

dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-2')
orders_table = dynamodb.Table(table_name)
positions_table = dynamodb.Table(positions_table_name)

symbol = "BTC/USDT"
order_id = str(uuid.uuid4())
price = 100.0  # Very low price to ensure buy fill? No, simulator fills instant based on current price usually?
# Simulator logic:
# if side == 'buy' and current_price <= limit_price: fill
# Market price is ~90k. So a BUY at 90k should fill.
price = 95000.0 # Higher than market to ensure fill

print(f"Placing test manual order {order_id}...")

item = {
    'order_id': order_id,
    'symbol': symbol,
    'side': 'buy',
    'price': Decimal(str(price)),
    'amount': Decimal("0.001"),
    'status': 'pending',
    'created_at': int(time.time() * 1000),
    'expires_at': int((time.time() + 300) * 1000)
}

orders_table.put_item(Item=item)
print("Order placed in DynamoDB.")

print("Waiting 15s for bot to pick it up...")
time.sleep(15)

# Check position
response = positions_table.scan(FilterExpression="symbol = :s", ExpressionAttributeValues={":s": symbol})
items = response.get('Items', [])

if items:
    print(f"SUCCESS: Found {len(items)} positions for {symbol}:")
    for p in items:
        print(f" - {p['side']} {p['amount'] if 'amount' in p else p.get('quantity')} @ {p['entry_price']}")
else:
    print("FAILURE: No positions found.")
    
# Check logs for receipt
os.system("grep 'Discovered' trading-bot/nohup.out")
