
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
from threading import Lock

# Binance Connector
from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from persistence import DynamoManager
from strategy_loader import StrategyLoader
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
        logging.FileHandler("api_logs.txt") 
    ]
)
logger = logging.getLogger(__name__)

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
        
        self.last_processed_kline_ts = {} 
        self.candles = {symbol: deque(maxlen=500) for symbol in self.symbols}
        logger.info("Initialized candles with maxlen: 500")
        
        self.latest_prices = {}
        self.start_time = time.time()
        self.ws_client = None
        self.lock = Lock()

    def load_config(self, path):
        with open(path, 'r') as f:
            self.config = json.load(f)
        
        self.symbols = self.config['trading']['symbols']
        self.base_currency = self.config['trading']['base_currency']
        self.interval = self.config['trading'].get('interval', '1m')
        self.mode = self.config['trading'].get('mode', 'TEST')
        
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
        
        # New Plugin Loading Logic
        try:
            StrategyLoader.discover_strategies()
        except Exception as e:
            logger.error(f"Plugin Discovery Failed: {e}")

        for name, details in active_strategies.items():
            if details['enabled']:
                try:
                    # Use Loader
                    strategy = StrategyLoader.get_strategy(name, details['params'])
                    self.strategies[name] = strategy
                    logger.info(f"Loaded strategy plugin: {name}")
                except Exception as e:
                    logger.error(f"Failed to load strategy {name}: {e}")
    
    def setup_position_manager(self):
        risk_config = self.config['trading'].get('risk_management', {})
        self.position_manager = PositionManager(self.exchange, self.db, self.config['trading'], self.mode)
        logger.info(f"Position Manager initialized in {self.mode} mode")

    def start_websocket(self):
        logger.info(f"Starting WebSocket Client ({self.interval})...")
        def handle_message(_, message):
            try:
                payload = json.loads(message)
                if 'data' in payload: data = payload['data']
                else: data = payload
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
        streams = [f"{symbol.replace('/', '').lower()}@kline_{self.interval}" for symbol in self.symbols]
        self.ws_client.subscribe(stream=streams)
        logger.info(f"Subscribed to: {streams}")

    def on_error(self, _, error):
        logger.error(f"WebSocket Error: {error}")

    def on_close(self, _, *args):
        logger.warning("WebSocket Closed. Attempting Reconnect...")
        time.sleep(5)
        try:
            self.start_websocket()
        except:
            pass

    def process_kline(self, data):
        with self.lock:
            try:
                k = data['k']
                symbol = data['s']
                # Map Symbol
                target_symbol = None
                for s in self.symbols:
                    if s.replace('/', '') == symbol: target_symbol = s; break
                if not target_symbol: return

                is_closed = k['x']
                candle = {
                    'timestamp': k['t'], 
                    'open': float(k['o']), 'high': float(k['h']), 'low': float(k['l']), 'close': float(k['c']), 'volume': float(k['v']),
                    'symbol': target_symbol
                }
                
                self.latest_prices[target_symbol] = candle['close']

                if is_closed:
                    last_ts = self.last_processed_kline_ts.get(target_symbol, 0)
                    if candle['timestamp'] > last_ts:
                        self.last_processed_kline_ts[target_symbol] = candle['timestamp']
                        self.candles[target_symbol].append(candle)
                        self.run_strategy(target_symbol)

                # Real-time Indicators
                if is_closed:
                    temp_history = list(self.candles[target_symbol])
                else:
                    temp_history = list(self.candles[target_symbol])
                    temp_history.append(candle)
                
                cand_data_to_log = candle.copy()
                if len(temp_history) >= 20: 
                    try:
                        df_temp = pd.DataFrame(temp_history)
                        for name, strategy in self.strategies.items():
                            # DECOUPLED: Generic Result Handling
                            res = strategy.calculate(df_temp)
                            if res.indicators:
                                cand_data_to_log.update(res.indicators)
                    except Exception: pass

                self.db.log_candle(cand_data_to_log)

            except Exception as e:
                logger.error(f"Process Kline Error: {e}")

    def run_strategy(self, symbol):
        if len(self.candles[symbol]) < 50: return

        df = pd.DataFrame(self.candles[symbol])
        
        for name, strategy in self.strategies.items():
            # DECOUPLED: Receive StrategyResult
            result = strategy.calculate(df)
            signal = result.signal
            
            # Log Generic Indicators
            if result.indicators:
                 # Human readable log
                 ind_str = " | ".join([f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k,v in result.indicators.items()])
                 if signal:
                     logger.info(f"{'🟢' if signal=='BUY' else '🔴'} SIGNAL {signal} ({name}) | {ind_str}")
                 else:
                     logger.info(f"UPDATE ({symbol}): {ind_str}")

            if signal:
                seq_id = self.db.get_next_sequence('signal_id')
                formatted_id = f"A{seq_id:04d}"
                
                # Decoupled Audit Log: Pass generic indicators as details
                details = {'symbol':symbol, 'signal':signal}
                if result.indicators: details.update(result.indicators)
                if result.metadata: details.update(result.metadata)

                self.db.log_audit('SIGNAL_GENERATED', cause=f"Strategy:{name}", details=details, mode=self.mode, price=df.iloc[-1]['close'], side='BUY' if signal=='BUY' else 'SELL', signal_id=formatted_id)
                self.db.log_signal({'symbol': symbol, 'signal': signal, 'algo': name, 'price': df.iloc[-1]['close'], 'timestamp': int(time.time()*1000)})
                
                self.execute_trade(symbol, signal, name, df.iloc[-1]['close'], signal_id=formatted_id)

        # Log Full Candle (Overwrite real-time)
        # Note: Strategy.calculate already enriched DF columns for backfill/logging?
        # Yes, MaCrossoverStrategy modifies DF. So df.iloc[-1] has columns.
        self.db.log_candle(df.iloc[-1].to_dict())


    def execute_trade(self, symbol, action, algo, price, signal_id=None):
        try:
            pos = self.position_manager.current_position
            action_side = 'long' if action.lower() == 'buy' else 'short'
            
            if pos:
                if pos['side'] == action_side:
                    logger.info(f"Ignoring {action}: Already {pos['side']}")
                    return
                else:
                    enable_flip = self.config['trading'].get('enable_position_flip', False)
                    if enable_flip:
                        logger.info(f"[FLIP] Opposite signal detected: {action} vs {pos['side']}. Flipping position...")
                        self.flip_position_logic(symbol, pos, action, price, signal_id)
                        return
                    else:
                        self.position_manager.close_position(price)
                        return

            if not self.position_manager.can_open_position(symbol): return
            
            amount = self.position_manager.calculate_position_size(symbol, price)
            if not amount: return
            
            # Use 'buy'/'sell' for Orders (vs 'long'/'short' for Positions)
            order_side = action.lower() 
            self.position_manager.place_limit_order(symbol, order_side, price, amount, signal_id=signal_id)
            
        except Exception as e:
            logger.error(f"Execute Trade Error: {e}")

    def flip_position_logic(self, symbol, pos, action, price, signal_id):
        logger.info(f"[FLIP] Flipping {pos['side']} -> {action}")
        success = self.position_manager.close_position_immediate(pos['position_id'], price, reason='flip', signal_id=signal_id)
        
        if success:
             # FIX: Flip Logic Deadlock
             # Wait for position to actually close (confirmed via sync_state)
             # Timeout 30s
             logger.info("[FLIP] Waiting for close confirmation...")
             start_wait = time.time()
             closed_confirmed = False
             
             while time.time() - start_wait < 30:
                 self.position_manager.sync_state(self.latest_prices)
                 if self.position_manager.current_position is None:
                     closed_confirmed = True
                     break
                 time.sleep(0.5)
                 
             if closed_confirmed:
                 logger.info("[FLIP] Close confirmed. Placing new order.")
                 order_side = action.lower()
                 amount = self.position_manager.calculate_position_size(symbol, price)
                 if amount:
                     self.position_manager.place_limit_order(symbol, order_side, price, amount, signal_id=signal_id)
             else:
                 logger.error("[FLIP] Timeout waiting for close. Flip aborted to prevent dual position.")

    def backfill_history(self):
        limit = 500
        logger.info(f"Backfilling {limit} candles...")
        for symbol in self.symbols:
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, self.interval, limit=limit)
                new_candles = []
                for c in ohlcv:
                    new_candles.append({'timestamp': c[0], 'open': float(c[1]), 'high': float(c[2]), 'low': float(c[3]), 'close': float(c[4]), 'volume': float(c[5]), 'symbol': symbol})
                self.candles[symbol].extend(new_candles)
                
                if new_candles:
                    df = pd.DataFrame(self.candles[symbol])
                    # Strategy calculates and Modifies DF (Enrichment)
                    for name, strat in self.strategies.items(): strat.calculate(df)
                    for idx, row in df.iterrows(): self.db.log_candle(row.to_dict())
                    self.latest_prices[symbol] = new_candles[-1]['close']
            except Exception as e:
                logger.error(f"Backfill error {symbol}: {e}")

    def run(self):
        self.backfill_history()
        self.start_websocket()
        logger.info("Bot is listening (Plugin Architecture)...")
        
        counter = 0
        while True:
            time.sleep(10)
            counter += 1
            try:
                self.position_manager.sync_state(self.latest_prices)

                pos = self.position_manager.current_position
                if pos and pos.get('force_close') and self.latest_prices.get(pos['symbol']):
                     self.position_manager.close_position(self.latest_prices[pos['symbol']])
                     pos['force_close'] = False

                for oid in list(self.position_manager.pending_orders.keys()):
                    odata = self.position_manager.pending_orders.get(oid)
                    if odata: self.position_manager.check_order_status(oid, self.latest_prices.get(odata['symbol']))

                self.position_manager.cancel_expired_orders()
                
                for s in self.symbols:
                    if s in self.latest_prices: self.position_manager.update_position_pnl(s, self.latest_prices[s])

            except Exception as e:
                logger.error(f"Loop Error: {e}")

            if counter % 6 == 0:
                uptime = int(time.time() - self.start_time)
                with open("api_logs.txt", "a") as f: f.write(f"{datetime.now()} [HEARTBEAT] Running {uptime}s | {self.latest_prices}\n")

if __name__ == "__main__":
    # Resolve config path relative to this script
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config.json')
    
    if not os.path.exists(config_path):
        print(f"Config not found at: {config_path}")
        # Fallback to current dir if running from root
        if os.path.exists('config.json'):
            config_path = 'config.json'
            
    bot = TradingBot(config_path)
    bot.run()
