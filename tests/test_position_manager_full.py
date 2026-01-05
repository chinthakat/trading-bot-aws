
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from datetime import datetime
from decimal import Decimal

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))

from app.position_manager import PositionManager

class TestPositionManagerFull(unittest.TestCase):
    def setUp(self):
        # Mocks
        self.mock_exchange = MagicMock()
        self.mock_db = MagicMock()
        
        # Config
        self.config = {
            'mode': 'TEST',
            'base_currency': 'USDT',
            'risk_per_trade': 1.0, # 1%
            'risk_management': {
                'max_positions': 1,
                'use_min_quantity': False,
                'min_quantity_check': False, # Legacy/Extra
                'sl_pct': 0.02,
                'tp_pct': 0.04,
                'max_slippage_pct': 0.001,
                'commission_rate': 0.001
            }
        }
        
        # DB Mocks
        self.mock_db.get_test_account_summary.return_value = {'balance': 10000.0, 'total_fees': 0.0}
        self.mock_db.get_active_position.return_value = None # Fix: No active local position
        
        # Initialize PositionManager
        self.pm = PositionManager(self.mock_exchange, self.mock_db, self.config, mode='TEST')
        self.pm.simulator.positions = {} # ensure clean start (Dict)
        
        # Enable Logging
        import logging
        logging.basicConfig(level=logging.INFO)
        
        # Exchange Mocks
        
        # Exchange Mocks
        self.mock_exchange.market.return_value = {
            'limits': {'amount': {'min': 0.001}},
            'precision': {'amount': 4, 'price': 2}
        }
        self.mock_exchange.price_to_precision.side_effect = lambda s, p: round(p, 2)
        
    def test_calculate_position_size(self):
        """Test Risk-Based Sizing"""
        # Price 100, Balance 10000, Risk 1% ($100)
        # SL 2%. Risk/Unit = 100 * 0.02 = 2.
        # Qty = 100 / 2 = 50.
        qty = self.pm.calculate_position_size('BTC/USDT', 100.0)
        print(f"DEBUG: Qty={qty}, RiskPerTrade={self.pm.risk_per_trade}, SLPct={self.pm.sl_pct}")
        self.assertAlmostEqual(qty, 50.0)

    def test_open_position_flow(self):
        """Test Opening a Position Simulates Correctly"""
        symbol = 'BTC/USDT'
        price = 50000.0
        
        print(f"DEBUG: CurrentPos={self.pm.current_position}")
        # 1. Check can open
        self.assertTrue(self.pm.can_open_position(symbol))
        
        # 2. Place Order
        order = self.pm.place_limit_order(symbol, 'buy', price, 0.1, 'entry')
        
        # 3. Verify Order Created in Simulator
        self.assertIsNotNone(order)
        self.assertEqual(order['status'], 'pending') # Simulator returns pending
        
        # 4. Fill Order
        self.pm.check_order_status(order['order_id'], price)
        
        # 5. Verify Position Created
        self.assertIsNotNone(self.pm.current_position)
        self.assertEqual(self.pm.current_position['symbol'], symbol)
        self.assertEqual(len(self.pm.simulator.positions), 1)
        
        # 6. Verify DB Persistence
        self.mock_db.log_position.assert_called()

    def test_flip_position_logic(self):
        """Test Long -> Short Flip"""
        # 1. Setup Active Long Position
        pos_id = 'pos_1'
        self.pm.simulator.positions = {
            'BTC/USDT': {
                'position_id': pos_id,
                'symbol': 'BTC/USDT',
                'side': 'long',
                'quantity': 1.0,
                'entry_price': 50000.0,
                'current_price': 50000.0,
                'status': 'open',
                'entry_commission': 50.0 # arbitrary
            }
        }
        self.pm.current_position = self.pm.simulator.positions['BTC/USDT']
        self.pm.simulator.balance = 100.0 # Low balance (invested)
        # Mock DB to return low balance too (since PM reads DB)
        self.mock_db.get_test_account_summary.return_value = {'balance': 100.0, 'total_fees': 0.0}
        
        # 2. Attempt Flip (Close Long via Immediate)
        # Reason: Flip requires exiting first.
        # This creates a pending EXIT order.
        success = self.pm.close_position_immediate(pos_id, 51000.0, reason='flip') 
        self.assertTrue(success)
        
        # 2b. Calculate Size for New Short (Bug Reproduction)
        # Should be based on Equity (100 + ~51000 value), not Cash (100).
        # If Logic is wrong, it returns Min Qty.
        # If Risk=1%, Equity=51100. RiskAmt=511. SL=2% (Price=51000 -> Risk/Unit=1020).
        # Qty = 511 / 1020 = 0.5.
        
        # Current Logic (Broken): Bal=100. RiskAmt=1. Qty ~ 0.
        qty = self.pm.calculate_position_size('BTC/USDT', 51000.0)
        print(f"DEBUG: Flip Qty={qty} (Expected ~0.5)")
        
        # EXPECT FAILURE HERE UNTIL FIXED
        self.assertGreater(qty, 0.1, "Quantity too small (Cash Bug)")
        
        # Verify Pending Order exists
        self.assertEqual(len(self.pm.simulator.pending_orders), 1)
        order_id = list(self.pm.simulator.pending_orders.keys())[0]
        
        # 3. Simulate Fill of Exit Order
        # Sell @ 51000 (Market price)
        # Limit price was 51000 * 0.99 = 50490. Market 51000. 51000 >= 50490. Fill.
        filled = self.pm.check_order_status(order_id, 51000.0)
        self.assertTrue(filled)
        
        # 4. Verify Close
        # Position should be removed from 'positions'
        self.assertNotIn('BTC/USDT', self.pm.simulator.positions)
        self.assertEqual(len(self.pm.simulator.closed_positions), 1)
        
        # 5. Verify Balance Update
        # PnL = (51000 - 50000) * 1 = 1000.
        # Fees omitted in simple logic or calc?
        # Simulator _execute_fill deducts fees.
        # Old Bal 10000.
        # This test ensures flow is correct.
        self.assertGreater(self.pm.simulator.balance, 10000.0)

    def test_cash_calculation(self):
        """Test Equity and Cash Updating"""
        # 1. Buy 1 BTC @ 1000 (Fee 1 = 1usd)
        self.pm.simulator.balance = 10000.0
        self.pm.simulator.total_fees = 0.0
        
        # Place Order -> Fill
        order = self.pm.simulator.place_limit_order('BTC/USDT', 'buy', 1000.0, 1.0)
        self.pm.simulator._execute_fill(order, 1000.0)
        
        # Balance = 10000 - 1000 (Cost) - 1 (Comm) = 8999
        expected_balance = 10000.0 - 1000.0 - 1.0
        self.assertEqual(self.pm.simulator.balance, expected_balance)
        
        # 2. Sell 1 BTC @ 1200 (Fee 1.2 = 1.2usd)
        order2 = self.pm.simulator.place_limit_order('BTC/USDT', 'sell', 1200.0, 1.0)
        self.pm.simulator._execute_fill(order2, 1200.0)
        
        # Revenue = 1200. Comm = 1.2.
        # Balance = 8999 + 1200 - 1.2 = 10197.8
        self.assertAlmostEqual(self.pm.simulator.balance, 10197.8)

if __name__ == '__main__':
    unittest.main()
