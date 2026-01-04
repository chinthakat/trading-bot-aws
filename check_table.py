
import boto3
import json
from decimal import Decimal

# Custom Encoder for Decimal
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def check_table():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table = dynamodb.Table('TradingBot_Test_Positions')
    
    print("Scanning TradingBot_Test_Positions...")
    resp = table.scan()
    items = resp.get('Items', [])
    print(f"Items Found: {len(items)}")
    for i in items:
        print(json.dumps(i, cls=DecimalEncoder, indent=2))

if __name__ == "__main__":
    check_table()
