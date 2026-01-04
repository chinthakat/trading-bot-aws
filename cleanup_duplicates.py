
import boto3
import json
import os
from decimal import Decimal

def cleanup():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table = dynamodb.Table('TradingBot_Test_Positions')
    
    resp = table.scan()
    items = resp.get('Items', [])
    
    # Sort by entry_time descending (newest first)
    # Handle missing entry_time
    def get_time(x):
        return float(x.get('entry_time', 0))
        
    items.sort(key=get_time, reverse=True)
    
    print(f"Found {len(items)} positions.")
    
    if not items:
        return

    # Keep the first one (newest)
    newest = items[0]
    print(f"Keeping newest: {newest['position_id']} ({newest.get('entry_time')})")
    
    for item in items[1:]:
        pid = item['position_id']
        print(f"Deleting duplicate/stale: {pid} ({item.get('entry_time')})")
        table.delete_item(Key={'position_id': pid})
        
    print("Cleanup complete.")

if __name__ == "__main__":
    cleanup()
