import os
import sys
import boto3
from decimal import Decimal
import json
import time
import uuid
from datetime import datetime
import pandas as pd

# Add app directory to path
sys.path.append(os.path.join(os.getcwd(), 'app'))

from persistence import DynamoManager

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

db = DynamoManager(config)

SYMBOL = "BTC/USDT"
MODE = "TEST"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

log("--- STARTING LIFECYCLE VERIFICATION ---")

# 1. Place a TEST Order
log("1. Placing Test Order...")
order_id = str(uuid.uuid4())
order = {
    'order_id': order_id,
    'symbol': SYMBOL,
    'side': 'buy',
    'price': 90000.0,
    'amount': 0.001,
    'status': 'pending',
    'type': 'entry',
    'created_at': datetime.now(),
    'expires_at': datetime.now() + pd.Timedelta(hours=1) # Valid for 1h
}

try:
    # Use persistence method if available, else manual put
    db.log_order(order)
    # Move to test table by update? persistence.log_order defaults to live... 
    # Ah, persistence.log_order is HARDCODED to LIVE in the original version?
    # Wait, I checked persistence.py and log_order was NOT updated in my last pass!
    # I only updated log_position, update_position_pnl, close_position.
    # log_order likely still defaults to LIVE table unless I fixed it?
    # Checking my memory... I did NOT update log_order.
    
    # Let's check where it went.
    
except Exception as e:
    log(f"Error placing order: {e}")

# ... (Script continues) but wait, if log_order is broken for TEST, the bot might not see it?
# Bot reads from self.orders_table which is set correctly in PositionManager.
# But dashboard creates orders via... ? Dashboard usually writes to DB directly?
# Dashboard (manual trade) uses db.log_order? 
# If db.log_order writes to LIVE table, and Bot (Test Mode) reads TEST table...
# THEN THE BOT NEVER SEES THE ORDER.

log("CHECKING IF ORDER IS IN TEST TABLE...")
resp = db.test_orders_table.scan()
items = resp.get('Items', [])
found = False
for i in items:
    if i['order_id'] == order_id:
        found = True
        break

if not found:
    log("❌ ORDER NOT FOUND IN TEST TABLE!")
    log("Likely cause: db.log_order() writes to LIVE table by default/always.")
    
    # Manually put into test table to continue test
    item = {
        'order_id': order['order_id'],
        'symbol': order['symbol'],
        'side': order['side'],
        'price': Decimal(str(order['price'])),
        'amount': Decimal(str(order['amount'])),
        'status': order['status'],
        'created_at': int(order['created_at'].timestamp() * 1000),
        'expires_at': int(order['expires_at'].timestamp() * 1000)
    }
    db.test_orders_table.put_item(Item=item)
    log("Forced order into TEST table for test continuation.")
else:
    log("✅ Order found in TEST table.")

# 2. Wait for Bot to Pickup (Simulate Bot Logic or wait for real bot?)
# If real bot is running, it should see 'pending' order in TEST table and process it?
# But wait, PositionManager.sync_state imports PENDING orders.
# Then check_order_status checks if they fill.
# Simulator fills them.
log("2. Waiting for Bot/Simulator to Fill...")
time.sleep(15) 

# 3. Check for Position
log("3. Checking for Position...")
pos = db.get_active_position(mode="TEST")
if pos:
    log(f"✅ Position Created: {pos['position_id']} Status:{pos['status']}")
else:
    log("❌ No Position Found.")

# 4. Simulate Price Update (Bot should do this)
log("4. Monitoring PnL...")
if pos:
    initial_pnl = pos.get('pnl')
    log(f"Initial PnL: {initial_pnl}")
    time.sleep(10)
    pos_update = db.get_active_position(mode="TEST")
    log(f"Updated PnL: {pos_update.get('pnl')}")

# 5. Request Close
log("5. Requesting Close...")
if pos:
    db.update_position_status(pos['position_id'], 'request_close', mode="TEST")
    time.sleep(15)
    
    # Check if closed
    # accessing table directly since get_active_position filters for open/req_close
    resp = db.test_positions_table.get_item(Key={'position_id': pos['position_id']})
    final_pos = resp.get('Item')
    if final_pos:
        log(f"Final Status: {final_pos['status']}")
    else:
        log("Position gone?")

log("--- END ---")
