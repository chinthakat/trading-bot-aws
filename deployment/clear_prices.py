import boto3
import json
import os
import sys

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def clear_prices():
    config = load_config()
    region = config['aws']['region']
    table_name = config['aws']['tables']['prices']
    
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    print(f"--- Clearing Table: {table_name} ---")
    
    # Handle pagination
    scan_kwargs = {}
    done = False
    start_key = None
    count = 0
    
    with table.batch_writer() as batch:
        while not done:
            if start_key:
                scan_kwargs['ExclusiveStartKey'] = start_key
            
            response = table.scan(**scan_kwargs)
            items = response.get('Items', [])
            
            for item in items:
                # Convert timestamp from Decimal to int/float if needed (though batch handles it)
                # But we must pass key exactly.
                key = {
                    'symbol': item['symbol'],
                    'timestamp': item['timestamp']
                }
                batch.delete_item(Key=key)
                count += 1
                
            start_key = response.get('LastEvaluatedKey', None)
            done = start_key is None
            
    print(f"✅ Table cleared. Deleted {count} items.")

if __name__ == "__main__":
    clear_prices()
