import boto3
import json
import os
from decimal import Decimal

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

# Helper for Decimal
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return json.JSONEncoder.default(self, obj)

def inspect():
    config = load_config()
    region = config['aws']['region']
    table_name = config['aws']['tables']['prices']
    
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    print(f"--- Inspecting Table: {table_name} ---")
    
    response = table.scan(Limit=5)
    items = response.get('Items', [])
    
    if not items:
        print("Table is EMPTY.")
    else:
        print(f"Found {len(items)} items. Showing first 2:")
        for i, item in enumerate(items[:2]):
            print(json.dumps(item, cls=DecimalEncoder, indent=2))
            
if __name__ == "__main__":
    inspect()
