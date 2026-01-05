
import boto3
import json
import time

def clear_closed_positions():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table_name = 'TradingBot_Test_Positions' # Check persistence.py to confirm name or use config
    # persistence.py uses self.test_positions_table = dynamodb.Table('TradingBot_Test_Positions')
    
    table = dynamodb.Table(table_name)
    
    print(f"Scanning {table_name} for CLOSED positions to delete...")
    
    response = table.scan()
    items = response.get('Items', [])
    
    deleted_count = 0
    with table.batch_writer() as batch:
        for item in items:
            if item.get('status') == 'closed':
                batch.delete_item(Key={'position_id': item['position_id']})
                deleted_count += 1
                
    print(f"Deleted {deleted_count} closed positions.")
    print("Total PnL history should now be reset.")

if __name__ == "__main__":
    clear_closed_positions()
