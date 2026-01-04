
import boto3
import json
import os
from decimal import Decimal

# Helper for Decimal serialization
def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError

def check_status():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table = dynamodb.Table('TradingBot_Test_Positions')
    
    print("Scannning TradingBot_Test_Positions...")
    resp = table.scan()
    for item in resp.get('Items', []):
        print(f"PosID: {item.get('position_id')} | Symbol: {item.get('symbol')} | Status: {item.get('status')}")

if __name__ == "__main__":
    check_status()
