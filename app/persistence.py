import boto3
import time
import uuid
from botocore.exceptions import ClientError
from decimal import Decimal
from datetime import datetime
import math

class DynamoManager:
    def __init__(self, config):
        self.config = config
        self.region = config['aws']['region']
        self.table_names = config['aws']['tables']
        
        # Initialize Boto3 resource
        # Note: AWS credentials are automatically picked up from the environment
        # (e.g. ~/.aws/credentials, env vars, or IAM role if on EC2)
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        
        self.trades_table = self.dynamodb.Table(self.table_names['trades'])
        self.stats_table = self.dynamodb.Table(self.table_names['stats'])
        self.prices_table = self.dynamodb.Table(self.table_names['prices'])
        self.signals_table = self.dynamodb.Table(self.table_names['signals'])
        
        # Position Management tables
        self.positions_table = self.dynamodb.Table(self.table_names.get('positions', 'positions'))
        self.orders_table = self.dynamodb.Table(self.table_names.get('orders', 'orders'))
        
        # Paper Trading (TEST mode) tables
        self.test_positions_table = self.dynamodb.Table(self.table_names.get('test_positions', 'test_positions'))
        self.test_orders_table = self.dynamodb.Table(self.table_names.get('test_orders', 'test_orders'))
        self.test_account_table = self.dynamodb.Table(self.table_names.get('test_account', 'test_account'))

    def log_trade(self, trade_data):
        """
        Logs a trade to DynamoDB.
        trade_data: dict containing symbol, action, amount, price, pnl, algo
        """
        try:
            item = {
                'trade_id': str(uuid.uuid4()),
                'timestamp': int(time.time() * 1000),
                'symbol': trade_data['symbol'],
                'action': trade_data['action'],
                'amount': Decimal(str(trade_data['amount'])),
                'price': Decimal(str(trade_data['price'])),
                'pnl': Decimal(str(trade_data.get('pnl', 0))),
                'algo': trade_data['algo']
            }
            self.trades_table.put_item(Item=item)
            print(f"Logged trade: {item['trade_id']}")
        except ClientError as e:
            print(f"Error logging trade: {e}")
    
    def log_signal(self, signal_data):
        """
        Logs a trading signal to DynamoDB.
        signal_data: dict with keys like symbol, signal, algo, price, timestamp
        """
        try:
            # Convert any Decimal/float values
            item = {
                'signal_id': str(uuid.uuid4()),  # Primary key
                'symbol': signal_data['symbol'],
                'signal': signal_data['signal'],
                'algo': signal_data.get('algo', 'UNKNOWN'),
                'price': Decimal(str(signal_data['price'])),
                'timestamp': signal_data['timestamp']
            }
            
            self.signals_table.put_item(Item=item)
            print(f"Signal logged: {signal_data['signal']} for {signal_data['symbol']}")
        except Exception as e:
            print(f"Error logging signal: {e}")


    def log_candle(self, candle_data):
        """
        Logs a closed candle with indicators.
        candle_data: dict with symbol, timestamp, open, high, low, close, volume, and indicators
        """
        try:
            # TTL: Expire after 7 days
            expiry = int(time.time()) + 604800
            
            # Prepare Item
            item = {
                'symbol': candle_data['symbol'],
                'timestamp': int(candle_data['timestamp']),
                'expiry': expiry
            }
            
            for k, v in candle_data.items():
                if k in ['symbol', 'timestamp']:
                    continue
                
                # Robust NaN/Inf check using string representation
                # This catches float('nan'), numpy.nan, etc.
                s_val = str(v).lower()
                if s_val in ['nan', 'inf', '-inf']:
                    continue
                
                # Attempt to convert to Decimal for DynamoDB (handles floats, ints, numpy types)
                try:
                    item[k] = Decimal(str(v))
                except:
                    # If not a number, store as is
                    item[k] = v
                    
            self.prices_table.put_item(Item=item)
        except ClientError as e:
            print(f"Error logging candle: {e}")

    def log_price(self, symbol, price, **kwargs):
        """
        Logs historical price and any additional indicators.
        """
        try:
            # TTL: Expire after 7 days (604800 seconds)
            expiry = int(time.time()) + 604800
            
            item = {
                'symbol': symbol,
                'timestamp': int(time.time() * 1000),
                'price': Decimal(str(price)),
                'expiry': expiry
            }
            
            # Add extra fields (e.g. indicators)
            for k, v in kwargs.items():
                # Robust NaN/Inf check
                s_val = str(v).lower()
                if s_val in ['nan', 'inf', '-inf']:
                    continue
                
                try:
                    item[k] = Decimal(str(v))
                except:
                    item[k] = v
                    
            self.prices_table.put_item(Item=item)
        except ClientError as e:
            print(f"Error logging price: {e}")

    def get_trades(self, limit=50):
        """
        Fetch recent trades.
        """
        try:
            # Better to Query by Index if we had one, but Scan ok for small MVP limit
            # To sort by timestamp desc, we might need to fetch more and sort in app
            response = self.trades_table.scan(Limit=limit)
            items = response.get('Items', [])
            return sorted(items, key=lambda x: x['timestamp'], reverse=True)
        except ClientError as e:
            print(f"Error fetching trades: {e}")
            return []

    def get_price_history(self, symbol, limit=200):
        """
        Fetch price history for a specific symbol using Query.
        """
        try:
            from boto3.dynamodb.conditions import Key
            response = self.prices_table.query(
                KeyConditionExpression=Key('symbol').eq(symbol),
                ScanIndexForward=False, # Descending time (newest first)
                Limit=limit
            )
            items = response.get('Items', [])
            # Reverse to return in Ascending order (oldest -> newest) for plotting
            items.reverse()
            return items
        except ClientError as e:
            print(f"Error fetching price history: {e}")
            return []
    
    # === Position Management Methods ===
    
    def log_position(self, position_data, mode="LIVE"):
        """Log a new position to DynamoDB."""
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            item = {
                'position_id': position_data['position_id'],
                'symbol': position_data['symbol'],
                'side': position_data['side'],
                'entry_price': Decimal(str(position_data['entry_price'])),
                'quantity': Decimal(str(position_data['quantity'])),
                'entry_time': int(position_data['entry_time'].timestamp() * 1000),
                'status': position_data['status'],
                'pnl': Decimal(str(position_data.get('pnl', 0)))
            }
            table.put_item(Item=item)
            print(f"[{mode}] Logged position: {item['position_id']}")
        except ClientError as e:
            print(f"Error logging position: {e}")
    
    def update_position_pnl(self, position_id, pnl, current_price, mode="LIVE"):
        """Update P&L for an open position."""
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            table.update_item(
                Key={'position_id': position_id},
                UpdateExpression='SET pnl = :pnl, current_price = :price',
                ExpressionAttributeValues={
                    ':pnl': Decimal(str(pnl)),
                    ':price': Decimal(str(current_price))
                }
            )
        except ClientError as e:
            print(f"Error updating position P&L: {e}")
    
    def close_position(self, position_id, exit_price, exit_time, final_pnl, mode="LIVE"):
        """Mark a position as closed."""
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            table.update_item(
                Key={'position_id': position_id},
                UpdateExpression='SET #status = :status, exit_price = :exit_price, exit_time = :exit_time, pnl = :pnl',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'closed',
                    ':exit_price': Decimal(str(exit_price)),
                    ':exit_time': int(exit_time.timestamp() * 1000),
                    ':pnl': Decimal(str(final_pnl))
                }
            )
            print(f"[{mode}] Closed position: {position_id} with P&L: {final_pnl}")
        except ClientError as e:
            print(f"Error closing position: {e}")
    
    def log_order(self, order_data, mode="LIVE"):
        """Log a new order to DynamoDB."""
        try:
            table = self.test_orders_table if mode == "TEST" else self.orders_table
            item = {
                'order_id': order_data['order_id'],
                'symbol': order_data['symbol'],
                'side': order_data['side'],
                'price': Decimal(str(order_data['price'])),
                'amount': Decimal(str(order_data['amount'])),
                'status': order_data['status'],
                'created_at': int(order_data['created_at'].timestamp() * 1000),
                'expires_at': int(order_data['expires_at'].timestamp() * 1000)
            }
            if 'type' in order_data:
                item['type'] = order_data['type']
                
            table.put_item(Item=item)
            print(f"[{mode}] Logged order: {item['order_id']}")
        except ClientError as e:
            print(f"Error logging order: {e}")
    
    def update_order(self, order_data):
        """Update an order status."""
        try:
            update_expr = 'SET #status = :status'
            expr_values = {':status': order_data['status']}
            
            if 'filled_at' in order_data and order_data['filled_at']:
                update_expr += ', filled_at = :filled_at'
                expr_values[':filled_at'] = int(order_data['filled_at'].timestamp() * 1000)
            
            self.orders_table.update_item(
                Key={'order_id': order_data['order_id']},
                UpdateExpression=update_expr,
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues=expr_values
            )
        except ClientError as e:
            print(f"Error updating order: {e}")

    def update_order_status(self, order_id, new_status, mode="LIVE"):
        """Update order status."""
        try:
            table = self.test_orders_table if mode == "TEST" else self.orders_table
            table.update_item(
                Key={'order_id': order_id},
                UpdateExpression='SET #status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': new_status}
            )
            print(f"[{mode}] Updated order {order_id} status to {new_status}")
        except ClientError as e:
            print(f"Error updating order status: {e}")

    def update_position_status(self, position_id, new_status, mode="LIVE"):
        """Update position status (e.g. to 'request_close')."""
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            table.update_item(
                Key={'position_id': position_id},
                UpdateExpression='SET #status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': new_status}
            )
            print(f"[{mode}] Updated position {position_id} status to {new_status}")
        except ClientError as e:
            print(f"Error updating position status: {e}")

    def update_position_risk(self, position_id, stop_loss, take_profit, mode="LIVE"):
        """Update SL/TP for a position."""
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            # Handle potential None values safely? 
            # DynamoDB doesn't like nulls sometimes, better to remove attribute if None, but here we assume user sends values.
            # Convert to Decimal
            sl_val = Decimal(str(stop_loss)) if stop_loss else None
            tp_val = Decimal(str(take_profit)) if take_profit else None
            
            update_expr = 'SET '
            expr_vals = {}
            
            if sl_val is not None:
                update_expr += 'stop_loss = :sl, '
                expr_vals[':sl'] = sl_val
            if tp_val is not None:
                update_expr += 'take_profit = :tp, '
                expr_vals[':tp'] = tp_val
            
            if not expr_vals:
                return # Nothing to update
                
            update_expr = update_expr.rstrip(', ') # Remove trailing comma
            
            table.update_item(
                Key={'position_id': position_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_vals
            )
            print(f"[{mode}] Updated position {position_id} risk: SL={stop_loss}, TP={take_profit}")
        except ClientError as e:
            print(f"Error updating position risk: {e}")
    
    def get_account_pnl(self, mode="LIVE"):
        """Get account-level P&L statistics."""
        try:
            if mode == "TEST":
                table = self.test_positions_table
            else:
                table = self.positions_table
                
            response = table.scan()
            positions = response.get('Items', [])
            
            total_pnl = 0
            open_pnl = 0
            closed_pnl = 0
            win_count = 0
            loss_count = 0
            
            for pos in positions:
                pnl = float(pos.get('pnl', 0))
                total_pnl += pnl
                
                if pos['status'] == 'open':
                    open_pnl += pnl
                else:
                    closed_pnl += pnl
                    if pnl > 0:
                        win_count += 1
                    elif pnl < 0:
                        loss_count += 1
            
            
            return {
                'total_pnl': total_pnl,
                'open_pnl': open_pnl,
                'closed_pnl': closed_pnl,
                'win_count': win_count,
                'loss_count': loss_count,
                'win_rate': win_count / (win_count + loss_count) if (win_count + loss_count) > 0 else 0
            }
        except ClientError as e:
            print(f"Error getting account P&L: {e}")
            return {'total_pnl': 0, 'open_pnl': 0, 'closed_pnl': 0, 'win_count': 0, 'loss_count': 0, 'win_rate': 0}

    def get_active_position(self, mode="LIVE"):
        """
        Get the currently active position (open or request_close).
        Returns None if no active position is found.
        """
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            
            # Scan for status=open OR status=request_close
            # Using partial scan with FilterExpression
            response = table.scan(
                FilterExpression='#st IN (:open, :req_close)',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={
                    ':open': 'open',
                    ':req_close': 'request_close'
                }
            )
            
            items = response.get('Items', [])
            if items:
                # Return the first found active position
                # (Assuming Rule 2: Single Position Only)
                pos = items[0]
                # Convert Decimals to appropriate types
                pos['entry_price'] = float(pos['entry_price'])
                pos['quantity'] = float(pos['quantity'])
                pos['pnl'] = float(pos.get('pnl', 0))
                # Convert timestamp if needed? 
                # PositionManager expects datetime objects for internal usage usually?
                # Actually _create_position_from_order sets datetime. 
                # DB stores milliseconds.
                # Let's verify what PositionManager expects.
                # It uses it for calculations/logging. 
                # Let's convert entry_time to datetime
                if 'entry_time' in pos:
                    pos['entry_time'] = datetime.fromtimestamp(int(pos['entry_time']) / 1000)
                
                return pos
            
            return None
            
        except ClientError as e:
            print(f"Error fetching active position: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error in get_active_position: {e}")
            return None
