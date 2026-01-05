
import argparse
import time
import logging
import json
import pandas as pd
import uuid
from app.services.db_service import SharedDbService
from app.strategy_loader import StrategyLoader
import ta

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class StrategyRunner:
    def __init__(self, strategy_name, symbol, interval, params):
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.interval = interval
        self.db = SharedDbService()
        
        # Load Strategy
        # We might need to mock config
        config = params
        self.strategy = StrategyLoader.get_strategy(strategy_name, config)
        logger.info(f"Strategy {strategy_name} initialized for {symbol}")

    def run(self):
        logger.info(f"Starting Strategy Loop for {self.strategy_name}...")
        last_processed_ts = 0
        loop_counter = 0
        import os
        
        while True:
            try:
                loop_counter += 1
                if loop_counter % 10 == 0:
                     self.db.update_heartbeat(f"strat_{self.strategy_name}_{self.symbol}", "online", {'pid': os.getpid()})

                # 1. Fetch Data
                candles = self.db.get_recent_candles(self.symbol, limit=200)
                if not candles:
                    time.sleep(1)
                    continue
                
                # Check if we have new data
                latest_ts = candles[-1]['timestamp']
                # If we want to run EVERY tick, remove this check.
                # But for now, let's limit to 1 run per new candle update? Or 1s throttle is enough?
                # The issue is REPEATING signal for same candle condition.
                
                df = pd.DataFrame(candles)
                
                # 2. Run Logic
                result = self.strategy.calculate(df)
                
                # 3. Handle Signal
                if result.signal:
                    # Deduplication:
                    # If we already signaled for this candle timestamp (or previous one?), skip.
                    # Usually signal applies to the trigger candle.
                    trigger_ts = df.iloc[-1]['timestamp']
                    
                    if trigger_ts > last_processed_ts:
                        logger.info(f"Generated Signal: {result.signal} @ {df.iloc[-1]['close']}")
                        
                        # Create Signal Object
                        signal_id = str(uuid.uuid4())
                        sig = {
                            'signal_id': signal_id,
                            'strategy_name': self.strategy_name,
                            'symbol': self.symbol,
                            'side': result.signal,
                            'price': df.iloc[-1]['close'],
                            'timestamp': int(time.time() * 1000),
                            'status': 'NEW',
                            'metadata': result.metadata or result.indicators
                        }
                        self.db.write_signal(sig)
                        last_processed_ts = trigger_ts
                    
                # Sleep to prevent tight loop
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Strategy Loop Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True, help="Name of strategy class")
    parser.add_argument("--symbol", required=True, help="Trading Pair")
    parser.add_argument("--interval", default="1m", help="Timeframe")
    parser.add_argument("--params", default="{}", help="JSON params")
    
    args = parser.parse_args()
    params = json.loads(args.params)
    
    runner = StrategyRunner(args.strategy, args.symbol, args.interval, params)
    runner.run()
