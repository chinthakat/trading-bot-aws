
import ta
from strategies.base import BaseStrategy, StrategyResult

class MaCrossoverStrategy(BaseStrategy):
    NAME = "MA_Crossover"
    
    def __init__(self, config):
        super().__init__(config)
        self.short_window = config.get('short_period', 10)
        self.long_window = config.get('long_period', 100)

    def calculate(self, df) -> StrategyResult:
        # Require enough data
        if len(df) < self.long_window:
            # Return empty result with current close for logging if possible
            return StrategyResult(indicators={'close': df.iloc[-1]['close']} if len(df)>0 else {})

        # Calculate Indicators
        close = df['close']
        sma_short = ta.trend.sma_indicator(close, window=self.short_window)
        sma_long = ta.trend.sma_indicator(close, window=self.long_window)
        
        # Enrich DF for Backfill/History
        df['sma_short'] = sma_short
        df['sma_long'] = sma_long
        
        # Prepare Indicator values for the last row
        last_s = sma_short.iloc[-1]
        last_l = sma_long.iloc[-1]
        
        indicators = {
            'sma_short': last_s,
            'sma_long': last_l,
            'close': close.iloc[-1]
        }
        
        # Check Crossover
        prev_s = sma_short.iloc[-2]
        prev_l = sma_long.iloc[-2]
        
        signal = None
        
        # BUY: Short crosses above Long
        if prev_s <= prev_l and last_s > last_l:
            signal = 'BUY'
        
        # SELL: Short crosses below Long
        elif prev_s >= prev_l and last_s < last_l:
            signal = 'SELL'
            
        return StrategyResult(signal=signal, indicators=indicators)
