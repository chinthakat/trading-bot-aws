import boto3
import json
import os
import time

# Load Config (to get table names)
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

config = load_config()
REGION = config['aws']['region'] # Currently us-east-1
TABLES = config['aws']['tables']

ec2 = boto3.client('ec2', region_name=REGION)
dynamodb = boto3.client('dynamodb', region_name=REGION)

def terminate_instance():
    print("--- Terminating EC2 Instance ---")
    response = ec2.describe_instances(
        Filters=[
            {'Name': 'tag:Name', 'Values': ['TradingBot']},
            {'Name': 'instance-state-name', 'Values': ['running', 'pending', 'stopped', 'stopping']}
        ]
    )
    
    instance_ids = []
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_ids.append(instance['InstanceId'])
            
    if instance_ids:
        print(f"Terminating instances: {instance_ids}")
        ec2.terminate_instances(InstanceIds=instance_ids)
        print("Waiting for termination...")
        waiter = ec2.get_waiter('instance_terminated')
        waiter.wait(InstanceIds=instance_ids)
        print("Instances terminated.")
    else:
        print("No active 'TradingBot' instances found.")

def delete_security_group():
    print("--- Deleting Security Group ---")
    sg_name = 'TradingBotSG'
    try:
        ec2.delete_security_group(GroupName=sg_name)
        print(f"Deleted Security Group: {sg_name}")
    except Exception as e:
        print(f"Could not delete Security Group {sg_name}: {e}")

def delete_key_pair():
    print("--- Deleting Key Pair ---")
    key_name = 'TradingBotKey'
    try:
        ec2.delete_key_pair(KeyName=key_name)
        print(f"Deleted Key Pair: {key_name}")
    except Exception as e:
        print(f"Error deleting key pair {key_name}: {e}")
        
    # Delete local file
    local_key = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TradingBotKey.pem')
    if os.path.exists(local_key):
        try:
            os.remove(local_key)
            print(f"Deleted local file: {local_key}")
        except Exception as e:
            print(f"Could not delete local file: {e}")

def delete_dynamodb_tables():
    print("--- Deleting DynamoDB Tables ---")
    # Note: We only delete the tables defined in our config to avoid accidents
    for key, table_name in TABLES.items():
        try:
            dynamodb.delete_table(TableName=table_name)
            print(f"Deleting table: {table_name}")
        except dynamodb.exceptions.ResourceNotFoundException:
            print(f"Table {table_name} not found.")
        except Exception as e:
            print(f"Error deleting {table_name}: {e}")

if __name__ == "__main__":
    print(f"TEARDOWN STARTED for Region: {REGION}")
    terminate_instance()
    # Wait a bit for dependencies to clear (SG might be attached if instance not full gone, but waiter should handle it)
    time.sleep(5)
    delete_security_group()
    delete_key_pair()
    delete_dynamodb_tables()
    print("TEARDOWN COMPLETE.")
