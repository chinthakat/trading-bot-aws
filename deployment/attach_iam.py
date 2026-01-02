import boto3
import json
import time
import os

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

config = load_config()
REGION = config['aws']['region']

iam = boto3.client('iam')
ec2 = boto3.client('ec2', region_name=REGION)

ROLE_NAME = 'TradingBotRole'
PROFILE_NAME = 'TradingBotProfile'

def create_iam_role():
    print(f"Checking IAM Role: {ROLE_NAME}...")
    try:
        iam.get_role(RoleName=ROLE_NAME)
        print("Role exists.")
    except iam.exceptions.NoSuchEntityException:
        print("Creating Role...")
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }
            ]
        }
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
        # Attach DynamoDB Access
        print("Attaching DynamoDB Policy...")
        iam.attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn='arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess'
        )
        print("Role created.")

def create_instance_profile():
    print(f"Checking Instance Profile: {PROFILE_NAME}...")
    try:
        iam.get_instance_profile(InstanceProfileName=PROFILE_NAME)
        print("Instance Profile exists.")
    except iam.exceptions.NoSuchEntityException:
        print("Creating Instance Profile...")
        iam.create_instance_profile(InstanceProfileName=PROFILE_NAME)
        print("Instance Profile created.")
        
        # Add role to profile
        print("Adding Role to Profile...")
        iam.add_role_to_instance_profile(
            InstanceProfileName=PROFILE_NAME,
            RoleName=ROLE_NAME
        )
        # Wait for propagation
        print("Waiting for IAM propagation...")
        time.sleep(10)

def attach_to_instance():
    # Get Instance ID
    response = ec2.describe_instances(
        Filters=[
            {'Name': 'tag:Name', 'Values': ['TradingBot']},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )
    reservations = response.get('Reservations', [])
    if not reservations:
        print("No running TradingBot instance found.")
        return
    
    instance_id = reservations[0]['Instances'][0]['InstanceId']
    print(f"Found Instance: {instance_id}")
    
    # Check if already associated
    associations = ec2.describe_iam_instance_profile_associations(
        Filters=[{'Name': 'instance-id', 'Values': [instance_id]}]
    )
    
    if associations['IamInstanceProfileAssociations']:
        print("Instance already has an IAM profile associated.")
        # Ideally check if it's the right one, but for MVP we assume if present it's ok or handled manually
        return

    print("Associating Instance Profile...")
    try:
        # We need the ARN of the instance profile
        profile = iam.get_instance_profile(InstanceProfileName=PROFILE_NAME)
        profile_arn = profile['InstanceProfile']['Arn']
        
        ec2.associate_iam_instance_profile(
            IamInstanceProfile={'Arn': profile_arn},
            InstanceId=instance_id
        )
        print("Success! IAM Role attached.")
    except Exception as e:
        print(f"Failed to associate profile: {e}")

if __name__ == "__main__":
    create_iam_role()
    create_instance_profile()
    # Wait a bit more for eventual consistency
    time.sleep(5)
    attach_to_instance()
