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
from position_manager import PositionManager

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
        self.setup_position_manager()
        
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
    
    def setup_position_manager(self):
        """Initialize the position manager with risk controls."""
        risk_config = self.config['trading'].get('risk_management', {})
        mode = self.config['trading'].get('mode', 'TEST')
        self.position_manager = PositionManager(self.exchange, self.db, risk_config, mode)
        logger.info(f"Position Manager initialized in {mode} mode")


    # --- WebSocket Handling ---

    def start_websocket(self):
        logger.info(f"Starting WebSocket Client ({self.interval})...")
        
        # Local callback to ensure reliable execution (Closure)
        def handle_message(_, message):
            try:
                payload = json.loads(message)
                
                # Handle Combined Stream Format (is_combined=True)
                if 'data' in payload:
                    data = payload['data']
                else:
                    data = payload

                if 'e' in data and data['e'] == 'kline':
                    self.process_kline(data)
            except Exception as e:
                logger.error(f"WS Message Error: {e}")

        self.ws_client = SpotWebsocketStreamClient(
            stream_url="wss://stream.binance.com:9443",
            on_message=handle_message,
            on_error=self.on_error,
            on_close=self.on_close,
            is_combined=True
        )
        
        # Subscribe to Kline streams from Config
        streams = [f"{symbol.replace('/', '').lower()}@kline_{self.interval}" for symbol in self.symbols]
        self.ws_client.subscribe(stream=streams)
        logger.info(f"Subscribed to: {streams}")

    # on_message method is no longer used directly by WS client, 
    # but kept if needed for reference or manual calls.
    def on_message(self, _, message):
        pass

    def on_error(self, _, error):
        logger.error(f"WebSocket Error: {error}")

    def on_error(self, _, error):
        with open("/home/ec2-user/trading-bot/ws_debug.log", "a") as f:
            f.write(f"{datetime.now()} WS ERROR: {error}\n")
        logger.error(f"WebSocket Error: {error}")


    def on_close(self, _, *args):
        logger.warning("WebSocket Closed. Attempting Reconnect...")
        time.sleep(5)
        self.start_websocket()

    def process_kline(self, data):
        try:
            # Extract Candle Data
            k = data['k']
            symbol = data['s'] 
            
            with open("ws_debug.log", "a") as f:
                f.write(f"{datetime.now()} KLINE: {symbol} Price:{k['c']} IsClosed:{k['x']}\n")

            # Map raw symbol data 's' (BTCUSDT) to config symbol (BTC/USDT)
            target_symbol = None
            for s in self.symbols:
                # DEBUG MAPPING
                if s.replace('/', '') == symbol:
                    target_symbol = s
                    break
            
            if not target_symbol:
                with open("ws_debug.log", "a") as f:
                    f.write(f"{datetime.now()} MAPPING FAIL: Got {symbol} but have {self.symbols}\n")
                return

            is_closed = k['x'] # boolean
            close_price = float(k['c'])
            
            self.latest_prices[target_symbol] = close_price
            
            # Construct candle object
            candle = {
                'timestamp': k['t'], 
                'open': float(k['o']),
                'high': float(k['h']),
                'low': float(k['l']),
                'close': float(k['c']),
                'volume': float(k['v']),
                'symbol': target_symbol
            }
            
            # --- REAL-TIME INDICATOR CALCULATION ---
            # Create a customized copy of history + current candle to calculate indicators continuously
            temp_history = list(self.candles[target_symbol])
            temp_history.append(candle)
            
            cand_data_to_log = candle # Default to raw candle
            
            if len(temp_history) >= 20: # Minimal check, strategies have their own checks
                try:
                    df_temp = pd.DataFrame(temp_history)
                    for name, strategy in self.strategies.items():
                        strategy.calculate(df_temp)
                    
                    # Get the last row (our live candle) which now has indicators
                    cand_data_to_log = df_temp.iloc[-1].to_dict()
                except Exception as calc_err:
                    logger.error(f"RT Calc Error: {calc_err}")

            # PERSIST LIVE CANDLE WITH INDICATORS
            self.db.log_candle(cand_data_to_log)

        except Exception as e:
            logger.error(f"Real-time persist error: {e}")
        
        # logic: We only really commit to memory and run strategies on CLOSE of a candle
        # to mimic standard technical analysis.
        if is_closed:
            # 1. Update Memory
            self.candles[target_symbol].append(candle)
            
            # 2. Run Strategy (Calculates indicators + Re-logs full candle)
            self.run_strategy(target_symbol)

    def run_strategy(self, symbol):
        if len(self.candles[symbol]) < 50: # Minimum warmup
            return

        df = pd.DataFrame(self.candles[symbol])
        
        # Execute Strategies
        for name, strategy in self.strategies.items():
            signal = strategy.calculate(df) # This adds indicator columns to df
            
            if signal:
                # Log signal with SMA values (only on candle close!)
                last_row = df.iloc[-1]
                sma_short = last_row.get('sma_short', 'N/A')
                sma_long = last_row.get('sma_long', 'N/A')
                
                if signal == 'BUY':
                    logger.info(f"🟢 BUY SIGNAL: SMA crossed ABOVE | Short: {sma_short:.2f}, Long: {sma_long:.2f}")
                else:
                    logger.info(f"🔴 SELL SIGNAL: SMA crossed BELOW | Short: {sma_short:.2f}, Long: {sma_long:.2f}")
                
                # Log signal to database (for dashboard/chart)
                self.db.log_signal({
                    'symbol': symbol,
                    'signal': signal,
                    'algo': name,
                    'price': df.iloc[-1]['close'],
                    'timestamp': int(time.time() * 1000)
                })
                
                self.execute_trade(symbol, signal, name, df.iloc[-1]['close'])


        # Log Full Candle + Indicators to DB (Overwrites the raw real-time candle)
        last_row = df.iloc[-1].to_dict()
        self.db.log_candle(last_row)
        
        # Explicit Log for User Clarity
        logger.info(f"REALTIME UPDATE ({symbol}): Close={last_row['close']} | SMA_S={last_row.get('sma_short', 'N/A')} | SMA_L={last_row.get('sma_long', 'N/A')}")

    def execute_trade(self, symbol, action, algo, price):
        """Execute trade using PositionManager with limit orders."""
        try:
            # Check if we can open a position
            if not self.position_manager.can_open_position(symbol):
                logger.info(f"Cannot execute {action} for {symbol}: position limit reached")
                return
            
            # Calculate position size (uses exchange minimum)
            amount = self.position_manager.calculate_position_size(symbol, price)
            if amount is None:
                logger.error(f"Failed to calculate position size for {symbol}")
                return
            
            # Dry run check
            if not self.exchange.apiKey:
                logger.warning(f"No API Keys - Dry Run: Would place {action} limit order for {symbol}")
                return
            
            # Place limit order via PositionManager
            side = action.lower()  # "BUY" -> "buy", "SELL" -> "sell"
            order = self.position_manager.place_limit_order(symbol, side, price, amount)
            
            if order:
                logger.info(f"✓ Limit order placed: {action} {amount} {symbol} @ {order['price']}")
            else:
                logger.error(f"Failed to place limit order for {symbol}")
                
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
        order_check_counter = 0
        
        while True:
            # Keep main thread alive
            time.sleep(10)
            
            counter += 1
            order_check_counter += 1
            
            # Check orders every 10s (every iteration)
            try:
                # 1. Sync State (New Orders, Cancel/Close Requests, Risk Updates)
                self.position_manager.sync_state()

                # 2. Check for Forced Close Requests
                pos = self.position_manager.current_position
                if pos and pos.get('force_close', False):
                    # Find price
                    symbol = pos['symbol']
                    current_price = self.latest_prices.get(symbol)
                    
                    if current_price:
                        logger.info(f"Detected FORCE CLOSE request for {pos['position_id']}")
                        self.position_manager.close_position(current_price=current_price)
                        pos['force_close'] = False
                
                # 3. Regular Order Status Check
                for order_id in list(self.position_manager.pending_orders.keys()):
                    order_data = self.position_manager.pending_orders.get(order_id)
                    if order_data:
                        symbol = order_data['symbol']
                        current_price = self.latest_prices.get(symbol)
                        self.position_manager.check_order_status(order_id, current_price)
                
                # 4. Cancel expired orders
                self.position_manager.cancel_expired_orders()
                
                # 5. Update P&L for open positions
                for symbol in self.symbols:
                    if symbol in self.latest_prices:
                        self.position_manager.update_position_pnl(symbol, self.latest_prices[symbol])
                        
            except Exception as e:
                logger.error(f"Order monitoring error: {e}")
            
            # Status log every ~60s
            if counter % 6 == 0:
                self.log_status()
                # Log a heartbeat to api_logs.txt so user knows it's alive
                with open("api_logs.txt", "a") as f:
                     price = self.latest_prices.get(self.symbols[0], "N/A")
                     ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                     f.write(f"{ts} [WS UPDATE] Bot is alive | Price: {price}\n")


if __name__ == "__main__":
    bot = TradingBot('config.json')
    bot.run()
