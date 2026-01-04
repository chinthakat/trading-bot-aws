import boto3
import json
import os
import sys
from decimal import Decimal

# Helper to handle Decimal serialization
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

if __name__ == "__main__":
    config = load_config()
    region = config['aws']['region']
    tables = config['aws']['tables']
    
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(tables['test_audit'])
    
    print(f"Scanning {table.name}...")
    
    response = table.scan()
    items = response.get('Items', [])
    
    # Sort by timestamp desc
    items.sort(key=lambda x: x['timestamp'], reverse=True)
    
    print(f"Found {len(items)} logs. Showing top 10:")
    
    for item in items[:10]:
        print("---")
        # specific details
        print(f"Time: {item['timestamp']}")
        print(f"Action: {item['action']}")
        print(f"Cause: {item['cause']}")
        print(f"Details: {json.dumps(item['details'], cls=DecimalEncoder)}")
