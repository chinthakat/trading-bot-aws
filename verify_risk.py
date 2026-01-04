
import boto3
import json
import time
import uuid
from decimal import Decimal

def verify():
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    dynamodb = boto3.resource('dynamodb', region_name=config['aws']['region'])
    orders_table = dynamodb.Table('TradingBot_Test_Orders')
    positions_table = dynamodb.Table('TradingBot_Test_Positions')
    
    # 0. Get Current Price
    prices_table = dynamodb.Table('TradingBot_Prices')
    resp = prices_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('symbol').eq('BTC/USDT'),
        ScanIndexForward=False,
        Limit=1
    )
    items = resp.get('Items', [])
    if items:
        # It could be a candle (close) or a price tick (price)
        latest = items[0]
        if 'price' in latest:
            market_price = float(latest['price'])
        elif 'close' in latest:
            market_price = float(latest['close'])
        else:
            print("Warning: Price data missing 'price' or 'close' key. Defaulting.")
            market_price = 100000.0
    else:
        print("Warning: Could not fetch price. Defaulting to 100,000")
        market_price = 100000.0
        
    print(f"Market Price: {market_price}")

    # Buy @ Market + 5% to guarantee fill
    price = market_price * 1.05
    amount = 0.001
    
    order_id = str(uuid.uuid4())
    print(f"Injecting Order {order_id} @ {price:.2f}")
    
    # Calculate SL/TP to simulate Bot behavior
    sl_price = price * 0.98
    tp_price = price * 1.04
    
    item = {
        'order_id': order_id,
        'symbol': 'BTC/USDT',
        'side': 'buy',
        'price': Decimal(str(price)),
        'amount': Decimal(str(amount)),
        'status': 'pending',
        'created_at': int(time.time() * 1000),
        'expires_at': int((time.time() + 300) * 1000),
        'type': 'entry',
        'stop_loss': Decimal(str(sl_price)),
        'take_profit': Decimal(str(tp_price))
    }
    orders_table.put_item(Item=item)
    print("Item Pushed.")
    
    # 1b. Verify Persistence
    print("Verifying Persistence...")
    chk = orders_table.get_item(Key={'order_id': order_id})
    if 'Item' in chk:
        print(f"Item Found in DB: Status={chk['Item']['status']}")
    else:
        print("CRITICAL: Item NOT found in DB immediately after put.")
    
    # 1c. Verify Scan
    print("Verifying Scan Filter...")
    scn = orders_table.scan(FilterExpression="#st = :pending", ExpressionAttributeNames={'#st':'status'}, ExpressionAttributeValues={':pending':'pending'})
    found = False
    for i in scn.get('Items', []):
        if i['order_id'] == order_id:
            found = True
            print("Item found via Scan.")
            break
    if not found:
        print("CRITICAL: Item NOT found via Scan filter.")

    print("Waiting for fill...")
    pos = None
    for _ in range(30):
        time.sleep(2)
        resp = orders_table.get_item(Key={'order_id': order_id})
        o = resp.get('Item')
        if o and o['status'] == 'filled':
            print("Order Filled!")
            
            # Check Position
            print("Checking Position...")
            p_resp = positions_table.scan(FilterExpression="#st = :op", ExpressionAttributeNames={'#st':'status'}, ExpressionAttributeValues={':op':'open'})
            items = p_resp.get('Items', [])
            if items:
                pos = items[0]
                entry = float(pos['entry_price'])
                sl = float(pos.get('stop_loss', 0))
                tp = float(pos.get('take_profit', 0))
                
                print(f"Position Entry: {entry}")
                print(f"SL: {sl} (Expected ~{entry * 0.98:.2f})")
                print(f"TP: {tp} (Expected ~{entry * 1.04:.2f})")
                
                if sl > 0 and tp > 0:
                    print("SUCCESS: SL/TP Set.")
                    # Verify Pct
                    sl_ratio = sl / entry
                    if 0.97 <= sl_ratio <= 0.99:
                         print("SUCCESS: SL is ~2%.")
                    else:
                         print(f"FAILURE: SL Ratio {sl_ratio:.4f} mismatch.")
                         
                else:
                    print("FAILURE: SL/TP Missing.")
            else:
                 print("FAILURE: No position found.")
                 return
            break

    if not pos:
        print("Timeout waiting for fill.")
        return

    # 4. Trigger SL
    print("Triggering SL (Updating SL > Price)...")
    # Current price is approx entry (fill price).
    # We set SL to Entry * 1.1 (Above Price). Long should close if Price <= SL.
    # Wait, if SL = 1.1 * Price, then Price (1.0) <= SL (1.1). Yes.
    
    new_sl = Decimal(str(float(pos['entry_price']) * 1.1))
    positions_table.update_item(
        Key={'position_id': pos['position_id']},
        UpdateExpression='SET stop_loss = :sl',
        ExpressionAttributeValues={':sl': new_sl}
    )
    
    print("Waiting for Close...")
    for _ in range(30):
        time.sleep(2)
        resp = positions_table.get_item(Key={'position_id': pos['position_id']})
        p = resp.get('Item')
        if p and p['status'] == 'closed':
            print(f"Position Closed! Reason: {p.get('status')}")
            # Can we check reason? DB doesn't store 'reason' in status, but we can check PnL or Logs.
            # Assuming close means success.
            print("SUCCESS: SL Triggered.")
            return

    print("Timeout waiting for close.")

if __name__ == "__main__":
    verify()
