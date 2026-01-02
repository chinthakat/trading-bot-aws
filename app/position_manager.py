import logging
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List
from paper_trading import PaperTradingSimulator

logger = logging.getLogger(__name__)

class PositionManager:
    """
    Manages trading positions with strict risk controls:
    - Only one position at a time
    - Limit orders with expiry
    - Minimum quantity sizing for conservative risk
    - P&L tracking at account and trade levels
    """
    
    def __init__(self, exchange, db, config, mode="TEST"):
        self.exchange = exchange
        self.db = db
        self.mode = mode
        
        # Risk Parameters
        self.max_positions = config.get('max_positions', 1)
        self.use_min_quantity = config.get('use_min_quantity', True)
        self.order_ttl_seconds = config.get('order_ttl', 300)  # 5 minutes
        self.max_slippage_pct = config.get('max_slippage_pct', 0.5)
        
        # Mode-specific initialization
        if mode == "TEST":
            initial_balance = config.get('test_initial_balance', 10000.0)
            self.simulator = PaperTradingSimulator(initial_balance)
            # Use test tables
            self.positions_table_name = 'test_positions'
            self.orders_table_name = 'test_orders'
            logger.info(f"PositionManager in TEST mode with ${initial_balance:,.2f} paper balance")
        else:  # LIVE
            self.simulator = None
            self.positions_table_name = 'positions'
            self.orders_table_name = 'orders'
            logger.info(f"PositionManager in LIVE mode - REAL TRADES ENABLED")
        
        # State
        self.current_position = None
        self.pending_orders = {}  # order_id -> order_data
        
        logger.info(f"Risk controls: max_positions={self.max_positions}, "
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
        Routes to simulator in TEST mode or real exchange in LIVE mode.
        """
        try:
            # Calculate limit price with small offset
            offset_pct = 0.001  # 0.1%
            if side.lower() == 'buy':
                limit_price = current_price * (1 + offset_pct)
            else:
                limit_price = current_price * (1 - offset_pct)
            
            if self.mode == "TEST":
                # Paper trading - use simulator
                order_data = self.simulator.place_limit_order(symbol, side, limit_price, amount)
                self.pending_orders[order_data['order_id']] = order_data
                
                # Log to test tables - use appropriate method or direct table access
                try:
                    # Convert datetime to timestamp for DynamoDB
                    order_log = order_data.copy()
                    order_log['created_at'] = int(order_data['created_at'].timestamp() * 1000)
                    if 'expires_at' in order_log:
                        order_log['expires_at'] = int(order_data['expires_at'].timestamp() * 1000)
                    
                    # Log to test orders table
                    self.db.test_orders_table.put_item(Item=order_log)
                    logger.info(f"[TEST] Order logged to test_orders table: {order_data['order_id']}")
                except Exception as e:
                    logger.error(f"Failed to log test order to DB: {e}")
                
                return order_data
                
            else:  # LIVE mode
                # Round to appropriate precision
                market = self.exchange.market(symbol)
                limit_price = self.exchange.price_to_precision(symbol, limit_price)
                
                logger.info(f"[LIVE] Placing {side} limit order: {symbol} @ {limit_price} qty={amount}")
                
                # Place real order
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
                self.db.log_order(order_data)
                
                logger.info(f"[LIVE] Order placed successfully: {order['id']}")
                return order_data
                
        except Exception as e:
            logger.error(f"Failed to place limit order for {symbol}: {e}")
            return None
    
    def check_order_status(self, order_id: str, current_price: float = None) -> Optional[Dict]:
        """Check if an order has been filled."""
        try:
            if self.mode == "TEST":
                if not current_price:
                    return None
                    
                # Simulate fill
                filled = self.simulator.simulate_fill(order_id, current_price)
                
                if filled:
                    # Retrieve filled order from simulator
                    # It sits in filled_orders list, manual search needed or better lookup?
                    # Simulator moves it to self.filled_orders and deletes from pending
                    # We can find it in self.simulator.filled_orders
                    filled_order = None
                    for o in self.simulator.filled_orders:
                        if o['order_id'] == order_id:
                            filled_order = o
                            break
                    
                    if filled_order:
                        logger.info(f"[TEST] Order {order_id} filled at {filled_order['fill_price']}")
                        
                        # Update pending orders (remove from local pending)
                        if order_id in self.pending_orders:
                            self.pending_orders.pop(order_id)
                        
                        # Update DB: test_orders
                        try:
                            # Convert datetimes
                            order_log = filled_order.copy()
                            order_log['created_at'] = int(order_log['created_at'].timestamp() * 1000)
                            if 'filled_at' in order_log:
                                order_log['filled_at'] = int(order_log['filled_at'].timestamp() * 1000)
                            if 'expires_at' in order_log:
                                order_log['expires_at'] = int(order_log['expires_at'].timestamp() * 1000)
                            
                            self.db.test_orders_table.put_item(Item=order_log)
                        except Exception as e:
                            logger.error(f"Failed to persist filled test order: {e}")

                        # Update DB: test_positions
                        # Find the position for this symbol
                        symbol = filled_order['symbol']
                        position = self.simulator.get_position(symbol)
                        
                        if position:
                            try:
                                pos_log = position.copy()
                                pos_log['entry_time'] = int(pos_log['entry_time'].timestamp() * 1000)
                                if 'exit_time' in pos_log and pos_log['exit_time']:
                                    pos_log['exit_time'] = int(pos_log['exit_time'].timestamp() * 1000)
                                
                                # Convert floats to Decimal
                                for k, v in pos_log.items():
                                    if isinstance(v, float):
                                        pos_log[k] = Decimal(str(v))
                                
                                self.db.test_positions_table.put_item(Item=pos_log)
                                logger.info(f"[TEST] Position persisted for {symbol}")
                            except Exception as e:
                                logger.error(f"Failed to persist test position: {e}")

                        return filled_order
                return None

            else:  # LIVE MODE
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
            
        position = self.current_position
        if position['side'] == 'long':
            pnl = (current_price - position['entry_price']) * position['quantity']
        else:
            pnl = (position['entry_price'] - current_price) * position['quantity']
            
        position['pnl'] = pnl
        position['current_price'] = current_price
        
        # Update in DB (optimize to not write every 2s?)
        # For now, write e.g. if P&L changes significantly or throttling
        # self.db.update_position(position)
        
    def sync_state(self):
        """
        Sync state from Database.
        1. Import pending orders created by Dashboard.
        2. Process 'request_cancel' orders.
        3. Process 'request_close' positions.
        4. Sync Risk Params (SL/TP).
        """
        try:
            # Table Selection
            if self.mode == "TEST":
                orders_table = self.db.test_orders_table
                positions_table = self.db.test_positions_table
            else:
                orders_table = self.db.orders_table
                positions_table = self.db.positions_table
            
            # === 1. Sync Pending Orders (New imports) ===
            # Scan for status=pending
            resp = orders_table.scan(
                FilterExpression='#st = :pending',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':pending': 'pending'}
            )
            db_orders = resp.get('Items', [])
            
            for order in db_orders:
                order_id = order['order_id']
                if order_id not in self.pending_orders:
                    # New Order Found
                    if 'price' in order: order['price'] = float(order['price'])
                    if 'amount' in order: order['amount'] = float(order['amount'])
                    
                    if self.mode == "TEST" and self.simulator:
                        if order_id not in self.simulator.pending_orders:
                            sim_order = order.copy()
                            # Convert DB types to Py types for Simulator
                            # Note: Simulator might expect datetime objects
                            # Created_at in DB is timestamp int. Simulator uses datetime? 
                            # Checking simulator code: it uses datetime.now() usually.
                            # Just re-insert.
                            self.simulator.pending_orders[order_id] = sim_order 
                            logger.info(f"[TEST] Injected new dashboard order {order_id}")
                    
                    self.pending_orders[order_id] = order
            
            # === 2. Process Cancel Requests ===
            resp = orders_table.scan(
                FilterExpression='#st = :req_cancel',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':req_cancel': 'request_cancel'}
            )
            cancel_requests = resp.get('Items', [])
            
            for order in cancel_requests:
                order_id = order['order_id']
                logger.info(f"Processing cancel request for {order_id}")
                
                try:
                    if self.mode == "TEST" and self.simulator:
                        # Remove from simulator
                        if order_id in self.simulator.pending_orders:
                            self.simulator.pending_orders.pop(order_id)
                        
                        # Update DB
                        order['status'] = 'canceled'
                        # self.db.update_order(order) # Need a method that accepts dict or use generic update
                        self.db.update_order_status(order_id, 'canceled', self.mode)
                        
                        if order_id in self.pending_orders:
                            self.pending_orders.pop(order_id)
                            
                    else: # LIVE
                        # Cancel on Exchange
                        try:
                            self.exchange.cancel_order(order_id)
                        except Exception as e:
                            logger.warning(f"Exchange cancel failed (maybe already gone): {e}")
                        
                        self.db.update_order_status(order_id, 'canceled', self.mode)
                        if order_id in self.pending_orders:
                            self.pending_orders.pop(order_id)
                            
                except Exception as e:
                    logger.error(f"Failed to process cancel request {order_id}: {e}")

            # === 3. Process Close Requests ===
            resp = positions_table.scan(
                FilterExpression='#st = :req_close',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':req_close': 'request_close'}
            )
            close_requests = resp.get('Items', [])
            
            for pos in close_requests:
                pos_id = pos['position_id']
                # Check if it matches current position
                if self.current_position and self.current_position['position_id'] == pos_id:
                    logger.info(f"Processing close request for position {pos_id}")
                    # We need current price to close. 
                    # Ideally we have it from the main bot loop.
                    # We can Trigger a close flag? 
                    # Or just place a market order here if we have price?
                    # We don't have price passed here easily. 
                    # Strategy: Set a flag 'force_close' on the object? 
                    # OR: Just update the DB status back to 'open' but trigger the close_position logic?
                    
                    # Better: self.close_position() requires price. 
                    # If we don't have it, we can't close safely with Limit.
                    # Use Market order?
                    # Let's set a flag on the self.current_position object
                    self.current_position['force_close'] = True
                
                else:
                    # It's a request for a position we don't think we have active?
                    # Maybe it's already closed. Update DB to closed just in case?
                    # Or it's a desync. Ignore.
                    pass

            # === 4. Sync Risk (SL/TP) ===
            if self.current_position:
                # Re-fetch from DB to check for updates
                # Optimization: Only do this every X seconds? scan is expensive?
                # For MVP, maybe we skip full scan and Query specific ID?
                # But we don't have Key condition easily without index.
                # Actually, we can just GET item since we have Position ID
                try:
                    # Determine table
                    table = positions_table
                    response = table.get_item(Key={'position_id': self.current_position['position_id']})
                    if 'Item' in response:
                        db_pos = response['Item']
                        # Update local SL/TP
                        self.current_position['stop_loss'] = float(db_pos.get('stop_loss', 0)) if db_pos.get('stop_loss') else None
                        self.current_position['take_profit'] = float(db_pos.get('take_profit', 0)) if db_pos.get('take_profit') else None
                        # logger.info(f"Synced risk for {self.current_position['symbol']}: SL={self.current_position['stop_loss']}")
                except Exception as e:
                    logger.error(f"Error syncing risk params: {e}")

        except Exception as e:
            print(f"Error syncing state: {e}")
            logger.error(f"Error syncing state: {e}")
    
    def get_account_pnl(self) -> Dict:
        """Get account-level P&L statistics."""
        return self.db.get_account_pnl()
