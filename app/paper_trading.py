import logging
import uuid
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class PaperTradingSimulator:
    """
    Simulates exchange behavior for TEST mode.
    - Maintains virtual balance ($10K initial)
    - Simulates instant order fills at limit prices
    - Tracks virtual positions and P&L
    - Uses real price data for accurate simulation
    """
    
    def __init__(self, initial_balance: float):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions = {}  # symbol -> position dict
        self.pending_orders = {}  # order_id -> order dict
        self.filled_orders = []
        
        logger.info(f"Paper Trading Simulator initialized with ${initial_balance:,.2f}")
    
    def get_balance(self) -> float:
        """Get current cash balance."""
        return self.balance
    
    def get_equity(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total equity (balance + unrealized P&L).
        
        Args:
            current_prices: Dict of symbol -> current_price
        """
        unrealized_pnl = 0.0
        
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                if position['side'] == 'long':
                    pnl = (current_price - position['entry_price']) * position['quantity']
                else:  # short
                    pnl = (position['entry_price'] - current_price) * position['quantity']
                unrealized_pnl += pnl
        
        return self.balance + unrealized_pnl
    
    def place_limit_order(self, symbol: str, side: str, price: float, amount: float) -> Dict:
        """
        Place a virtual limit order.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            side: "buy" or "sell"
            price: Limit price
            amount: Quantity
            
        Returns:
            Order data dict
        """
        order_id = str(uuid.uuid4())
        
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'side': side,
            'price': price,
            'amount': amount,
            'status': 'pending',
            'created_at': datetime.now()
        }
        
        self.pending_orders[order_id] = order
        
        logger.info(f"[PAPER] Placed {side} limit order: {symbol} @ ${price:.2f} qty={amount}")
        
        return order
    
    def simulate_fill(self, order_id: str, current_price: float) -> bool:
        """
        Check if order should be filled based on current price.
        For simplicity, fills instantly if price crosses limit.
        
        Args:
            order_id: Order to check
            current_price: Current market price
            
        Returns:
            True if order was filled
        """
        if order_id not in self.pending_orders:
            return False
        
        order = self.pending_orders[order_id]
        limit_price = order['price']
        side = order['side']
        
        # Check if price crossed limit
        should_fill = False
        if side == 'buy' and current_price <= limit_price:
            should_fill = True
        elif side == 'sell' and current_price >= limit_price:
            should_fill = True
        
        if should_fill:
            self._execute_fill(order, current_price)
            return True
        
        return False
    
    def _execute_fill(self, order: Dict, fill_price: float):
        """Execute order fill and update balances/positions."""
        order_id = order['order_id']
        symbol = order['symbol']
        side = order['side']
        amount = order['amount']
        
        # Update order status
        order['status'] = 'filled'
        order['filled_at'] = datetime.now()
        order['fill_price'] = fill_price
        
        # Move to filled orders
        self.filled_orders.append(order)
        del self.pending_orders[order_id]
        
        # Update balance and positions
        if side == 'buy':
            # Deduct cost from balance
            cost = fill_price * amount
            self.balance -= cost
            
            # Create or update position
            if symbol in self.positions:
                # Average down (shouldn't happen with max_positions=1, but handle it)
                pos = self.positions[symbol]
                total_qty = pos['quantity'] + amount
                avg_price = ((pos['entry_price'] * pos['quantity']) + (fill_price * amount)) / total_qty
                pos['quantity'] = total_qty
                pos['entry_price'] = avg_price
            else:
                self.positions[symbol] = {
                    'position_id': str(uuid.uuid4()),
                    'symbol': symbol,
                    'side': 'long',
                    'entry_price': fill_price,
                    'quantity': amount,
                    'entry_time': datetime.now(),
                    'status': 'open'
                }
            
            logger.info(f"[PAPER] ✅ BUY filled: {amount} {symbol} @ ${fill_price:.2f} | Balance: ${self.balance:.2f}")
            
        else:  # sell
            # Add proceeds to balance
            proceeds = fill_price * amount
            self.balance += proceeds
            
            # Close or reduce position
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # Calculate realized P&L
                realized_pnl = (fill_price - pos['entry_price']) * amount
                
                pos['quantity'] -= amount
                
                if pos['quantity'] <= 0:
                    # Position closed
                    pos['status'] = 'closed'
                    pos['exit_price'] = fill_price
                    pos['exit_time'] = datetime.now()
                    pos['pnl'] = realized_pnl
                    
                    # Remove from active positions
                    del self.positions[symbol]
                
                logger.info(f"[PAPER] ✅ SELL filled: {amount} {symbol} @ ${fill_price:.2f} | P&L: ${realized_pnl:+.2f} | Balance: ${self.balance:.2f}")
            else:
                logger.warning(f"[PAPER] SELL order filled but no position exists for {symbol}")
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get current position for symbol."""
        return self.positions.get(symbol)
    
    def has_open_position(self, symbol: str) -> bool:
        """Check if there's an open position for symbol."""
        return symbol in self.positions
    
    def get_stats(self, current_prices: Dict[str, float]) -> Dict:
        """Get account statistics."""
        equity = self.get_equity(current_prices)
        total_pnl = equity - self.initial_balance
        
        return {
            'balance': self.balance,
            'equity': equity,
            'total_pnl': total_pnl,
            'pnl_pct': (total_pnl / self.initial_balance) * 100,
            'open_positions': len(self.positions),
            'pending_orders': len(self.pending_orders)
        }
