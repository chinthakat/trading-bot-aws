import os
import sys
import boto3
import json

# Add app directory to path
sys.path.append(os.path.join(os.getcwd(), 'app'))

from persistence import DynamoManager

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

db = DynamoManager(config)

POS_ID = "f9a29142-5459-48d3-85e7-2fba713549f8" # The zombie request_close position

print(f"--- DELETING ZOMBIE POSITION {POS_ID} ---")
try:
    db.test_positions_table.delete_item(
        Key={'position_id': POS_ID}
    )
    print("Successfully deleted.")
except Exception as e:
    print(f"Error deleting: {e}")
