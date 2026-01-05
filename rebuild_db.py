
import boto3
import json
import time
import os
from botocore.exceptions import ClientError
from decimal import Decimal

# Load config
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    # Fallback to ../config.json
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)

region = config['aws']['region']
dynamodb = boto3.client('dynamodb', region_name=region)
dynamodb_res = boto3.resource('dynamodb', region_name=region)

tables_to_reset = [
    {
        'TableName': 'TradingBot_Test_Positions',
        'KeySchema': [{'AttributeName': 'position_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'position_id', 'AttributeType': 'S'}]
    },
    {
        'TableName': 'TradingBot_Test_Orders',
        'KeySchema': [{'AttributeName': 'order_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'order_id', 'AttributeType': 'S'}]
    },
    {
        'TableName': 'TradingBot_Test_Account',
        'KeySchema': [
            {'AttributeName': 'account_id', 'KeyType': 'HASH'},
            {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
        ],
        'AttributeDefinitions': [
            {'AttributeName': 'account_id', 'AttributeType': 'S'},
            {'AttributeName': 'timestamp', 'AttributeType': 'N'}
        ]
    }
]

def delete_table(table_name):
    try:
        print(f"Deleting {table_name}...")
        dynamodb.delete_table(TableName=table_name)
        waiter = dynamodb.get_waiter('table_not_exists')
        waiter.wait(TableName=table_name)
        print(f"Deleted {table_name}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            print(f"{table_name} does not exist.")
        else:
            print(f"Error deleting {table_name}: {e}")

def create_table(table_def):
    try:
        print(f"Creating {table_def['TableName']}...")
        dynamodb.create_table(
            TableName=table_def['TableName'],
            KeySchema=table_def['KeySchema'],
            AttributeDefinitions=table_def['AttributeDefinitions'],
            BillingMode='PAY_PER_REQUEST'
        )
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=table_def['TableName'])
        print(f"Created {table_def['TableName']}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceInUseException':
            print(f"{table_def['TableName']} already exists.")
        else:
            print(f"Error creating {table_def['TableName']}: {e}")

def seed_account():
    print("Seeding Test Account with $10,000...")
    table = dynamodb_res.Table('TradingBot_Test_Account')
    timestamp = int(time.time() * 1000)
    item = {
        'account_id': 'test_account',
        'timestamp': timestamp,
        'balance': Decimal("10000.00"),
        'equity': Decimal("10000.00"),
        'total_fees': Decimal("0.00"),
        'updated_at': timestamp
    }
    table.put_item(Item=item)
    print("Account Seeded.")

def rebuild():
    print("--- REBUILDING DATABASE ---")
    for t in tables_to_reset:
        delete_table(t['TableName'])
        
    # Wait a bit to ensure AWS consistency
    time.sleep(2)
    
    for t in tables_to_reset:
        create_table(t)
        
    seed_account()
    print("--- REBUILD COMPLETE ---")

if __name__ == "__main__":
    rebuild()
