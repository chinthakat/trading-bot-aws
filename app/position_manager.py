import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

class PositionManager:
    """
    Manages trading positions with strict risk controls:
    - Only one position at a time
    - Limit orders with expiry
    - Minimum quantity sizing for conservative risk
    - P&L tracking at account and trade levels
    """
    
    def __init__(self, exchange, db, config):
        self.exchange = exchange
        self.db = db
        
        # Risk Parameters
        self.max_positions = config.get('max_positions', 1)
        self.use_min_quantity = config.get('use_min_quantity', True)
        self.order_ttl_seconds = config.get('order_ttl', 300)  # 5 minutes
        self.max_slippage_pct = config.get('max_slippage_pct', 0.5)
        
        # State
        self.current_position = None
        self.pending_orders = {}  # order_id -> order_data
        
        logger.info(f"PositionManager initialized: max_positions={self.max_positions}, "
                   f"use_min_quantity={self.use_min_quantity}, order_ttl={self.order_ttl_seconds}s")
    
    def can_open_position(self, symbol: str) -> bool:
        """Check if we can open a new position."""
        if self.current_position is not None:
            logger.warning(f"Cannot open position for {symbol}: already have open position")
            return False
        
        # Check pending orders
        if len(self.pending_orders) > 0:
            logger.warning(f"Cannot open position for {symbol}: have pending orders")
            return False
            
        return True
    
    def calculate_position_size(self, symbol: str, price: float) -> float:
        """
        Calculate position size.
        Initially uses exchange minimum for conservative risk management.
        """
        try:
            # Load market info
            if not self.exchange.markets:
                self.exchange.load_markets()
            
            market = self.exchange.market(symbol)
            min_amount = market['limits']['amount']['min']
            
            if self.use_min_quantity:
                logger.info(f"Using minimum quantity for {symbol}: {min_amount}")
                return min_amount
            else:
                # Future: could implement percentage-based sizing here
                return min_amount
                
        except Exception as e:
            logger.error(f"Error calculating position size for {symbol}: {e}")
            return None
    
    def place_limit_order(self, symbol: str, side: str, current_price: float, amount: float) -> Optional[Dict]:
        """
        Place a limit order with slight offset from current price.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            side: "buy" or "sell"
            current_price: Current market price
            amount: Quantity to trade
            
        Returns:
            Order data dict or None if failed
        """
        try:
            # Calculate limit price with small offset to increase fill probability
            # Buy slightly above market, sell slightly below
            offset_pct = 0.001  # 0.1%
            if side.lower() == 'buy':
                limit_price = current_price * (1 + offset_pct)
            else:
                limit_price = current_price * (1 - offset_pct)
            
            # Round to appropriate precision
            market = self.exchange.market(symbol)
            price_precision = market['precision']['price']
            limit_price = self.exchange.price_to_precision(symbol, limit_price)
            
            logger.info(f"Placing {side} limit order: {symbol} @ {limit_price} qty={amount}")
            
            # Place the order
            order = self.exchange.create_limit_order(symbol, side, amount, limit_price)
            
            # Track order
            order_data = {
                'order_id': order['id'],
                'symbol': symbol,
                'side': side,
                'price': limit_price,
                'amount': amount,
                'status': 'pending',
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(seconds=self.order_ttl_seconds)
            }
            
            self.pending_orders[order['id']] = order_data
            
            # Persist to database
            self.db.log_order(order_data)
            
            logger.info(f"Order placed successfully: {order['id']}")
            return order_data
            
        except Exception as e:
            logger.error(f"Failed to place limit order for {symbol}: {e}")
            return None
    
    def check_order_status(self, order_id: str) -> Optional[Dict]:
        """Check if an order has been filled."""
        try:
            order = self.exchange.fetch_order(order_id)
            
            if order['status'] == 'closed':
                # Order filled!
                logger.info(f"Order {order_id} filled at {order['average']}")
                
                # Update pending orders
                if order_id in self.pending_orders:
                    order_data = self.pending_orders.pop(order_id)
                    order_data['status'] = 'filled'
                    order_data['filled_at'] = datetime.now()
                    
                    # Update database
                    self.db.update_order(order_data)
                    
                    # Create position
                    self._create_position_from_order(order_data, order)
                    
                return order
                
            elif order['status'] == 'canceled':
                logger.info(f"Order {order_id} was canceled")
                if order_id in self.pending_orders:
                    self.pending_orders.pop(order_id)
                    
            return order
            
        except Exception as e:
            logger.error(f"Error checking order {order_id}: {e}")
            return None
    
    def cancel_expired_orders(self):
        """Cancel orders that have exceeded TTL."""
        now = datetime.now()
        expired = []
        
        for order_id, order_data in self.pending_orders.items():
            if now > order_data['expires_at']:
                expired.append(order_id)
        
        for order_id in expired:
            try:
                logger.info(f"Canceling expired order: {order_id}")
                self.exchange.cancel_order(order_id)
                
                order_data = self.pending_orders.pop(order_id)
                order_data['status'] = 'expired'
                self.db.update_order(order_data)
                
            except Exception as e:
                logger.error(f"Failed to cancel expired order {order_id}: {e}")
    
    def _create_position_from_order(self, order_data: Dict, exchange_order: Dict):
        """Create a position when an order fills."""
        position = {
            'position_id': str(uuid.uuid4()),
            'symbol': order_data['symbol'],
            'side': 'long' if order_data['side'] == 'buy' else 'short',
            'entry_price': float(exchange_order['average']),
            'quantity': float(exchange_order['filled']),
            'entry_time': datetime.now(),
            'status': 'open',
            'pnl': 0.0
        }
        
        self.current_position = position
        self.db.log_position(position)
        
        logger.info(f"Position opened: {position['position_id']} "
                   f"{position['side']} {position['quantity']} {position['symbol']} @ {position['entry_price']}")
    
    def close_position(self, current_price: float):
        """Close the current open position."""
        if self.current_position is None:
            logger.warning("No open position to close")
            return
        
        pos = self.current_position
        
        # Determine side for exit order (opposite of entry)
        exit_side = 'sell' if pos['side'] == 'long' else 'buy'
        
        # Place limit order to close
        order = self.place_limit_order(pos['symbol'], exit_side, current_price, pos['quantity'])
        
        if order:
            logger.info(f"Closing position {pos['position_id']} with order {order['order_id']}")
    
    def update_position_pnl(self, symbol: str, current_price: float):
        """Update unrealized P&L for open position."""
        if self.current_position is None:
            return
        
        if self.current_position['symbol'] != symbol:
            return
        
        pos = self.current_position
        
        # Calculate unrealized P&L
        if pos['side'] == 'long':
            pnl = (current_price - pos['entry_price']) * pos['quantity']
        else:  # short
            pnl = (pos['entry_price'] - current_price) * pos['quantity']
        
        pos['pnl'] = pnl
        pos['current_price'] = current_price
        
        # Update in database
        self.db.update_position_pnl(pos['position_id'], pnl, current_price)
    
    def get_account_pnl(self) -> Dict:
        """Get account-level P&L statistics."""
        return self.db.get_account_pnl()
