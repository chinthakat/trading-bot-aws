#!/usr/bin/env python3
"""Quick check of DynamoDB account state"""
import boto3
import json
from decimal import Decimal

with open('config.json') as f:
    config = json.load(f)

dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
table = dynamodb.Table(config['aws']['tables']['test_account'])

# Get latest 5 records
from boto3.dynamodb.conditions import Key
response = table.query(
    KeyConditionExpression=Key('account_id').eq('test_account'),
    ScanIndexForward=False,
    Limit=5
)

print("Latest 5 Account Records:")
for item in response['Items']:
    print(f"\nTimestamp: {item.get('timestamp')}")
    print(f"  Balance: {item.get('balance')}")
    print(f"  Equity: {item.get('equity')}")  
    print(f"  Fees: {item.get('total_fees')}")
