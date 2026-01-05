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
        
        # Audit Logs
        self.audit_table = self.dynamodb.Table(self.table_names.get('audit', 'audit_logs'))
        self.test_audit_table = self.dynamodb.Table(self.table_names.get('test_audit', 'test_audit_logs'))
        self.counters_table = self.dynamodb.Table(self.table_names.get('counters', 'TradingBot_Counters'))

    def _sanitize_for_dynamo(self, item):
        """Helper to sanitize a dict for DynamoDB (float -> Decimal, robust NaN checks)."""
        new_item = {}
        for k, v in item.items():
            # Robust NaN/Inf check for floats/strings
            s_val = str(v).lower()
            if s_val in ['nan', 'inf', '-inf']:
                continue
            
            # Convert float to Decimal
            if isinstance(v, float):
                try:
                    new_item[k] = Decimal(str(v))
                except:
                    new_item[k] = v
            else:
                new_item[k] = v
        return new_item

    def get_next_sequence(self, name):
        """
        Get next sequence number from atomic counter.
        Returns integer.
        """
        try:
            response = self.counters_table.update_item(
                Key={'counter_name': name},
                UpdateExpression="ADD current_value :inc",
                ExpressionAttributeValues={':inc': 1},
                ReturnValues="UPDATED_NEW"
            )
            return int(response['Attributes']['current_value'])
        except Exception as e:
            print(f"Error getting sequence {name}: {e}")
            return int(time.time()) # Fallback to timestamp if fails

    def log_audit(self, action, cause, details, mode, price=None, side=None, signal_id=None):
        """
        Log an audit event.
        """
        try:
            table = self.test_audit_table if mode == "TEST" else self.audit_table
            timestamp = int(time.time() * 1000)
            
            item = {
                'log_id': str(uuid.uuid4()),
                'timestamp': timestamp,
                'action': action,
                'cause': cause,
                'details': details or {}
            }
            
            # Additional structured fields
            if price: 
                item['price'] = Decimal(str(price))
            if side: 
                item['side'] = side
            if signal_id: 
                item['signal_id'] = signal_id
            
            # Also extract from details if not passed explicitly but present (fallback)
            if 'symbol' in details:
                item['symbol'] = details['symbol']
            if not price and 'price' in details:
                item['price'] = Decimal(str(details['price']))
                
            # Sanitize details (convert floats to Decimals)
            sanitized_details = {}
            for k, v in details.items():
                if isinstance(v, float):
                    sanitized_details[k] = Decimal(str(v))
                else:
                    sanitized_details[k] = v
            item['details'] = sanitized_details
            
            table.put_item(Item=item)
        except Exception as e:
            print(f"Error logging audit: {e}")

    def get_audit_logs(self, limit=50, mode="LIVE"):
        """
        Fetch recent audit logs.
        """
        try:
            table = self.test_audit_table if mode == "TEST" else self.audit_table
            # Scan might be slow if table grows, but ok for MVP. 
            # Ideally use Index on timestamp.
            response = table.scan() # Fetch all to sort correctly (Limit on scan truncates arbitrary items)
            items = response.get('Items', [])
            sorted_items = sorted(items, key=lambda x: x['timestamp'], reverse=True)
            return sorted_items[:limit]
        except Exception as e:
            print(f"Error fetching audit logs: {e}")
            return []
            
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
                'strategy_name': position_data.get('strategy_name', 'manual'),
                'entry_price': Decimal(str(position_data['entry_price'])),
                'quantity': Decimal(str(position_data['quantity'])),
                'entry_time': int(position_data['entry_time'].timestamp() * 1000),
                'status': position_data['status'],
                'pnl': Decimal(str(position_data.get('pnl', 0))),
                'entry_commission': Decimal(str(position_data.get('entry_commission', 0))),
                'stop_loss': Decimal(str(position_data.get('stop_loss', 0))) if position_data.get('stop_loss') else None,
                'take_profit': Decimal(str(position_data.get('take_profit', 0))) if position_data.get('take_profit') else None
            }
            # Remove None values
            item = {k: v for k, v in item.items() if v is not None}
            table.put_item(Item=item)
            print(f"[{mode}] Logged position: {item['position_id']} ({item.get('strategy_name')})")
        except ClientError as e:
            print(f"Error logging position: {e}")

    def update_position_pnl(self, position_id, pnl, current_price, mode="LIVE"):
        """
        Update the P&L of an active position.
        """
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            table.update_item(
                Key={'position_id': position_id},
                UpdateExpression="set pnl = :p",
                ExpressionAttributeValues={
                    ':p': Decimal(str(pnl))
                }
            )
            # We don't necessarily need to store current_price in position table, but pnl is critical.
        except ClientError as e:
            print(f"Error updating position pnl: {e}")
        
    def update_position_status(self, position_id, status, mode="LIVE"):
        """Update status of a position."""
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            table.update_item(
                Key={'position_id': position_id},
                UpdateExpression="set #st = :s",
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':s': status}
            )
            print(f"Updated position {position_id} status to {status}")
        except ClientError as e:
            print(f"Error updating position status: {e}")

    def update_position_risk(self, position_id, stop_loss, take_profit, mode="LIVE"):
        """Update SL/TP for a position."""
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            
            # Robust Decimal
            sl_val = Decimal(str(stop_loss)) if stop_loss is not None else None
            tp_val = Decimal(str(take_profit)) if take_profit is not None else None
            
            update_expr = "set stop_loss = :sl, take_profit = :tp"
            vals = {':sl': sl_val, ':tp': tp_val}
            
            table.update_item(
                Key={'position_id': position_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=vals
            )
        except ClientError as e:
            print(f"Error updating position risk: {e}")

    def close_position(self, position_data, mode="LIVE"):
        """
        Close a position by updating exit fields.
        """
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            
            table.update_item(
                Key={'position_id': position_data['position_id']},
                UpdateExpression="set #st = :st, exit_price = :ep, exit_time = :et, quantity = :q, pnl = :pnl, exit_commission = :ec",
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={
                    ':st': 'closed',
                    ':ep': Decimal(str(position_data['exit_price'])),
                    ':et': int(position_data['exit_time'].timestamp() * 1000),
                    ':q': Decimal(str(position_data['quantity'])),  # Remaining quantity (if partial) or 0? Usually we overwrite or irrelevant for closed.
                    # Wait, quantity shouldn't change unless partial.
                    ':pnl': Decimal(str(position_data['pnl'])),
                    ':ec': Decimal(str(position_data.get('exit_commission', 0)))
                }
            )
            print(f"[{mode}] Closed position {position_data['position_id']} PnL: {position_data['pnl']}")
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
                'strategy_name': order_data.get('strategy_name', 'manual'),
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

    # ... (Rest of Position Ops) ...
    
    def get_account_pnl(self, mode="LIVE"):
        """Get account-level P&L statistics, grouped by strategy."""
        try:
            if mode == "TEST":
                table = self.test_positions_table
            else:
                table = self.positions_table
                
            response = table.scan()
            positions = response.get('Items', [])
            
            # Global Stats
            global_stats = {
                'total_pnl': 0.0, 'open_pnl': 0.0, 'closed_pnl': 0.0, 
                'win_count': 0, 'loss_count': 0, 'total_fees': 0.0
            }
            
            # Per-Strategy Stats
            strategies = {}
            
            for pos in positions:
                strat = pos.get('strategy_name', 'manual')
                if strat not in strategies:
                    strategies[strat] = {
                        'total_pnl': 0.0, 'win_count': 0, 'loss_count': 0, 'total_fees': 0.0
                    }
                
                pnl = float(pos.get('pnl', 0))
                fees = float(pos.get('entry_commission', 0)) + float(pos.get('exit_commission', 0))
                
                # Update Global
                global_stats['total_pnl'] += pnl
                global_stats['total_fees'] += fees
                if pos.get('status') == 'open':
                     global_stats['open_pnl'] += pnl
                else:
                     global_stats['closed_pnl'] += pnl
                     if pnl > 0: global_stats['win_count'] += 1
                     elif pnl < 0: global_stats['loss_count'] += 1
                     
                # Update Strategy
                strategies[strat]['total_pnl'] += pnl
                strategies[strat]['total_fees'] += fees
                if pnl > 0 and pos.get('status') == 'closed': strategies[strat]['win_count'] += 1
                elif pnl < 0 and pos.get('status') == 'closed': strategies[strat]['loss_count'] += 1
            
            return {
                'total_pnl_net': global_stats['total_pnl'],
                'open_pnl_gross': global_stats['open_pnl'],
                'closed_pnl': global_stats['closed_pnl'],
                'win_count': global_stats['win_count'],
                'loss_count': global_stats['loss_count'],
                'win_rate': global_stats['win_count'] / (global_stats['win_count'] + global_stats['loss_count']) if (global_stats['win_count'] + global_stats['loss_count']) > 0 else 0,
                'total_fees': global_stats['total_fees'],
                'strategies': strategies # Breakdown
            }
        except ClientError as e:
            print(f"Error getting account P&L: {e}")
            return {
                'total_pnl_net': 0.0, 
                'open_pnl_gross': 0.0,
                'closed_pnl': 0.0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0.0,
                'total_fees': 0.0,
                'strategies': {}
            }

    def get_all_active_positions(self, mode="LIVE"):
        """
        Get all active positions (open or request_close) for all strategies.
        Returns a list of position dicts.
        """
        try:
            table = self.test_positions_table if mode == "TEST" else self.positions_table
            
            # Scan for status=open OR status=request_close
            response = table.scan(
                FilterExpression='#st IN (:open, :req_close)',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={
                    ':open': 'open',
                    ':req_close': 'request_close'
                }
            )
            
            items = response.get('Items', [])
            return [self._hydrate_position(item) for item in items]
            
        except ClientError as e:
            print(f"Error fetching active positions: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error in get_all_active_positions: {e}")
            return []

    def _hydrate_position(self, pos):
        """Helper to convert DynamoDB types to Python types."""
        # Convert Decimals/Strings to float
        pos['entry_price'] = float(pos['entry_price'])
        pos['quantity'] = float(pos['quantity'])
        pos['pnl'] = float(pos.get('pnl', 0))
        
        if 'entry_commission' in pos: pos['entry_commission'] = float(pos['entry_commission'])
        if 'exit_commission' in pos: pos['exit_commission'] = float(pos['exit_commission'])
        if 'stop_loss' in pos and pos['stop_loss'] is not None: pos['stop_loss'] = float(pos['stop_loss'])
        if 'take_profit' in pos and pos['take_profit'] is not None: pos['take_profit'] = float(pos['take_profit'])
        
        # Hydrate Timestamp
        if 'entry_time' in pos:
            # Check if it's already datetime (unlikely from DB) or int (ms)
            if isinstance(pos['entry_time'], (int, Decimal)):
                pos['entry_time'] = datetime.fromtimestamp(int(pos['entry_time']) / 1000)
                
        return pos

    def get_test_account_balance(self):
        """Get the current test account balance (latest entry)."""
        try:
            # Table has composite key (account_id, timestamp)
            # We query for 'test_account' and get the latest by timestamp
            response = self.test_account_table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('account_id').eq('test_account'),
                ScanIndexForward=False, # Descending order (newest first)
                Limit=1
            )
            items = response.get('Items', [])
            if items:
                return {
                    'balance': float(items[0]['balance']),
                    'updated_at': items[0].get('updated_at')
                }
            return None
        except Exception as e:
            print(f"Error getting test account balance: {e}")
            return None
            
    def update_test_account_balance(self, balance: float):
        """Update test account balance."""
        try:
            timestamp = int(datetime.now().timestamp() * 1000)
            self.test_account_table.put_item(
                Item={
                    'account_id': 'test_account',
                    'timestamp': timestamp,
                    'balance': Decimal(str(balance)),
                    'updated_at': timestamp
                }
            )
            return True
        except Exception as e:
            print(f"Error updating test account balance: {e}")
            return False
