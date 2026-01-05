
import boto3
import json
from decimal import Decimal

region = 'ap-southeast-2'
dynamodb = boto3.resource('dynamodb', region_name=region)

def scan_table(name):
    print(f"\n--- Scanning {name} ---")
    table = dynamodb.Table(name)
    resp = table.scan()
    items = resp.get('Items', [])
    for item in items:
        # Simple dict print
        print({k: str(v) for k,v in item.items()})
    print(f"Total: {len(items)}")

scan_table('TradingBot_Test_Positions')
