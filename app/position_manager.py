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
            
            # Try to load existing balance from database
            saved_account = db.get_test_account_balance()
            if saved_account:
                starting_balance = saved_account['balance']
                logger.info(f"Loaded saved test account balance: ${starting_balance:,.2f}")
            else:
                starting_balance = initial_balance
                logger.info(f"No saved balance found, starting with initial: ${starting_balance:,.2f}")
                # Persist initial balance immediately so it's not lost on restart
                db.update_test_account_balance(starting_balance)
            
            self.simulator = PaperTradingSimulator(starting_balance)
            # Use test tables
            self.positions_table_name = 'test_positions'
            self.orders_table_name = 'test_orders'
            logger.info(f"PositionManager in TEST mode with ${starting_balance:,.2f} paper balance")
            
            # Load EXISTING open positions into Simulator from DB
            # This handles restarts where DB has positions but memory is fresh
            try:
                response = self.db.test_positions_table.scan(
                    FilterExpression='#st = :open OR #st = :req_close',
                    ExpressionAttributeNames={'#st': 'status'},
                    ExpressionAttributeValues={':open': 'open', ':req_close': 'request_close'}
                )
                existing_positions = response.get('Items', [])
                
                for pos in existing_positions:
                    # Convert Decimal to float for simulator
                    sim_pos = {
                        'position_id': pos['position_id'],
                        'symbol': pos['symbol'],
                        'side': pos['side'],
                        'entry_price': float(pos['entry_price']),
                        'quantity': float(pos['quantity']),
                        'status': pos['status'],
                        # Handle timestamps if needed, simulator uses them for info only mostly
                        'entry_time': datetime.now() # imprecise but safe
                    }
                    if 'entry_time' in pos:
                        try:
                            sim_pos['entry_time'] = datetime.fromtimestamp(int(pos['entry_time'])/1000)
                        except: pass
                        
                    self.simulator.positions[pos['symbol']] = sim_pos
                    logger.info(f"[TEST] Restored position {pos['symbol']} into simulator")
                    
            except Exception as e:
                logger.error(f"Failed to restore positions to simulator: {e}")
                
        else:  # LIVE
            self.simulator = None
            self.positions_table_name = 'positions'
            self.orders_table_name = 'orders'
            logger.info(f"PositionManager in LIVE mode - REAL TRADES ENABLED")
        
        # State
        self.current_position = self.db.get_active_position(self.mode)
        if self.current_position:
            logger.info(f"Restored active position from DB: {self.current_position['symbol']} ({self.current_position['status']})")
        
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
    
    def place_limit_order(self, symbol: str, side: str, current_price: float, amount: float, order_type: str = 'entry') -> Optional[Dict]:
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
                order_data['type'] = order_type # Tag order type
                self.pending_orders[order_data['order_id']] = order_data
                
                # Log to test tables - use appropriate method or direct table access
                try:
                    # Convert datetime to timestamp for DynamoDB
                    order_log = order_data.copy()
                    order_log['created_at'] = int(order_data['created_at'].timestamp() * 1000)
                    if 'expires_at' in order_log:
                        order_log['expires_at'] = int(order_data['expires_at'].timestamp() * 1000)
                    
                    # Convert float values to Decimal for DynamoDB
                    for k, v in order_log.items():
                        if isinstance(v, float):
                            order_log[k] = Decimal(str(v))
                    
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
                
                logger.info(f"[LIVE] Placing {side} limit order: {symbol} @ {limit_price} qty={amount} ({order_type})")
                
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
                    'expires_at': datetime.now() + timedelta(seconds=self.order_ttl_seconds),
                    'type': order_type # Tag
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
                    filled_order = None
                    for o in self.simulator.filled_orders:
                        if o['order_id'] == order_id:
                            filled_order = o
                            break
                    
                    if filled_order:
                        logger.info(f"[TEST] Order {order_id} filled at {filled_order['fill_price']}")
                        
                        # retrieve local tracked order to get type
                        local_order = self.pending_orders.get(order_id)
                        order_type = local_order.get('type', 'entry') if local_order else 'entry'

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
                            
                            # Convert float values to Decimal for DynamoDB
                            for k, v in order_log.items():
                                if isinstance(v, float):
                                    order_log[k] = Decimal(str(v))
                            
                            self.db.test_orders_table.put_item(Item=order_log)
                        except Exception as e:
                            logger.error(f"Failed to persist filled test order: {e}")

                        # LOGIC SPLIT: Entry vs Exit
                        if order_type == 'entry':
                            # Update DB: test_positions (CREATE)
                            symbol = filled_order['symbol']
                            position = self.simulator.get_position(symbol)
                            if position:
                                try:
                                    pos_log = position.copy()
                                    pos_log['entry_time'] = int(pos_log['entry_time'].timestamp() * 1000)
                                    if 'exit_time' in pos_log and pos_log['exit_time']:
                                        pos_log['exit_time'] = int(pos_log['exit_time'].timestamp() * 1000)
                                    for k, v in pos_log.items():
                                        if isinstance(v, float):
                                            pos_log[k] = Decimal(str(v))
                                    self.db.test_positions_table.put_item(Item=pos_log)
                                    logger.info(f"[TEST] Position persisted for {symbol}")
                                    
                                    # Sync local current_position
                                    self.current_position = position # Simulator obj needs mapping? 
                                    # Simulator position is dict, matches our format mostly. 
                                    # Actually simulator keeps positions in memory. PositionManager should also invoke _create_position_from_order conceptually triggers same thing.
                                    # In TEST mode, simulator manages positions. We just rely on simulator.get_position.
                                    # But wait, self.current_position is used by checks. We should sync it.
                                    self.current_position = position

                                except Exception as e:
                                    logger.error(f"Failed to persist test position: {e}")
                        
                        elif order_type == 'exit':
                             # CLOSED
                             logger.info(f"[TEST] Exit order filled. Clearing current position.")
                             self.current_position = None
                             # DB update: Simulator updates DB? No, we did above.
                             # We need to update the CLOSED position in DB.
                             # Get historic positions from simulator?
                             # Or just update status.
                             # Actually simulator moves to closed_positions.
                             # We should find it and sync.
                             if self.simulator.closed_positions:
                                 last_closed = self.simulator.closed_positions[-1]
                                 if last_closed['symbol'] == filled_order['symbol']:
                                      # Log closed pos to DB
                                      try:
                                          pos_log = last_closed.copy()
                                          pos_log['entry_time'] = int(pos_log['entry_time'].timestamp() * 1000)
                                          pos_log['exit_time'] = int(pos_log['exit_time'].timestamp() * 1000)
                                          for k, v in pos_log.items():
                                              if isinstance(v, float): pos_log[k] = Decimal(str(v))
                                          self.db.test_positions_table.put_item(Item=pos_log)
                                          logger.info(f"[TEST] Closed position persisted.")

                                          # Update Account Balance in DB
                                          self.db.update_test_account_balance(self.simulator.balance)
                                          logger.info(f"[TEST] Account balance persisted: ${self.simulator.balance:.2f}")

                                      except Exception as e:
                                          logger.error(f"Failed persist closed pos: {e}")

                        return filled_order
                return None

            else:  # LIVE MODE
                order = self.exchange.fetch_order(order_id)
                
                if order['status'] == 'closed':
                    # Order filled!
                    logger.info(f"Order {order_id} filled at {order['average']}")
                    
                    # Update pending orders
                    local_order_data = None
                    if order_id in self.pending_orders:
                        local_order_data = self.pending_orders.pop(order_id)
                        local_order_data['status'] = 'filled'
                        local_order_data['filled_at'] = datetime.now()
                        
                        # Update database
                        self.db.update_order(local_order_data)
                    
                    order_type = local_order_data.get('type', 'entry') if local_order_data else 'entry'
                    
                    if order_type == 'entry':
                        # Create position
                        self._create_position_from_order(local_order_data, order)
                    else: # Exit
                        # Close position logic
                        logger.info(f"Exit order {order_id} filled. Closing position.")
                        
                        if self.current_position:
                             # Update local state
                             self.current_position['status'] = 'closed'
                             self.current_position['exit_price'] = float(order['average'])
                             self.current_position['exit_time'] = datetime.now()
                             # Calculate Final PnL
                             if self.current_position['side'] == 'long':
                                 pnl = (self.current_position['exit_price'] - self.current_position['entry_price']) * self.current_position['quantity']
                             else:
                                 pnl = (self.current_position['entry_price'] - self.current_position['exit_price']) * self.current_position['quantity']
                             self.current_position['pnl'] = pnl
                             
                             # DB Update: Log closed position
                             self.db.log_position(self.current_position)
                             
                             # Reset
                             self.current_position = None
                        
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
                order_data = self.pending_orders.get(order_id)
                if not order_data: continue
                symbol = order_data.get('symbol')
                
                logger.info(f"Canceling expired order: {order_id}")
                
                if self.mode == "TEST" and self.simulator:
                    if order_id in self.simulator.pending_orders:
                        del self.simulator.pending_orders[order_id]
                else:
                    # Live Mode - Requires Symbol
                    if symbol:
                        self.exchange.cancel_order(order_id, symbol)
                    else:
                        logger.warning(f"Cannot cancel order {order_id} without symbol")
                
                # Update Local State
                self.pending_orders.pop(order_id)
                
                # Update DB
                self.db.update_order_status(order_id, 'expired', self.mode)
                
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
        self.db.log_position(position, self.mode)
        
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
        
        # Use simple "Marketable Limit" logic to ensure fill
        # For Sell: Price * 0.995 (Sell lower than market -> fills at market)
        # For Buy: Price * 1.005 (Buy higher than market -> fills at market)
        if exit_side == 'sell':
            limit_price = current_price * 0.995
        else:
            limit_price = current_price * 1.005
            
        # Place limit order to close
        order = self.place_limit_order(pos['symbol'], exit_side, limit_price, pos['quantity'], order_type='exit')
        
        if order:
            logger.info(f"Closing position {pos['position_id']} with order {order['order_id']}")
    
    def close_position_immediate(self, position_id: str, current_price: float, reason: str = 'manual', position_data: Dict = None) -> bool:
        """
        Immediately close a position using market-like limit order.
        Used for position flipping.
        Returns True if close order placed successfully.
        """
        try:
            # Find position
            pos = None
            if position_data:
                pos = position_data
            elif self.current_position and self.current_position.get('position_id') == position_id:
                pos = self.current_position
            elif self.mode == "TEST" and self.simulator:
                # Search simulator positions by ID
                for sym, p in self.simulator.positions.items():
                    if p.get('position_id') == position_id:
                        pos = p
                        break
            
            if not pos:
                logger.error(f"Position {position_id} not found for immediate close")
                return False
            
            symbol = pos['symbol']
            side = pos['side']
            amount = pos['quantity']
            
            # Determine exit side (opposite of entry)
            exit_side = 'sell' if side == 'buy' else 'buy'
            
            # Place aggressive limit order for immediate execution
            # In PAPER mode, this will auto-fill
            # In LIVE mode, use tight limit to ensure fill
            logger.info(f"[FLIP] Closing {position_id}: {side} position, placing {exit_side} order")
            
            order = self.place_limit_order(
                symbol=symbol,
                side=exit_side,
                current_price=current_price,
                amount=amount,
                order_type='exit'
            )
            
            if order:
                logger.info(f"[FLIP] Close order placed for {position_id}: {order.get('order_id')}")
                return True
            else:
                logger.error(f"[FLIP] Failed to place close order for {position_id}")
                return False
                
        except Exception as e:
            logger.error(f"[FLIP] Error in close_position_immediate: {e}")
            logger.exception("Full traceback:")
            return False
    
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
        
        # Update in DB
        self.db.update_position_pnl(position['position_id'], pnl, current_price, self.mode)
        
    def sync_state(self, current_prices: Dict[str, float] = None):
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
                            # DynamoDB returns Decimal for numbers. Simulator expects datetime for created_at.
                            c_at = order.get('created_at')
                            if c_at:
                                # Handle Decimal, int, float, str
                                if isinstance(c_at, (int, float, str, Decimal)):
                                    try:
                                        ts = float(c_at)
                                        sim_order['created_at'] = datetime.fromtimestamp(ts/1000)
                                    except:
                                        sim_order['created_at'] = datetime.now()
                                else:
                                    sim_order['created_at'] = datetime.now()
                            else:
                                sim_order['created_at'] = datetime.now()
                            
                            self.simulator.pending_orders[order_id] = sim_order 
                            logger.info(f"[TEST] Injected new dashboard order {order_id}")
                    
                    # Store in local state (Convert timestamps first)
                    if 'expires_at' in order and isinstance(order['expires_at'], (Decimal, int, float, str)):
                        try:
                            order['expires_at'] = datetime.fromtimestamp(float(order['expires_at'])/1000)
                        except:
                            order['expires_at'] = datetime.now() + pd.Timedelta(hours=24) # Fallback
                            
                    if 'created_at' in order and isinstance(order['created_at'], (Decimal, int, float, str)):
                         try:
                            order['created_at'] = datetime.fromtimestamp(float(order['created_at'])/1000)
                         except:
                            order['created_at'] = datetime.now()

                    self.pending_orders[order_id] = order
                    logger.info(f"Imported pending order {order_id} from DB")
            
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
                symbol = pos.get('symbol')
                logger.info(f"Processing close request for position {pos_id} ({symbol})")
                
                # Get Price
                price = None
                if current_prices and symbol in current_prices:
                    price = current_prices[symbol]
                
                if price:
                    # Execute immediate close
                    # Pass 'pos' dict explicitly to avoid lookup failure for zombie positions
                    success = self.close_position_immediate(pos_id, price, reason="manual_db_request", position_data=pos)
                    if success:
                        logger.info(f"Successfully executed manual close for {pos_id}")
                        # Update status to 'closing' to PREVENT INFINITE LOOP (spamming orders)
                        try:
                            self.db.update_position_status(pos_id, 'closing', self.mode)
                        except Exception as e:
                            logger.error(f"Failed to update status to closing for {pos_id}: {e}")
                    else:
                        logger.error(f"Failed to execute manual close for {pos_id}")
                else:
                    logger.warning(f"Cannot process close request for {symbol}: No price data")

            # === 4. Sync Risk (SL/TP) ===
            if self.current_position:
                try:
                    # Determine table
                    table = positions_table
                    response = table.get_item(Key={'position_id': self.current_position['position_id']})
                    if 'Item' in response:
                        db_pos = response['Item']
                        # Update local SL/TP
                        self.current_position['stop_loss'] = float(db_pos.get('stop_loss', 0)) if db_pos.get('stop_loss') else None
                        self.current_position['take_profit'] = float(db_pos.get('take_profit', 0)) if db_pos.get('take_profit') else None
                except Exception as e:
                    logger.error(f"Error syncing risk params: {e}")

        except Exception as e:
            print(f"Error syncing state: {e}")
            logger.error(f"Error syncing state: {e}")
    
    def get_account_pnl(self) -> Dict:
        """Get account-level P&L statistics."""
        return self.db.get_account_pnl()
