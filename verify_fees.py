
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
    
    # 1. Inject Order
    order_id = str(uuid.uuid4())
    print(f"Injecting Order {order_id}...")
    
    # Buy @ 150,000 to guarantee fill (Market is ~91k)
    # Commission Rate is 0.001
    price = 150000.0
    amount = 0.001
    
    item = {
        'order_id': order_id,
        'symbol': 'BTC/USDT',
        'side': 'buy',
        'price': Decimal(str(price)),
        'amount': Decimal(str(amount)),
        'status': 'pending',
        'created_at': int(time.time() * 1000),
        'expires_at': int((time.time() + 300) * 1000),
        'type': 'entry'
    }
    orders_table.put_item(Item=item)
    
    print("Waiting for fill...")
    for _ in range(10):
        time.sleep(2)
        resp = orders_table.get_item(Key={'order_id': order_id})
        o = resp.get('Item')
        if o and o['status'] == 'filled':
            print("Order Filled!")
            # Check Order Commission
            comm = float(o.get('commission', 0))
            print(f"Order Commission: {comm}")
            
            # Check Position
            print("Checking Position...")
            # We don't know position_id easily but we can scan for open pos
            p_resp = positions_table.scan(FilterExpression="#st = :op", ExpressionAttributeNames={'#st':'status'}, ExpressionAttributeValues={':op':'open'})
            items = p_resp.get('Items', [])
            if items:
                pos = items[0]
                entry_comm = float(pos.get('entry_commission', 0))
                pnl = float(pos.get('pnl', 0))
                print(f"Position Entry Comm: {entry_comm}")
                print(f"Position Net PnL: {pnl}")
                
                if comm > 0 and abs(comm - entry_comm) < 0.0001:
                    print("SUCCESS: Commission verified.")
                else:
                    print("FAILURE: Commission mismatch or zero.")
            else:
                 print("FAILURE: No position found.")
            return

    print("Timeout waiting for fill.")

if __name__ == "__main__":
    verify()
