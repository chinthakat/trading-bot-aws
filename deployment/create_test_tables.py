import boto3
import json
import os

# Load config
config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
with open(config_path, 'r') as f:
    config = json.load(f)

region = config['aws']['region']
dynamodb = boto3.client('dynamodb', region_name=region)

# Create Test Positions table
print("Creating Test Positions table...")
try:
    dynamodb.create_table(
        TableName='TradingBot_Test_Positions',
        KeySchema=[
            {'AttributeName': 'position_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'position_id', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print("✓ Test Positions table created")
except dynamodb.exceptions.ResourceInUseException:
    print("✓ Test Positions table already exists")

# Create Test Orders table  
print("Creating Test Orders table...")
try:
    dynamodb.create_table(
        TableName='TradingBot_Test_Orders',
        KeySchema=[
            {'AttributeName': 'order_id', 'KeyType': 'HASH'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'order_id', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print("✓ Test Orders table created")
except dynamodb.exceptions.ResourceInUseException:
    print("✓ Test Orders table already exists")

# Create Test Account table
print("Creating Test Account table...")
try:
    dynamodb.create_table(
        TableName='TradingBot_Test_Account',
        KeySchema=[
            {'AttributeName': 'account_id', 'KeyType': 'HASH'},
            {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'account_id', 'AttributeType': 'S'},
            {'AttributeName': 'timestamp', 'AttributeType': 'N'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )
    print("✓ Test Account table created")
except dynamodb.exceptions.ResourceInUseException:
    print("✓ Test Account table already exists")

print("\nAll test tables ready!")

