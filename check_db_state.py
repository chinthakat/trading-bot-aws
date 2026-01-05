
import os
import sys
import json
import boto3
from decimal import Decimal

# Add app to path to import services
sys.path.append(os.getcwd())
from app.services.db_service import SharedDbService

# Custom Encoder
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def check_db_state():
    print("--- Database State Check ---")
    
    # 1. Check Shared DB (SQLite)
    print("\n[1] Checking Shared Memory (SQLite)...")
    try:
        db = SharedDbService()
        positions = db.get_active_positions()
        if positions:
            print(f"FOUND {len(positions)} ACTIVE POSITIONS in Shared DB:")
            print(json.dumps([dict(p) for p in positions], indent=2, cls=DecimalEncoder))
        else:
            print("Shared DB: No active positions found.")
    except Exception as e:
        print(f"Shared DB Error: {e}")

    # 2. Check DynamoDB
    print("\n[2] Checking DynamoDB...")
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            
        region = config['aws']['region']
        mode = config['trading'].get('mode', 'TEST')
        print(f"Mode: {mode}")
        
        dynamodb = boto3.resource('dynamodb', region_name=region)
        
        # Determine table name based on mode
        if mode == 'TEST':
            table_name = config['aws']['tables'].get('test_positions', 'TradingBot_Test_Positions')
        else:
            table_name = config['aws']['tables'].get('positions', 'TradingBot_Positions')
            
        print(f"Scanning Table: {table_name}")
        table = dynamodb.Table(table_name)
        
        resp = table.scan(
            FilterExpression='#st = :open OR #st = :req',
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={':open': 'open', ':req': 'request_close'}
        )
        items = resp.get('Items', [])
        
        if items:
            print(f"FOUND {len(items)} ACTIVE POSITIONS in DynamoDB:")
            print(json.dumps(items, indent=2, cls=DecimalEncoder))
        else:
            print("DynamoDB: No active positions found.")
            
    except Exception as e:
        print(f"DynamoDB Error: {e}")

if __name__ == "__main__":
    check_db_state()
