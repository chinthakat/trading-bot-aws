import ta
import pandas as pd
from strategies.base import BaseStrategy, StrategyResult

class BollingerMeanReversion(BaseStrategy):
    NAME = "Bollinger_Mean_Reversion"
    PLOT_CONFIG = {
        'overlays': ['bb_high', 'bb_mid', 'bb_low'],
        'oscillators': ['rsi'],
        'colors': ['rgba(255, 0, 0, 0.5)', 'rgba(128, 128, 128, 0.5)', 'rgba(0, 255, 0, 0.5)', 'purple']
    }
    
    def __init__(self, config):
        super().__init__(config)
        # Default parameters for short-term scalping
        self.window = config.get('bb_window', 20)
        self.std_dev = config.get('bb_std', 2.0)
        self.rsi_period = config.get('rsi_period', 14)
        self.rsi_oversold = config.get('rsi_oversold', 30)
        self.rsi_overbought = config.get('rsi_overbought', 70)
        
        # Required for Bot dynamic warmup calculation
        self.long_window = max(self.window, self.rsi_period)

    def calculate(self, df: pd.DataFrame) -> StrategyResult:
        # Ensure we have enough data for the indicators
        if len(df) < max(self.window, self.rsi_period):
            return StrategyResult(indicators={'close': df.iloc[-1]['close']} if len(df) > 0 else {})

        # 1. Calculate Bollinger Bands
        indicator_bb = ta.volatility.BollingerBands(
            close=df['close'], window=self.window, window_dev=self.std_dev
        )
        df['bb_high'] = indicator_bb.bollinger_hband()
        df['bb_low'] = indicator_bb.bollinger_lband()
        df['bb_mid'] = indicator_bb.bollinger_mavg()

        # 2. Calculate RSI
        # 2. Calculate RSI
        # RSI is in momentum module, not trend
        df['rsi'] = ta.momentum.rsi(df['close'], window=self.rsi_period)

        # Get latest values
        last_row = df.iloc[-1]
        close = last_row['close']
        rsi = last_row['rsi']
        bb_high = last_row['bb_high']
        bb_low = last_row['bb_low']

        indicators = {
            'close': close,
            'rsi': rsi,
            'bb_high': bb_high,
            'bb_low': bb_low,
            'bb_mid': last_row['bb_mid']
        }

        signal = None

        # BUY Signal: Price drops below Lower Band AND RSI is Oversold
        if close <= bb_low and rsi <= self.rsi_oversold:
            signal = 'BUY'
        
        # SELL Signal: Price rises above Upper Band AND RSI is Overbought
        elif close >= bb_high and rsi >= self.rsi_overbought:
            signal = 'SELL'

        return StrategyResult(signal=signal, indicators=indicators)