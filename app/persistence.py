import boto3
import time
import uuid
from botocore.exceptions import ClientError
from decimal import Decimal
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
            print(f"Error fetching prices for {symbol}: {e}")
            return []
