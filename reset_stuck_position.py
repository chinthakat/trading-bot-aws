
import boto3
import json
import os
from decimal import Decimal

def reset_position():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table = dynamodb.Table('TradingBot_Test_Positions')
    
    # 1. Scan for closing
    resp = table.scan(FilterExpression='#st = :cl', ExpressionAttributeNames={'#st':'status'}, ExpressionAttributeValues={':cl':'closing'})
    
    items = resp.get('Items', [])
    print(f"Found {len(items)} stuck 'closing' positions.")
    
    for item in items:
        pid = item['position_id']
        print(f"Resetting {pid} to 'open'...")
        table.update_item(
            Key={'position_id': pid},
            UpdateExpression="set #st = :op",
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={':op': 'open'}
        )
        print("Done.")

if __name__ == "__main__":
    reset_position()
