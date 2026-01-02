import logging
import ccxt
import json
import time
import pandas as pd
import os
import sys
from collections import deque
from datetime import datetime
from dotenv import load_dotenv

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from persistence import DynamoManager
from strategies import StrategyRegistry

# Load environment variables
load_dotenv()

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self, config_path):
        self.load_config(config_path)
        self.setup_exchange()
        self.setup_persistence()
        self.setup_strategies()
        
        # In-memory data storage
        self.price_history = {symbol: deque(maxlen=2000) for symbol in self.symbols}
        self.start_time = time.time()
        
    def load_config(self, path):
        with open(path, 'r') as f:
            self.config = json.load(f)
        
        self.symbols = self.config['trading']['symbols']
        self.base_currency = self.config['trading']['base_currency']
        self.risk_per_trade = self.config['trading']['risk_per_trade']
        
    def setup_exchange(self):
        exch_config = self.config['exchange']
        exchange_id = exch_config['id']
        exchange_class = getattr(ccxt, exchange_id)
        
        self.exchange = exchange_class({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_SECRET'),
            'enableRateLimit': True,
            'options': exch_config['options']
        })
        
        if exch_config.get('testnet'):
            self.exchange.set_sandbox_mode(True)
            
    def setup_persistence(self):
        try:
            self.db = DynamoManager(self.config)
        except Exception as e:
            logger.error(f"Failed to initialize DynamoDB: {e}")
            raise e
        
    def setup_strategies(self):
        self.strategies = {}
        active_strategies = self.config['trading']['active_strategies']
        
        for name, details in active_strategies.items():
            if details['enabled']:
                try:
                    strategy = StrategyRegistry.get_strategy(name, details['params'])
                    self.strategies[name] = strategy
                    logger.info(f"Loaded strategy: {name}")
                except Exception as e:
                    logger.error(f"Failed to load strategy {name}: {e}")

    def fetch_data(self):
        for symbol in self.symbols:
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                price = ticker['last']
                timestamp = ticker['timestamp']
                
                self.price_history[symbol].append({
                    'timestamp': timestamp,
                    'price': price,
                    'close': price,
                    'volume': ticker.get('baseVolume', 0)
                })
                
                self.db.log_price(symbol, price)
                
            except Exception as e:
                logger.error(f"Error fetching data for {symbol}: {e}")

    def execute_strategies(self):
        for symbol in self.symbols:
            if len(self.price_history[symbol]) < 100:
                continue
                
            df = pd.DataFrame(self.price_history[symbol])
            
            for name, strategy in self.strategies.items():
                signal = strategy.calculate(df)
                
                if signal:
                    logger.info(f"Signal {signal} for {symbol} from {name}")
                    self.execute_trade(symbol, signal, name, df.iloc[-1]['price'])

    def execute_trade(self, symbol, action, algo, price):
        try:
            amount = 0.001 
            
            if self.exchange.has['fetchMarkets']:
                if not self.exchange.markets:
                    self.exchange.load_markets()
                
                market = self.exchange.market(symbol)
                min_amount = market['limits']['amount']['min']
                
                if min_amount:
                    amount = min_amount
            
            if not self.exchange.apiKey:
                logger.warning("No API Keys - Dry Run Trade")
                order = {'id': 'mock-'+str(int(time.time())), 'price': price, 'amount': amount}
            else:
                side = action.lower() 
                order = self.exchange.create_order(symbol, 'market', side, amount)
                
            trade_data = {
                'symbol': symbol,
                'action': action,
                'amount': amount,
                'price': order.get('price', price),
                'pnl': 0,
                'algo': algo
            }
            
            self.db.log_trade(trade_data)
            logger.info(f"Executed {action} for {symbol} | Qty: {amount} | Price: {price}")
            
        except Exception as e:
            logger.exception(f"Trade execution failed: {e}")

    def log_status(self):
        uptime = int(time.time() - self.start_time)
        msg = f"STATUS: Running for {uptime}s | Strategies: {len(self.strategies)} | Symbols: {len(self.symbols)}"
        for symbol in self.symbols:
            last_price = self.price_history[symbol][-1]['price'] if self.price_history[symbol] else 'N/A'
            msg += f" | {symbol}: {last_price}"
        logger.info(msg)

    def run(self):
        logger.info("Bot started...")
        counter = 0
        while True:
            try:
                self.fetch_data()
                self.execute_strategies()
                
                # Log status every minute (approx every 6 cycles of 10s)
                counter += 1
                if counter % 6 == 0:
                    self.log_status()
                    
                time.sleep(10)
            except KeyboardInterrupt:
                logger.info("Bot stopped by user.")
                break
            except Exception as e:
                logger.exception(f"Unexpected error in main loop: {e}")
                time.sleep(10) # Wait before retry to avoid rapid loops

if __name__ == "__main__":
    bot = TradingBot('config.json')
    bot.run()
