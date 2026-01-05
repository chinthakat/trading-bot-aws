
import time
import logging
import json
import uuid
from threading import Thread
from datetime import datetime
from app.bot import TradingBot
from app.services.db_service import SharedDbService

logger = logging.getLogger(__name__)

class SharedMemoryBot(TradingBot):
    def __init__(self, config_path):
        super().__init__(config_path)
        self.shared_db = SharedDbService()
        logger.info("SharedMemoryBot Initialized with /dev/shm persistence")

    def setup_strategies(self):
        # Core process DOES NOT run strategies.
        # It only executes signals.
        self.strategies = {} 
        logger.info("Core Process: Strategies disabled (running in separate process)")

    def process_kline(self, data):
        """Override: Write Key Market Data to Shared Memory."""
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
                    'interval': self.interval,
                    'open': float(k['o']), 'high': float(k['h']), 'low': float(k['l']), 'close': float(k['c']), 'volume': float(k['v']),
                    'symbol': target_symbol
                }
                
                # 1. Write to Shared DB (Fast IPC)
                self.shared_db.write_candle(candle)
                
                # 2. Persist to DynamoDB (Audit/History) - Only Closed
                if is_closed:
                    self.db.log_candle(candle) # DynamoDB
                    
                # 3. Update Local State (for PositionManager/Execution)
                self.latest_prices[target_symbol] = candle['close']
                
            except Exception as e:
                logger.error(f"Process Kline Error: {e}")

    def hydrate_state(self):
        """Recover state from DynamoDB & Exchange to Shared Memory."""
        try:
            logger.info("Hydrating Shared Memory from Persistent Storage...")
            
            # 1. Backfill Market Data
            # Uses inherited backfill_history which fetches from Binance
            # We need to write these to SharedDB
            self.backfill_history() 
            # Note: backfill_history populates self.candles. We assume self.candles is populated.
            for symbol, candles in self.candles.items():
                for c in candles:
                    c['interval'] = self.interval
                    self.shared_db.write_candle(c)
            logger.info("Market Data Hydrated.")

            # 2. Restore Position State
            # PositionManager.__init__ calls _restore_test_state which pulls from DynamoDB
            if self.position_manager.current_position:
                 pos = self.position_manager.current_position
                 self.shared_db.update_position(pos)
                 logger.info(f"Position Hydrated: {pos['position_id']}")
                 
            logger.info("Hydration Complete.")
            
        except Exception as e:
            logger.error(f"Hydration Failed: {e}")

    def run(self):
        """Override: Main Loop scans Shared DB for Signals."""
        self.hydrate_state() # RESTORE STATE
        self.start_websocket()
        logger.info("Core Service Running... Waiting for Signals in /dev/shm")
        
        counter = 0
        while True:
            try:
                time.sleep(1) # Fast Poll
                counter += 1
                
                # 1. Poll Signals
                signals = self.shared_db.get_new_signals()
                for signal in signals:
                    logger.info(f"Picked up Signal: {signal['signal_id']} {signal['side']} {signal['symbol']}")
                    self.execute_signal(signal)
                    self.shared_db.mark_signal_processed(signal['signal_id'])
                    
                # 2. Sync Positions to Shared DB
                if self.position_manager.current_position:
                    pos = self.position_manager.current_position
                    # Enrich with current price logic if needed
                    self.shared_db.update_position(pos)
                    
                # 3. Sync Account to Shared DB
                try:
                    # Fetch Balance
                    balance = 0.0
                    if self.mode in ['PAPER', 'TEST']:
                        # Call Simulator via PositionManager
                        if self.position_manager.simulator:
                            balance = float(self.position_manager.simulator.get_balance())
                    else:
                        # LIVE (Simplified for USDT)
                        # We might need to cache this to avoid Rate Limits if polling 1s
                        # But fetch_balance is usually lightweight?
                        # Let's throttle it? Every 10s?
                        if counter % 10 == 0:
                            bal = self.exchange.fetch_balance()
                            balance = float(bal.get('total', {}).get('USDT', 0))
                        else:
                            # Keep previous or 0? 
                            # Better to attribute 'self.last_balance'
                            balance = getattr(self, 'last_balance', 0.0)
                        self.last_balance = balance

                    # Calculate Equity
                    # Equity = Balance + Unrealized PnL (This is wrong for Spot Longs where Balance matched Cost)
                    # Correct Logic:
                    # If No Position: Equity = Balance
                    # If Long: Equity = Balance + (Qty * CurrentPrice)
                    # If Short: Equity = Balance - (Qty * CurrentPrice) (Liability)
                    
                    equity = balance
                    unrealized_pnl = 0.0
                    
                    pos = self.position_manager.current_position
                    if pos:
                        qty = float(pos.get('quantity', 0))
                        # Current price from pos or latest_prices
                        current_price = float(pos.get('current_price', 0))
                        if current_price == 0:
                            current_price = float(pos.get('entry_price', 0)) 
                        
                        side = pos['side']
                        unrealized_pnl = float(pos.get('pnl', 0))
                        
                        if side in ['long', 'buy']:
                            equity = balance + (qty * current_price)
                        else:
                            # Short
                            equity = balance - (qty * current_price)
                    
                    # Update DB
                    self.shared_db.update_account(balance, equity, unrealized_pnl)
                    
                except Exception as err:
                    logger.error(f"Account Sync Error: {err}")
                
                # 4. Standard Bot Maintenance (Orders, PnL)
                self.position_manager.sync_state(self.latest_prices)
                for oid in list(self.position_manager.pending_orders.keys()):
                    odata = self.position_manager.pending_orders.get(oid)
                    if odata: 
                        sym = odata['symbol']
                        price = self.latest_prices.get(sym)
                        if counter % 10 == 0:
                            logger.info(f"[DEBUG] Checking Order {oid} for {sym}. Price: {price}")
                        self.position_manager.check_order_status(oid, price)
                if counter % 6 == 0:
                    uptime = int(time.time() - self.start_time)
                    with open("logs/api_logs.txt", "a") as f: f.write(f"{datetime.now()} [HEARTBEAT] Running {uptime}s | {self.latest_prices}\n")
                for s in self.symbols:
                    if s in self.latest_prices: 
                         self.position_manager.update_position_pnl(s, self.latest_prices[s])

            except Exception as e:
                logger.error(f"Core Loop Error: {e}")
                time.sleep(5)

    def execute_signal(self, signal):
        """Execute signal from Shared Memory."""
        symbol = signal['symbol']
        action = signal['side'] # BUY/SELL
        price = signal['price']
        algo = signal['strategy_name']
        sig_id = signal['signal_id']
        
        # Persist Signal to DynamoDB (Requirement)
        self.db.log_signal({'symbol': symbol, 'signal': action, 'algo': algo, 'price': price, 'timestamp': signal['timestamp']})
        
        # Execute
        self.execute_trade(symbol, action, algo, price, signal_id=sig_id)

if __name__ == "__main__":
    import os
    # Resolve config
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'config.json')
    
    bot = SharedMemoryBot(config_path)
    bot.run()
