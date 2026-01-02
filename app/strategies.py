import pandas as pd
import ta

class BaseStrategy:
    def __init__(self, config):
        self.config = config
        self.name = "BaseStrategy"

    def calculate(self, df):
        """
        Calculates indicators and returns a signal.
        df: Pandas DataFrame with columns ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        Returns: 'BUY', 'SELL', or None
        """
        raise NotImplementedError("Strategies must implement calculate method")

class MaCrossoverStrategy(BaseStrategy):
    def __init__(self, config):
        super().__init__(config)
        self.name = "MA_Crossover"
        self.short_window = config.get('short_period', 10)
        self.long_window = config.get('long_period', 100)

    def calculate(self, df):
        if len(df) < self.long_window:
            return None

        # Calculate Indicators
        df['sma_short'] = ta.trend.sma_indicator(df['close'], window=self.short_window)
        df['sma_long'] = ta.trend.sma_indicator(df['close'], window=self.long_window)
        
        # Get last two rows to check for crossover
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]

        # Check for Crossover
        # BUY: Short crosses above Long
        if prev_row['sma_short'] <= prev_row['sma_long'] and last_row['sma_short'] > last_row['sma_long']:
            return 'BUY'
        
        # SELL: Short crosses below Long
        if prev_row['sma_short'] >= prev_row['sma_long'] and last_row['sma_short'] < last_row['sma_long']:
            return 'SELL'
            
        return None

class StrategyRegistry:
    _strategies = {
        "MA_Crossover": MaCrossoverStrategy
    }

    @classmethod
    def get_strategy(cls, name, config):
        strategy_class = cls._strategies.get(name)
        if strategy_class:
            return strategy_class(config)
        raise ValueError(f"Strategy {name} not found")
