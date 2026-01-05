
import boto3
import time
from botocore.exceptions import ClientError
from decimal import Decimal

region = 'ap-southeast-2'
dynamodb = boto3.client('dynamodb', region_name=region)
dynamodb_res = boto3.resource('dynamodb', region_name=region)

def ensure_table(table_def):
    table_name = table_def['TableName']
    try:
        dynamodb.describe_table(TableName=table_name)
        print(f"✓ {table_name} exists.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            print(f"Creating {table_name}...")
            dynamodb.create_table(
                TableName=table_name,
                KeySchema=table_def['KeySchema'],
                AttributeDefinitions=table_def['AttributeDefinitions'],
                BillingMode='PAY_PER_REQUEST'
            )
            print(f"Waiting for {table_name} to be active...")
            waiter = dynamodb.get_waiter('table_exists')
            waiter.wait(TableName=table_name)
            print(f"✓ {table_name} created.")
        else:
            print(f"Error checking {table_name}: {e}")

def seed_account():
    print("Seeding Test Account...")
    table = dynamodb_res.Table('TradingBot_Test_Account')
    # Check if Item exists
    try:
        resp = table.get_item(Key={'account_id': 'test_account', 'timestamp': 0}) 
        # timestamp key is Range. We insert a new one mostly.
        # Just put a new item
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
        print("✓ Account Seeded ($10,000).")
    except Exception as e:
        print(f"Error seeding account: {e}")

definitions = [
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
    },
    {
        'TableName': 'TradingBot_Test_Positions',
        'KeySchema': [{'AttributeName': 'position_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'position_id', 'AttributeType': 'S'}]
    },
    {
        'TableName': 'TradingBot_Test_Orders',
        'KeySchema': [{'AttributeName': 'order_id', 'KeyType': 'HASH'}],
        'AttributeDefinitions': [{'AttributeName': 'order_id', 'AttributeType': 'S'}]
    }
]

if __name__ == "__main__":
    print("--- FIXING TABLES ---")
    for d in definitions:
        ensure_table(d)
    seed_account()
    print("--- DONE ---")
