
import boto3
import json
import sys

def delete_position(position_id):
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    table = dynamodb.Table('TradingBot_Test_Positions')
    
    print(f"Deleting Position: {position_id}...")
    table.delete_item(
        Key={'position_id': position_id}
    )
    print("Deleted.")

if __name__ == "__main__":
    # Position ID from previous check_db_state output
    delete_position("96ea3964-1255-4079-b99f-de2d47c319d6")
