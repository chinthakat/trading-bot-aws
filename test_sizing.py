
import sys
sys.path.append('app')
import unittest
from unittest.mock import MagicMock
from app.position_manager import PositionManager

class TestRiskManagement(unittest.TestCase):
    def test_sizing(self):
        # Config: 3% Risk, 2% SL
        config = {
            'risk_management': {
                'risk_per_trade': 3.0,
                'sl_pct': 0.02,
                'use_min_quantity': False
            },
            'commission_rate': 0.001
        }
        
        # Mocks
        exchange = MagicMock()
        exchange.markets = {'BTC/USDT': {'limits': {'amount': {'min': 0.00001}}}}
        exchange.market.return_value = {'limits': {'amount': {'min': 0.00001}}}
        
        db = MagicMock()
        # Mock Balance: $10,000
        db.get_test_account_balance.return_value = {'balance': 10000.0}
        
        pm = PositionManager(exchange, db, config['risk_management'], mode="TEST")
        
        # Test Case 1: Standard
        # Price = 50,000
        # Risk Amount = 10,000 * 0.03 = 300
        # Risk Per Unit = 50,000 * 0.02 = 1,000
        # Qty = 300 / 1000 = 0.3
        
        qty = pm.calculate_position_size('BTC/USDT', 50000.0)
        print(f"Qty: {qty}")
        self.assertAlmostEqual(qty, 0.3, places=2)
        
        # Test Case 2: Cap at Balance
        # Price = 50,000
        # Risk Amount = 300
        # SL = 0.1% (Very tight) -> Risk Per Unit = 50
        # Qty = 300 / 50 = 6 BTC
        # Cost = 6 * 50,000 = 300,000 (Exceeds 10,000)
        # Cap = 10,000 / 50,000 * 0.99 = 0.198
        
        pm.sl_pct = 0.001
        qty_cap = pm.calculate_position_size('BTC/USDT', 50000.0)
        print(f"Qty Cap: {qty_cap}")
        self.assertLess(qty_cap, 0.2)
        self.assertGreater(qty_cap, 0.19)

if __name__ == '__main__':
    unittest.main()
