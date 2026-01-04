
import sys
import os
import json
import logging
sys.path.append('app')
from app.position_manager import PositionManager
from unittest.mock import MagicMock

# Setup Logging
logging.basicConfig(level=logging.INFO)

def verify_sizing():
    # Load Config
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    print(f"Config Risk Params: {config['trading'].get('risk_management')}")
    print(f"Config Risk Per Trade: {config['trading'].get('risk_per_trade')}")
    
    # Mock Exchange
    exchange = MagicMock()
    exchange.markets = {'BTC/USDT': {'limits': {'amount': {'min': 0.00001}}}}
    exchange.market.return_value = {'limits': {'amount': {'min': 0.00001}}}
    
    # Mock DB
    db = MagicMock()
    db.get_test_account_balance.return_value = {'balance': 10000.0}
    
    # Initialize PM with REAL config
    pm = PositionManager(exchange, db, config['trading'], mode="TEST")
    
    print(f"PM Configured: UseMin={pm.use_min_quantity}, Risk={pm.risk_per_trade}%, SL={pm.sl_pct}")
    
    # Calculate
    price = 90000.0
    qty = pm.calculate_position_size('BTC/USDT', price)
    
    print(f"Calculated Qty for Price {price}: {qty}")
    
    # Validation
    # Risk = 3% of 10k = 300
    # SL = 2% of 90k = 1800
    # Exp Qty = 300 / 1800 = 0.1666...
    # Cost = 0.166 * 90000 = 15000 (Exceeds 10k)
    # Cap = 10000 / 90000 * 0.99 = 0.11
    
    expected_cap = (10000.0 / price) * 0.99
    print(f"Expected Cap: {expected_cap}")
    
    if abs(qty - expected_cap) < 0.001:
        print("SUCCESS: Sizing matches expectation (Capped).")
    elif qty == 0.00001:
         print("FAILURE: Returned Minimum Quantity.")
    else:
         print(f"FAILURE: Unexpected Quantity {qty}")

if __name__ == "__main__":
    verify_sizing()
