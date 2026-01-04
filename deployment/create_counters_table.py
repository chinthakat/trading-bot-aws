
import boto3
import json
import time

def create_counters_table():
    # Load config
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    table_name = config['aws']['tables']['counters'] # TradingBot_Counters
    region = config['aws']['region']
    
    dynamodb = boto3.client('dynamodb', region_name=region)
    
    print(f"Creating table {table_name} in {region}...")
    
    try:
        response = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {
                    'AttributeName': 'counter_name',
                    'KeyType': 'HASH'  # Partition key
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': 'counter_name',
                    'AttributeType': 'S'
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print("Table creation initiated:", response)
        
        print("Waiting for table to exist...")
        waiter = dynamodb.get_waiter('table_exists')
        waiter.wait(TableName=table_name)
        print(f"Table {table_name} is now ACTIVE.")
        
    except dynamodb.exceptions.ResourceInUseException:
        print(f"Table {table_name} already exists.")
    except Exception as e:
        print(f"Error creating table: {e}")

if __name__ == "__main__":
    create_counters_table()
