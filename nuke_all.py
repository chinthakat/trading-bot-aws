
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
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)

region = config['aws']['region']
dynamodb = boto3.client('dynamodb', region_name=region)
dynamodb_res = boto3.resource('dynamodb', region_name=region)

tables_map = config['aws']['tables']
# Exclude Prices
EXCLUDED = [tables_map['prices']]

def nuke_and_recreate():
    print("--- NUKING DATABASE (Except Prices) ---")
    
    schemas = {}
    
    # 1. Capture Schemas
    for key, table_name in tables_map.items():
        if table_name in EXCLUDED:
            print(f"Skipping {table_name} (Preserved)...")
            continue
            
        try:
            resp = dynamodb.describe_table(TableName=table_name)
            table_desc = resp['Table']
            schemas[table_name] = {
                'KeySchema': table_desc['KeySchema'],
                'AttributeDefinitions': table_desc['AttributeDefinitions'],
                'BillingMode': 'PAY_PER_REQUEST' 
                # Note: We assume On-Demand. If Provisioned, we switch to On-Demand for simplicity/cost.
            }
            print(f"Captured schema for {table_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"Table {table_name} not found, cannot capture schema (will skip recreation if not manual).")
            else:
                print(f"Error describing {table_name}: {e}")

    # 2. Delete Tables
    for table_name in schemas.keys():
        try:
            print(f"Deleting {table_name}...")
            dynamodb.delete_table(TableName=table_name)
        except ClientError as e:
            print(f"Error deleting {table_name}: {e}")
            
    # 3. Wait for Deletion
    print("Waiting for deletion...")
    waiter = dynamodb.get_waiter('table_not_exists')
    for table_name in schemas.keys():
        try:
            waiter.wait(TableName=table_name)
            print(f"✓ {table_name} deleted.")
        except:
             print(f"Timeout waiting for {table_name} deletion")

    # 4. Recreate Tables
    print("Recreating tables...")
    create_waiter = dynamodb.get_waiter('table_exists')
    
    for table_name, schema in schemas.items():
        try:
            print(f"Creating {table_name}...")
            dynamodb.create_table(
                TableName=table_name,
                KeySchema=schema['KeySchema'],
                AttributeDefinitions=schema['AttributeDefinitions'],
                BillingMode=schema['BillingMode']
            )
        except ClientError as e:
             if e.response['Error']['Code'] == 'ResourceInUseException':
                 print(f"{table_name} already exists.")
             else:
                 print(f"Error creating {table_name}: {e}")

    # 5. Wait for Creation
    for table_name in schemas.keys():
        try:
            create_waiter.wait(TableName=table_name)
            print(f"✓ {table_name} ready.")
        except:
            print(f"Timeout waiting for {table_name} creation")

    # 6. Seed Test Account
    print("Seeding Test Account with $10,000...")
    table = dynamodb_res.Table(tables_map['test_account'])
    timestamp = int(time.time() * 1000)
    item = {
        'account_id': 'test_account',
        'timestamp': timestamp,
        'balance': Decimal("10000.00"),
        'equity': Decimal("10000.00"),
        'total_fees': Decimal("0.00"),
        'updated_at': timestamp
    }
    try:
        table.put_item(Item=item)
        print("✓ Account Seeded.")
    except Exception as e:
        print(f"Error seeding account: {e}")

    print("--- NUKE COMPLETE ---")

if __name__ == "__main__":
    nuke_and_recreate()
