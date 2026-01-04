import boto3
import time
import json
import os
import sys

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def create_table(dynamodb, table_name):
    try:
        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'log_id', 'KeyType': 'HASH'},  # Partition Key
                {'AttributeName': 'timestamp', 'KeyType': 'RANGE'} # Sort Key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'log_id', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'N'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print(f"Creating table {table_name}...")
        table.wait_until_exists()
        print(f"Table {table_name} created successfully.")
    except dynamodb.exceptions.ResourceInUseException:
        print(f"Table {table_name} already exists.")
    except Exception as e:
        print(f"Error creating {table_name}: {e}")

if __name__ == "__main__":
    config = load_config()
    region = config['aws']['region']
    
    dynamodb = boto3.resource('dynamodb', region_name=region)
    
    tables = config['aws']['tables']
    
    # Create Live Table
    create_table(dynamodb, tables['audit'])
    
    # Create Test Table
    create_table(dynamodb, tables['test_audit'])
    
    print("Audit tables provisioning complete.")
