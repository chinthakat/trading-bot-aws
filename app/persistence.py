import boto3
import time
import uuid
from botocore.exceptions import ClientError
from decimal import Decimal

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

    def log_price(self, symbol, price):
        """
        Logs historical price (optional, as main storage is usually better suited for TimeStream or just using deque in mem).
        """
        try:
            # TTL: Expire after 7 days (604800 seconds)
            expiry = int(time.time()) + 604800
            self.prices_table.put_item(
                Item={
                    'symbol': symbol,
                    'timestamp': int(time.time() * 1000),
                    'price': Decimal(str(price)),
                    'expiry': expiry
                }
            )
        except ClientError as e:
            print(f"Error logging price: {e}")

    def get_trades(self, limit=50):
        """
        Fetch recent trades.
        """
        try:
            response = self.trades_table.scan(Limit=limit)
            return response.get('Items', [])
        except ClientError as e:
            print(f"Error fetching trades: {e}")
            return []
