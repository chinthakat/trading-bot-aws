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

# Binance Connector
from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient

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
        logging.FileHandler("bot.log"),
        logging.FileHandler("api_logs.txt") # Capture logs here too for the dashboard
    ]
)
logger = logging.getLogger(__name__)

# Also log uncaught exceptions
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

class TradingBot:
    def __init__(self, config_path):
        self.load_config(config_path)
        self.setup_exchange()
        self.setup_persistence()
        self.setup_strategies()
        
        # In-memory storage for candles
        # { symbol: DataFrame or List of Dicts }
        # We keep slightly more than needed for long_window (e.g. 500)
        self.candles = {symbol: deque(maxlen=500) for symbol in self.symbols}
        logger.info("Initialized candles with maxlen: 500")
        
        # Latest prices for quick lookup
        self.latest_prices = {}
        
        self.start_time = time.time()
        self.ws_client = None

    def load_config(self, path):
        with open(path, 'r') as f:
            self.config = json.load(f)
        
        self.symbols = self.config['trading']['symbols']
        self.base_currency = self.config['trading']['base_currency']
        self.risk_per_trade = self.config['trading']['risk_per_trade']
        self.interval = self.config['trading'].get('interval', '1m')
        
    def setup_exchange(self):
        # REST client for Order Execution (still needed)
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
            self.ws_base_url = "wss://testnet.binance.vision" 
        else:
            self.ws_base_url = "wss://stream.binance.com:9443"

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

    # --- WebSocket Handling ---

    def start_websocket(self):
        logger.info(f"Starting WebSocket Client ({self.interval})...")
        self.ws_client = SpotWebsocketStreamClient(
            stream_url=self.ws_base_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            is_combined=True
        )
        
        # Subscribe to Kline streams
        streams = [f"{symbol.replace('/', '').lower()}@kline_{self.interval}" for symbol in self.symbols]
        self.ws_client.subscribe(stream=streams)
        logger.info(f"Subscribed to: {streams}")

    def on_message(self, _, message):
        try:
            data = json.loads(message)
            if 'e' in data and data['e'] == 'kline':
                self.process_kline(data)
        except Exception as e:
            logger.error(f"WS Message Error: {e}")

    def on_error(self, _, error):
        logger.error(f"WebSocket Error: {error}")

    def on_close(self, _, *args):
        logger.warning("WebSocket Closed. Attempting Reconnect...")
        time.sleep(5)
        self.start_websocket()

    def process_kline(self, data):
        # Extract Candle Data
        k = data['k']
        symbol = data['s'] # e.g. BTCUSDT (Need to map back to BTC/USDT if necessary, but config symbols are BTC/USDT)
        
        # Map raw symbol data 's' (BTCUSDT) to config symbol (BTC/USDT)
        # Simple lookup:
        target_symbol = None
        for s in self.symbols:
            if s.replace('/', '') == symbol:
                target_symbol = s
                break
        
        if not target_symbol:
            return

        is_closed = k['x'] # boolean
        close_price = float(k['c'])
        
        self.latest_prices[target_symbol] = close_price
        
        # logic: We only really commit to memory and run strategies on CLOSE of a candle
        # to mimic standard technical analysis.
        if is_closed:
            candle = {
                'timestamp': k['t'], # Open time (ms)
                'open': float(k['o']),
                'high': float(k['h']),
                'low': float(k['l']),
                'close': float(k['c']),
                'volume': float(k['v']),
                'symbol': target_symbol
            }
            
            # 1. Update Memory
            self.candles[target_symbol].append(candle)
            
            # 2. Run Strategy
            self.run_strategy(target_symbol)
        
    def run_strategy(self, symbol):
        if len(self.candles[symbol]) < 50: # Minimum warmup
            return

        df = pd.DataFrame(self.candles[symbol])
        
        # Execute Strategies
        for name, strategy in self.strategies.items():
            signal = strategy.calculate(df) # This adds indicator columns to df
            
            if signal:
                logger.info(f"Signal {signal} for {symbol} from {name}")
                self.execute_trade(symbol, signal, name, df.iloc[-1]['close'])

        # Log Full Candle + Indicators to DB
        last_row = df.iloc[-1].to_dict()
        self.db.log_candle(last_row)
        
        # Explicit Log for User Clarity
        logger.info(f"REALTIME UPDATE ({symbol}): Close={last_row['close']} | SMA_S={last_row.get('sma_short', 'N/A')} | SMA_L={last_row.get('sma_long', 'N/A')}")

    def execute_trade(self, symbol, action, algo, price):
        try:
            amount = 0.001 
            # (Same trade logic as before, potentially optimized later)
            
            if self.exchange.has['fetchMarkets']:
                if not self.exchange.markets:
                    self.exchange.load_markets()
                market = self.exchange.market(symbol)
                min_amount = market['limits']['amount']['min']
                if min_amount:
                    amount = min_amount
            
            if not self.exchange.apiKey:
                logger.warning("No API Keys - Dry Run Trade")
                order = {'id': 'ws-mock-'+str(int(time.time())), 'price': price, 'amount': amount}
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
        msg = f"STATUS: Running for {uptime}s | Interval: {self.interval}"
        for symbol, price in self.latest_prices.items():
            msg += f" | {symbol}: {price}"
        logger.info(msg)

    def backfill_history(self):
        # We need enough history for the Long SMA (100) to have valid values.
        # 100 candles isn't enough (results in 1 valid point).
        limit = 500
        logger.info(f"Backfilling history for {len(self.symbols)} symbols ({limit} candles)...")
        for symbol in self.symbols:
            try:
                logger.info(f"API REQUEST: fetch_ohlcv({symbol}, {self.interval}, limit={limit})")
                
                # fetch_ohlcv returns [timestamp, open, high, low, close, volume]
                ohlcv = self.exchange.fetch_ohlcv(symbol, self.interval, limit=limit)
                logger.info(f"API RESPONSE: Received {len(ohlcv)} candles for {symbol}")
                
                new_candles = []
                for candle in ohlcv:
                    new_candles.append({
                        'timestamp': candle[0],
                        'open': float(candle[1]),
                        'high': float(candle[2]),
                        'low': float(candle[3]),
                        'close': float(candle[4]),
                        'volume': float(candle[5]),
                        'symbol': symbol
                    })
                
                # Update Memory
                self.candles[symbol].extend(new_candles)
                
                if len(new_candles) > 0:
                    df = pd.DataFrame(self.candles[symbol])
                    
                    # Calculate Indicators
                    for name, strategy in self.strategies.items():
                        strategy.calculate(df)
                        
                    logger.info(f"Persisting {len(df)} backfilled candles for {symbol} to DB...")
                    count = 0
                    for index, row in df.iterrows():
                        self.db.log_candle(row.to_dict())
                        count += 1
                        if count % 10 == 0: sum = 0 # Dummy op to not spam logs too distinct
                    
                    logger.info(f"Successfully persisted {count} candles for {symbol}.")
                    
                    # Set the latest price for status
                    self.latest_prices[symbol] = new_candles[-1]['close']
                    
            except Exception as e:
                logger.error(f"Backfill failed for {symbol}: {e}")
                logger.exception("Backfill traceback:")

    def run(self):
        # 1. Backfill first
        self.backfill_history()
        
        # 2. Start WS
        self.start_websocket()
        logger.info("Bot is listening...")
        
        counter = 0
        while True:
            # Keep main thread alive
            time.sleep(10)
            
            counter += 1
            if counter % 6 == 0: # Every ~60s
                self.log_status()
                # Log a heartbeat to api_logs.txt so user knows it's alive
                with open("api_logs.txt", "a") as f:
                     price = self.latest_prices.get(self.symbols[0], "N/A")
                     ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                     f.write(f"{ts} [WS UPDATE] Bot is alive | Price: {price}\n")

if __name__ == "__main__":
    bot = TradingBot('config.json')
    bot.run()
