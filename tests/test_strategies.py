import unittest
import pandas as pd
import sys
import os

# Adjust path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'app'))

from strategies import MaCrossoverStrategy

class TestMaCrossover(unittest.TestCase):
    def setUp(self):
        self.config = {'short_period': 2, 'long_period': 5}
        self.strategy = MaCrossoverStrategy(self.config)

    def test_no_signal_not_enough_data(self):
        df = pd.DataFrame({'close': [10, 11, 12]})
        signal = self.strategy.calculate(df)
        self.assertIsNone(signal)

    def test_buy_signal(self):
        # Create a scenario where SMA(2) crosses above SMA(5)
        # Prices: [10, 10, 10, 10, 10, 20, 30]
        # SMA5:   [.,  .,  .,  .,  10, 12, 16]
        # SMA2:   [.,  10, 10, 10, 10, 15, 25] --> Cross happens at the end
        
        # Let's construct simpler exact values
        # Index 0-4: Price 100. SMA5=100. SMA2=100.
        # Index 5: Price 110. SMA5 calc includes last 5. 
        
        prices = [100, 100, 100, 100, 100, 120, 140]
        # t=4: p=100. s2=100, s5=100.
        # t=5: p=120. s2=(100+120)/2=110. s5=(100*4+120)/5=104. s2 > s5. 
        # Prev was s2=s5=100.
        # Use simple logic: Signal generated when close > last_close
        
        df = pd.DataFrame({'close': prices})
        
        # We need to simulate the rolling window.
        # calculate() looks at the DataFrame as a whole and checks the transition at the last row.
        # So we pass the whole history.
        
        signal = self.strategy.calculate(df)
        self.assertEqual(signal, 'BUY')

    def test_sell_signal(self):
        # Opposite scenario
        # Prices start high, go low.
        prices = [100, 100, 100, 100, 100, 80, 60]
        # t=4: s2=100, s5=100.
        # t=5: P=80. s2=90. s5=(100*4+80)/5=96. s2 < s5.
        
        df = pd.DataFrame({'close': prices})
        signal = self.strategy.calculate(df)
        self.assertEqual(signal, 'SELL')

if __name__ == '__main__':
    unittest.main()
