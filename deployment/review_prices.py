import boto3
import json
import os
from decimal import Decimal
from datetime import datetime

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def get_table(name, config, dynamodb):
    return dynamodb.Table(config['aws']['tables'][name])

if __name__ == "__main__":
    config = load_config()
    region = config['aws']['region']
    dynamodb = boto3.resource('dynamodb', region_name=region)
    
    signals_table = get_table('signals', config, dynamodb)
    orders_table = get_table('test_orders', config, dynamodb)
    pos_table = get_table('test_positions', config, dynamodb)
    
    print("Scanning Signals...")
    signals = signals_table.scan().get('Items', [])
    print(f"Scanning Orders: {orders_table.name}...")
    orders = orders_table.scan().get('Items', [])
    print(f"Scanning Positions: {pos_table.name}...")
    positions = pos_table.scan().get('Items', [])
    
    # Sort
    signals.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
    
    print(f"\n--- PRICE ANALYSIS REPORT ({len(signals)} Signals) ---")
    print(f"{'TIME':<20} | {'SYMBOL':<8} | {'ACTION':<6} | {'SIGNAL $':<10} | {'LIMIT $':<10} | {'FILL $':<10} | {'DELTA %':<8}")
    print("-" * 90)
    
    for sig in signals[:15]: 
        ts = float(sig.get('timestamp', 0))
        symbol = sig.get('symbol')
        sig_price = float(sig.get('price', 0)) # Assuming 'price' field exists
        action = sig.get('signal', 'UNK')
        
        # Match Order (timestamp within 5s)
        matched_order = None
        for o in orders:
             # created_at might be int (ms) or float
             o_ts = float(o.get('created_at', 0))
             if abs(o_ts - ts) < 5000:
                 matched_order = o
                 break
                 
        limit_price = 0
        if matched_order:
             limit_price = float(matched_order.get('price', 0))
             
        # Match Position
        matched_pos = None
        for p in positions:
             p_ts = float(p.get('entry_time', 0))
             if abs(p_ts - ts) < 10000:
                 matched_pos = p
                 break
                 
        fill_price = 0
        if matched_pos:
             fill_price = float(matched_pos.get('entry_price', 0))
             
        delta = 0
        if sig_price > 0 and fill_price > 0:
            delta = ((fill_price - sig_price) / sig_price) * 100
            
        ts_str = datetime.fromtimestamp(ts/1000).strftime('%H:%M:%S')
        print(f"{ts_str:<20} | {symbol:<8} | {action:<6} | {sig_price:<10.2f} | {limit_price:<10.2f} | {fill_price:<10.2f} | {delta:>7.4f}%")

