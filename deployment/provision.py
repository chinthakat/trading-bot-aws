import boto3
import json
import time
import os
import sys
import subprocess

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

config = load_config()
REGION = config['aws']['region']
TABLES = config['aws']['tables']

ec2 = boto3.client('ec2', region_name=REGION)
dynamodb = boto3.client('dynamodb', region_name=REGION)

def create_dynamodb_tables():
    print("--- Checking DynamoDB Tables ---")
    
    # Tables Definitions
    table_defs = {
        TABLES['trades']: {
            'KeySchema': [{'AttributeName': 'trade_id', 'KeyType': 'HASH'}],
            'AttributeDefinitions': [{'AttributeName': 'trade_id', 'AttributeType': 'S'}]
        },
        TABLES['stats']: {
            'KeySchema': [
                {'AttributeName': 'stat_type', 'KeyType': 'HASH'},
                {'AttributeName': 'algo', 'KeyType': 'RANGE'}
            ],
            'AttributeDefinitions': [
                {'AttributeName': 'stat_type', 'AttributeType': 'S'},
                {'AttributeName': 'algo', 'AttributeType': 'S'}
            ]
        },
        TABLES['prices']: {
            'KeySchema': [
                {'AttributeName': 'symbol', 'KeyType': 'HASH'},
                {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
            ],
            'AttributeDefinitions': [
                {'AttributeName': 'symbol', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'N'}
            ]
        },
        TABLES['signals']: {
            'KeySchema': [{'AttributeName': 'signal_id', 'KeyType': 'HASH'}],
            'AttributeDefinitions': [{'AttributeName': 'signal_id', 'AttributeType': 'S'}]
        }
    }
    
    existing_tables = dynamodb.list_tables()['TableNames']
    
    for table_name, schema in table_defs.items():
        if table_name in existing_tables:
            print(f"Table {table_name} already exists.")
        else:
            print(f"Creating table {table_name}...")
            dynamodb.create_table(
                TableName=table_name,
                KeySchema=schema['KeySchema'],
                AttributeDefinitions=schema['AttributeDefinitions'],
                BillingMode='PAY_PER_REQUEST'
            )
            print(f"Table {table_name} created.")

def create_security_group():
    print("--- Checking Security Group ---")
    sg_name = 'TradingBotSG'
    vpcs = ec2.describe_vpcs()
    vpc_id = vpcs['Vpcs'][0]['VpcId']
    
    try:
        response = ec2.describe_security_groups(GroupNames=[sg_name])
        sg_id = response['SecurityGroups'][0]['GroupId']
        print(f"Security Group {sg_name} ({sg_id}) already exists.")
        return sg_id
    except:
        print(f"Creating Security Group {sg_name}...")
        sg = ec2.create_security_group(GroupName=sg_name, Description='Trading Bot Security Group', VpcId=vpc_id)
        sg_id = sg['GroupId']
        
        # Inbound Rules
        # SSH
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                {'IpProtocol': 'tcp', 'FromPort': 8501, 'ToPort': 8501, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
            ]
        )
        print(f"Security Group created: {sg_id}")
        return sg_id

def launch_instance(sg_id):
    print("--- Launching EC2 Instance ---")
    
    # AMI: Amazon Linux 2023 for us-east-1 (x86_64)
    # Note: AMIs are region specific. This ID is for us-east-1 AL2023.
    # We should ideally fetch it dynamically.
    
    ami_response = ec2.describe_images(
        Owners=['amazon'],
        Filters=[
            {'Name': 'name', 'Values': ['al2023-ami-2023.*-x86_64']},
            {'Name': 'state', 'Values': ['available']}
        ]
    )
    # Sort by creation date
    images = sorted(ami_response['Images'], key=lambda x: x['CreationDate'], reverse=True)
    image_id = images[0]['ImageId']
    print(f"Using AMI: {image_id}")
    
    # Read User Data
    user_data_path = os.path.join(os.path.dirname(__file__), 'user_data.sh')
    with open(user_data_path, 'r') as f:
        user_data_script = f.read()
    
    # Check for Key Pair
    key_pairs = ec2.describe_key_pairs()
    # Filter for our specific key if it exists, or check generically if we want to force new one
    # Simpler: Check if TradingBotKey_AU exists
    try:
        kp_response = ec2.describe_key_pairs(KeyNames=['TradingBotKey_AU'])
        key_name = 'TradingBotKey_AU'
        print(f"Using Key Pair: {key_name}")
    except:
        print("Key Pair 'TradingBotKey_AU' not found. Creating...")
        try:
            key_pair = ec2.create_key_pair(KeyName='TradingBotKey_AU')
            key_material = key_pair['KeyMaterial']
            
            key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'TradingBotKey_AU.pem')
            with open(key_path, 'w') as f:
                f.write(key_material)
            
            print(f"Created Key Pair: TradingBotKey_AU")
            print(f"Saved private key to: {key_path}")
            print("IMPORTANT: Keep this key safe. You need it to SSH.")
            key_name = 'TradingBotKey_AU'
        except Exception as e:
            print(f"Error creating key pair: {e}")
            return
    
    instance = ec2.run_instances(
        ImageId=image_id,
        InstanceType='t3.micro',
        MinCount=1,
        MaxCount=1,
        KeyName=key_name,
        SecurityGroupIds=[sg_id],
        UserData=user_data_script,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [{'Key': 'Name', 'Value': 'TradingBot'}]
        }]
    )
    
    inst_id = instance['Instances'][0]['InstanceId']
    print(f"Instance launched! ID: {inst_id}")
    print("Waiting for public IP...")
    
    waiter = ec2.get_waiter('instance_running')
    waiter.wait(InstanceIds=[inst_id])
    
    inst_desc = ec2.describe_instances(InstanceIds=[inst_id])
    public_ip = inst_desc['Reservations'][0]['Instances'][0].get('PublicIpAddress')
    
    print("--- Deployment Complete ---")
    print(f"Public IP: {public_ip}")
    print(f"SSH Command: ssh -i {key_name}.pem ec2-user@{public_ip}")
    print("\nNEXT STEPS:")
    print(f"1. Upload code: scp -i {key_name}.pem -r app/ config.json requirements.txt ec2-user@{public_ip}:/home/ec2-user/trading-bot/")
    print(f"2. SSH in and run: pip3 install -r requirements.txt")
    print(f"3. Start services: sudo systemctl start trading-dashboard")

if __name__ == "__main__":
    create_dynamodb_tables()
    sg_id = create_security_group()
    launch_instance(sg_id)
