
import logging
import uuid
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from decimal import Decimal

logger = logging.getLogger(__name__)

class PaperTradingSimulator:
    """
    Simulates exchange behavior for TEST mode.
    - Maintains virtual balance
    - Simulates instant order fills at limit prices (or marketable limit)
    - Persists state to DynamoDB 'test_*' tables via injected DB instance
    """
    
    def __init__(self, initial_balance: float, db=None, commission_rate=0.001):
        self.balance = float(initial_balance)
        self.db = db  # Persistence instance
        self.commission_rate = float(commission_rate)
        self.positions = {}  # symbol -> position dict
        self.pending_orders = {}  # order_id -> order dict
        self.filled_orders = []
        self.closed_positions = []
        
        logger.info(f"Paper Trading Simulator initialized with ${self.balance:,.2f} (Comm: {self.commission_rate*100}%)")

    def load_state(self, positions: List[Dict], orders: List[Dict]):
        """Load state from DB (called by PositionManager)."""
        for pos in positions:
            self.positions[pos['symbol']] = pos
            
        for order in orders:
            self.pending_orders[order['order_id']] = order
            
        logger.info(f"Simulator loaded state: {len(self.positions)} positions, {len(self.pending_orders)} orders")

    def place_limit_order(self, symbol: str, side: str, price: float, amount: float, expires_at: datetime = None) -> Dict:
        """
        Place a virtual limit order.
        """
        order_id = str(uuid.uuid4())
        timestamp = datetime.now()
        
        # Default Expiration: 24h if not provided
        if not expires_at:
            expires_at = timestamp + timedelta(hours=24)
            
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'side': side,
            'price': float(price),
            'amount': float(amount),
            'status': 'pending',
            'created_at': timestamp,
            'expires_at': expires_at,
            'filled_at': None,
            'fill_price': None
        }
        
        self.pending_orders[order_id] = order
        
        # Persist to DB
        if self.db:
            self._persist_order(order)
            
        logger.info(f"[PAPER] Placed {side} limit order: {symbol} @ ${price:.2f} qty={amount}")
        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if order_id in self.pending_orders:
            order = self.pending_orders.pop(order_id)
            order['status'] = 'canceled'
            
            if self.db:
                self.db.update_order_status(order_id, 'canceled', mode='TEST')
                
            logger.info(f"[PAPER] Canceled order {order_id}")
            return True
        return False

    def simulate_fill(self, order_id: str, current_price: float) -> bool:
        """
        Check fill conditions.
        Buy Limit: Fill if Market <= Limit
        Sell Limit: Fill if Market >= Limit
        """
        if order_id not in self.pending_orders:
            return False
            
        order = self.pending_orders[order_id]
        limit_price = order['price']
        side = order['side']
        
        should_fill = False
        
        # logic: 
        # If Limit Buy @ 100. Market is 99. Fill.
        # If Limit Buy @ 100. Market is 101. No Fill.
        
        if side == 'buy':
            if current_price <= limit_price:
                should_fill = True
        elif side == 'sell':
            if current_price >= limit_price:
                should_fill = True
                
        if should_fill:
            # Execute Fill
            logger.info(f"[SIMULATOR] Filling {side} {order_id}. Limit:{limit_price}, Market:{current_price}")
            self._execute_fill(order, current_price)
            return True
            
        return False

    def _execute_fill(self, order: Dict, fill_price: float):
        """Execute fill, update state, write DB."""
        order_id = order['order_id']
        symbol = order['symbol']
        side = order['side']
        amount = order['amount']
        
        # 1. Update Order
        order['status'] = 'filled'
        order['filled_at'] = datetime.now()
        order['fill_price'] = float(fill_price)
        
        self.filled_orders.append(order)
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
            
        if self.db:
            self.db.update_order_status(order_id, 'filled', mode='TEST')
            # Ideally update fill_price too, but update_order_status is simple.
            # Maybe overwrite full item?
            self._persist_order(order)

        # 2. Update Balance & Positions
        # 2. Update Balance & Positions
        cost = fill_price * amount
        commission = cost * self.commission_rate
        
        order['commission'] = commission
        
        if side == 'buy':
            self.balance -= (cost + commission)
            
            # Create/Update Position
            if symbol in self.positions:
                pos = self.positions[symbol]
                if pos['side'] == 'long':
                     # Avg Down
                     total_qty = pos['quantity'] + amount
                     # Weighted Avg Price
                     old_val = pos['entry_price'] * pos['quantity']
                     new_val = fill_price * amount
                     avg_price = (old_val + new_val) / total_qty
                     
                     pos['quantity'] = total_qty
                     pos['entry_price'] = avg_price
                     # Accumulate Entry Comm
                     pos['entry_commission'] = pos.get('entry_commission', 0.0) + commission
                else:
                    # Closing Short (Partial or Full)
                    remaining = pos['quantity'] - amount
                    if remaining <= 1e-9: # Epsilon for float comparison
                        # Full Close
                        # Gross PnL - Entry Comm - Exit Comm
                        gross_pnl = (pos['entry_price'] - fill_price) * pos['quantity'] # Short PnL
                        entry_comm = pos.get('entry_commission', 0.0)
                        net_pnl = gross_pnl - entry_comm - commission
                        
                        pos['status'] = 'closed'
                        pos['exit_price'] = fill_price
                        pos['exit_time'] = datetime.now()
                        pos['pnl'] = net_pnl
                        pos['exit_commission'] = commission
                        
                        self.closed_positions.append(pos)
                        del self.positions[symbol]
                        
                        if self.db:
                             self.db.update_position_status(pos['position_id'], 'closed', mode='TEST')
                             self.db.update_position_pnl(pos['position_id'], pnl, fill_price, mode='TEST')
                    else:
                        # Partial Close
                        pos['quantity'] = remaining
                        if self.db:
                            self.db.log_position(pos, mode='TEST') # Update qty
            else:
                # New Long
                new_pos = {
                    'position_id': str(uuid.uuid4()),
                    'symbol': symbol,
                    'side': 'long',
                    'entry_price': float(fill_price),
                    'quantity': float(amount),
                    'entry_time': datetime.now(),
                    'status': 'open',
                    'pnl': 0.0,
                    'entry_commission': commission,
                    'stop_loss': order.get('stop_loss'),
                    'take_profit': order.get('take_profit')
                }
                self.positions[symbol] = new_pos
                if self.db:
                    self.db.log_position(new_pos, mode='TEST')

        elif side == 'sell':
             self.balance += (cost - commission)
             # Check for Long to Close
             if symbol in self.positions and self.positions[symbol]['side'] == 'long':
                  # Close Long
                  pos = self.positions[symbol]
                  # Gross PnL - Entry Comm - Exit Comm
                  gross_pnl = (fill_price - pos['entry_price']) * amount
                  entry_comm = pos.get('entry_commission', 0.0)
                  net_pnl = gross_pnl - entry_comm - commission
                  
                  # Assume full close for MVP simplicity (or check qty)
                  pos['status'] = 'closed'
                  pos['exit_price'] = fill_price
                  pos['exit_time'] = datetime.now()
                  pos['pnl'] = net_pnl
                  pos['exit_commission'] = commission
                  
                  self.closed_positions.append(pos)
                  del self.positions[symbol]
                  
                  if self.db:
                      self.db.update_position_status(pos['position_id'], 'closed', mode='TEST')
                      self.db.update_position_pnl(pos['position_id'], net_pnl, fill_price, mode='TEST')
             
             else:
                  # New Short
                  new_pos = {
                    'position_id': str(uuid.uuid4()),
                    'symbol': symbol,
                    'side': 'short',
                    'entry_price': float(fill_price),
                    'quantity': float(amount),
                    'entry_time': datetime.now(),
                    'status': 'open',
                    'pnl': 0.0,
                    'entry_commission': commission,
                    'stop_loss': order.get('stop_loss'),
                    'take_profit': order.get('take_profit')
                  }
                  self.positions[symbol] = new_pos
                  if self.db:
                      self.db.log_position(new_pos, mode='TEST')

        logger.info(f"[PAPER] Fill executed: {side} {amount} {symbol} @ {fill_price}")
        
        if self.db:
             self.db.update_test_account_balance(self.balance)


    def get_position(self, symbol: str) -> Optional[Dict]:
        """Retrieve open position for symbol."""
        return self.positions.get(symbol)
        
    def _persist_order(self, order: Dict):
        """Helper to write order to DB."""
        if not self.db: return
        try:
            # Format for DynamoDB (Decimal, timestamps)
            item = order.copy()
            item['created_at'] = int(item['created_at'].timestamp() * 1000)
            if item.get('expires_at'):
                item['expires_at'] = int(item['expires_at'].timestamp() * 1000)
            if item.get('filled_at'):
                item['filled_at'] = int(item['filled_at'].timestamp() * 1000)
                
            for k, v in item.items():
                if isinstance(v, float):
                    item[k] = Decimal(str(v))
            
            self.db.test_orders_table.put_item(Item=item)
        except Exception as e:
            logger.error(f"[PAPER] DB Persist Error: {e}")

