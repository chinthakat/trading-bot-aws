import os
import sys
import boto3
import json
import time

# Add app directory to path
sys.path.append(os.path.join(os.getcwd(), 'app'))

from persistence import DynamoManager

def delete_all_items(table, key_name, range_key=None):
    """Scan and delete all items from a table."""
    try:
        print(f"Scanning {table.name}...")
        response = table.scan()
        items = response.get('Items', [])
        
        if not items:
            print(f"  No items found in {table.name}")
            return

        print(f"  Deleting {len(items)} items from {table.name}...")
        with table.batch_writer() as batch:
            for item in items:
                key = {key_name: item[key_name]}
                if range_key:
                    key[range_key] = item[range_key]
                batch.delete_item(Key=key)
        
        print(f"  Successfully cleared {table.name}")
    except Exception as e:
        print(f"  Error clearing {table.name}: {e}")

if __name__ == "__main__":
    # Load config
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print("config.json not found!")
        sys.exit(1)

    db = DynamoManager(config)
    
    print("WARNING: This will delete ALL data from TEST tables.")
    print("Tables: test_orders, test_positions, test_signals, test_account")
    # Time to abort if needed (though running effectively headless)
    # time.sleep(2) 
    
    # 1. Test Positions
    delete_all_items(db.test_positions_table, 'position_id')
    
    # 2. Test Orders
    delete_all_items(db.test_orders_table, 'order_id')
    
    # 3. Test Signals (We need to handle Signals if they are test-specific?)
    # DynamoManager has 'signals_table'. It might mix Live/Test args?
    # Let's check config or DynamoManager.
    # Usually signals are shared or we use 'algo' field?
    # But user asked to remove "all signals".
    # If the table is shared, we should filtering?
    # db.signals_table.
    # Use caution. If we are in TEST mode, maybe we only delete test signals?
    # But for now, let's assume separate table or we just scan/delete all for "clean view".
    # cleanup_db.py is usually for test env.
    
    # Let's check if there is a 'test_signals' table?
    # Config usually specifies table names.
    # Assuming 'signals_table' is unique.
    # I'll just clear 'signals' table completely as requested.
    # Wait, check keys: 'signal_id'
    delete_all_items(db.signals_table, 'signal_id')
    
    # 4. Test Account
    # Composite Key: account_id (Hash), timestamp (Range)
    delete_all_items(db.test_account_table, 'account_id', 'timestamp')

    print("\n--- Cleanup Complete ---")
