
import boto3
import json
import time
from decimal import Decimal

def nuke_database():
    print("WARNING: This will wipe ALL Test Data (Positions, Orders, Account History).")
    time.sleep(2)
    
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    
    tables = [
        'TradingBot_Test_Positions',
        'TradingBot_Test_Orders',
        'TradingBot_Test_Account'
    ]
    
    for t_name in tables:
        table = dynamodb.Table(t_name)
        print(f"Scanning & Deleting Table: {t_name}...")
        
        # Scan all
        response = table.scan()
        items = response.get('Items', [])
        
        # Get Key Schema to know what to delete
        keys = [k['AttributeName'] for k in table.key_schema]
        
        with table.batch_writer() as batch:
            for item in items:
                key_dict = {k: item[k] for k in keys}
                batch.delete_item(Key=key_dict)
                
        print(f"Deleted {len(items)} items from {t_name}.")
        
    # Re-Seed Account
    print("Re-Seeding Test Account with $10,000...")
    acc_table = dynamodb.Table('TradingBot_Test_Account')
    timestamp = int(time.time() * 1000)
    item = {
        'account_id': 'test_account',
        'timestamp': timestamp,
        'balance': Decimal("10000.00"),
        'equity': Decimal("10000.00"), # Explicitly set Equity = Balance
        'total_fees': Decimal("0.00"),
        'updated_at': timestamp
    }
    acc_table.put_item(Item=item)
    print("Database Nuked and Reseeded.")

if __name__ == "__main__":
    nuke_database()
