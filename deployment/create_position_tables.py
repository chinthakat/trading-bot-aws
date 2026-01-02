import boto3
import json
import os

# Load config
config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
with open(config_path, 'r') as f:
    config = json.load(f)

region = config['aws']['region']
dynamodb = boto3.client('dynamodb', region_name=region)

# Create Positions table
print("Creating Positions table...")
try:
    dynamodb.create_table(
        TableName='TradingBot_Positions',
        KeySchema=[
            {'AttributeName': 'position_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'position_id', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print("✓ Positions table created")
except dynamodb.exceptions.ResourceInUseException:
    print("✓ Positions table already exists")

# Create Orders table  
print("Creating Orders table...")
try:
    dynamodb.create_table(
        TableName='TradingBot_Orders',
        KeySchema=[
            {'AttributeName': 'order_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'order_id', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print("✓ Orders table created")
except dynamodb.exceptions.ResourceInUseException:
    print("✓ Orders table already exists")

print("\nAll tables ready!")
