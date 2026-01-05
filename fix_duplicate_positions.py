
import boto3
import json
from decimal import Decimal
import time
from boto3.dynamodb.conditions import Attr

def fix_duplicates():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table_name = 'TradingBot_Test_Positions' # Hardcoded for TEST as per user context
    table = dynamodb.Table(table_name)
    
    # scan for open positions
    response = table.scan(
        FilterExpression=Attr('status').eq('open') | Attr('status').eq('request_close')
    )
    items = response.get('Items', [])
    print(f"Found {len(items)} open/request_close positions.")
    
    # Group by Symbol
    by_symbol = {}
    for item in items:
        sym = item['symbol']
        if sym not in by_symbol: by_symbol[sym] = []
        by_symbol[sym].append(item)
        
    for sym, pos_list in by_symbol.items():
        if len(pos_list) > 1:
            print(f"Found {len(pos_list)} duplicates for {sym}. Cleaning up...")
            # Sort by entry_time descending (newest first)
            # entry_time is Decimal in DB
            pos_list.sort(key=lambda x: float(x.get('entry_time', 0)), reverse=True)
            
            # Keep the newest one
            keep = pos_list[0]
            to_remove = pos_list[1:]
            
            print(f"Keeping Position ID: {keep['position_id']} (Time: {keep['entry_time']})")
            
            for p in to_remove:
                pid = p['position_id']
                print(f"Closing Duplicate: {pid}")
                # Mark as closed in DB
                table.update_item(
                    Key={'position_id': pid},
                    UpdateExpression="set #st = :val, exit_reason = :r",
                    ExpressionAttributeNames={'#st': 'status'},
                    ExpressionAttributeValues={':val': 'closed', ':r': 'dedup_cleanup'}
                )
    
    print("Cleanup Complete.")

if __name__ == "__main__":
    fix_duplicates()
