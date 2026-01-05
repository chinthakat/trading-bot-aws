
import os
import sys
import json
import boto3
import logging
from botocore.exceptions import ClientError

# Setup paths
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from services.db_service import SharedDbService

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PatchHistory")

TARGET_STRATEGY = "MA_Crossover"

def load_config():
    # Load config relative to this script
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config.json')
    if not os.path.exists(config_path):
        config_path = 'config.json' # Fallback
    with open(config_path, 'r') as f:
        return json.load(f)

def patch_sqlite():
    logger.info("--- Patching SQLite (Shared DB) ---")
    try:
        db = SharedDbService()
        
        # Check current count
        cursor = db.conn.execute("SELECT count(*) FROM positions WHERE strategy_name IS NULL OR strategy_name = 'manual' OR strategy_name = ''")
        count = cursor.fetchone()[0]
        logger.info(f"Found {count} positions to patch in SQLite.")
        
        if count > 0:
            db.conn.execute("UPDATE positions SET strategy_name = ? WHERE strategy_name IS NULL OR strategy_name = 'manual' OR strategy_name = ''", (TARGET_STRATEGY,))
            db.conn.commit()
            logger.info("SQLite patch successful.")
        else:
            logger.info("No SQLite positions needed patching.")
            
    except Exception as e:
        logger.error(f"SQLite Patch Error: {e}")

def patch_dynamodb(config):
    logger.info("--- Patching DynamoDB ---")
    region = config['aws']['region']
    mode = config['trading'].get('mode', 'TEST')
    
    if mode == 'TEST':
        table_name = config['aws']['tables'].get('test_positions', 'TradingBot_Test_Positions')
    else:
        table_name = config['aws']['tables'].get('positions', 'TradingBot_Positions')
        
    logger.info(f"Targeting Table: {table_name} (Mode: {mode})")
    
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)
    
    try:
        # Scan for items to update
        # We can't easily filter for "attribute_not_exists" in Scan Filter *efficiently* without scanning all, 
        # but for this size it's fine.
        response = table.scan()
        items = response.get('Items', [])
        
        updated_count = 0
        for item in items:
            pid = item['position_id']
            strat = item.get('strategy_name')
            
            if not strat or strat == 'manual':
                logger.info(f"Patching Position {pid} (Current: {strat}) -> {TARGET_STRATEGY}")
                
                table.update_item(
                    Key={'position_id': pid},
                    UpdateExpression="SET strategy_name = :s",
                    ExpressionAttributeValues={':s': TARGET_STRATEGY}
                )
                updated_count += 1
                
        logger.info(f"DynamoDB Patch Complete. Updated {updated_count} items.")
        
    except ClientError as e:
        logger.error(f"DynamoDB Patch Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected Error: {e}")

if __name__ == "__main__":
    config = load_config()
    patch_sqlite()
    patch_dynamodb(config)
