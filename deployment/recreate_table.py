import boto3
import json
import os
import time

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def recreate_prices_table():
    config = load_config()
    region = config['aws']['region']
    table_name = config['aws']['tables']['prices']
    
    dynamodb = boto3.client('dynamodb', region_name=region)
    
    print(f"--- Recreating Table: {table_name} ---")
    
    # 1. Delete if exists
    try:
        dynamodb.delete_table(TableName=table_name)
        print(f"Deleting {table_name}...")
        
        # Wait for deletion
        waiter = dynamodb.get_waiter('table_not_exists')
        waiter.wait(TableName=table_name)
        print("Table deleted.")
    except dynamodb.exceptions.ResourceNotFoundException:
        print("Table did not exist.")
    except Exception as e:
        print(f"Error deleting table: {e}")
        return

    # 2. Create with new schema
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'symbol', 'KeyType': 'HASH'},    # Partition key
                {'AttributeName': 'timestamp', 'KeyType': 'RANGE'} # Sort key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'symbol', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'N'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )
        print("Table creation initiated...")
        
        # Wait for creation
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=table_name)
        print("✅ Limitless History Table Created (Symbol + Timestamp).")
        
    except Exception as e:
        print(f"Error creating table: {e}")

if __name__ == "__main__":
    recreate_prices_table()
