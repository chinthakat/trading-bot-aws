
import logging
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List
import pandas as pd
from paper_trading import PaperTradingSimulator

logger = logging.getLogger(__name__)

class PositionManager:
    """
    Manages trading positions with strict risk controls:
    - Only one position at a time
    - Limit orders with expiry
    - Minimum quantity sizing for conservative risk
    - Facade for PaperTradingSimulator (TEST) vs Exchange (LIVE)
    """
    
    def __init__(self, exchange, db, config, mode="TEST"):
        self.exchange = exchange
        self.db = db
        self.mode = mode
        
        # Risk Parameters
        self.max_positions = config.get('max_positions', 1)
        self.use_min_quantity = config.get('use_min_quantity', True)
        self.order_ttl_seconds = config.get('order_ttl', 300)  # 5 minutes
        
        # State
        self.pending_orders = {} # Local view of pending orders
        self.current_position = None
        
        # Mode-specific initialization
        if mode == "TEST":
            initial_balance = config.get('test_initial_balance', 10000.0)
            
            # Load balance from DB
            saved_account = db.get_test_account_balance()
            if saved_account:
                starting_balance = saved_account['balance']
                logger.info(f"Loaded saved test account balance: ${starting_balance:,.2f}")
            else:
                starting_balance = initial_balance
                db.update_test_account_balance(starting_balance)
            
            # Instantiate Simulator with DB INJECTION
            self.simulator = PaperTradingSimulator(starting_balance, db=self.db)
            self.positions_table_name = 'test_positions'
            self.orders_table_name = 'test_orders'
            logger.info(f"PositionManager in TEST mode with ${starting_balance:,.2f} paper balance")
            
            # Restore Simulator State from DB
            self._restore_test_state()
            
        else:  # LIVE
            self.simulator = None
            self.positions_table_name = 'positions'
            self.orders_table_name = 'orders'
            logger.info(f"PositionManager in LIVE mode - REAL TRADES ENABLED")
        
        # Load active position (common for both modes)
        self.current_position = self.db.get_active_position(self.mode)
        if self.current_position:
            logger.info(f"Restored active position from DB: {self.current_position['symbol']} ({self.current_position['status']})")
            
    def _restore_test_state(self):
        """Restore positions and orders into simulator from DB."""
        try:
            # 1. Restore Positions
            response = self.db.test_positions_table.scan(
                FilterExpression='#st = :open OR #st = :req_close',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':open': 'open', ':req_close': 'request_close'}
            )
            existing_positions = response.get('Items', [])
            
            # 2. Restore Orders (Pending)
            resp_ord = self.db.test_orders_table.scan(
                FilterExpression='#st = :pending',
                ExpressionAttributeNames={'#st': 'status'},
                ExpressionAttributeValues={':pending': 'pending'}
            )
            existing_orders = resp_ord.get('Items', [])

            # Helper to convert Decimal to float
            def dec_to_float(item):
                 new_item = item.copy()
                 for k,v in new_item.items():
                     if isinstance(v, Decimal): new_item[k] = float(v)
                 return new_item

            clean_positions = [dec_to_float(p) for p in existing_positions]
            clean_orders = [dec_to_float(o) for o in existing_orders]
            
            self.simulator.load_state(clean_positions, clean_orders)
            
        except Exception as e:
            logger.error(f"Failed to restore simulator state: {e}")

    def can_open_position(self, symbol: str) -> bool:
        if self.current_position is not None:
             logger.warning(f"Cannot open position for {symbol}: already have open position")
             return False
        if len(self.pending_orders) > 0:
             logger.warning(f"Cannot open position for {symbol}: have pending orders")
             return False
        return True

    def calculate_position_size(self, symbol: str, price: float) -> float:
        try:
            if not self.exchange.markets:
                self.exchange.load_markets()
            market = self.exchange.market(symbol)
            min_amount = market['limits']['amount']['min']
            
            if self.use_min_quantity:
                return min_amount
            return min_amount
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return None

    def place_limit_order(self, symbol: str, side: str, current_price: float, amount: float, order_type: str = 'entry', signal_id: str = None) -> Optional[Dict]:
        """
        Unified Place Order.
        Calculates Limit Price (with small offset).
        Delegates to Simulator (TEST) or Exchange (LIVE).
        """
        try:
            # Limit Price Calculation (0.1% offset usually for Maker, but we want fills)
            # Actually for entry we usually want LIMIT.
            offset_pct = 0.001 
            limit_price = current_price * (1 + offset_pct) if side == 'buy' else current_price * (1 - offset_pct)
            
            if self.mode == "TEST":
                # Simulator handles DB persistence internally now!
                order = self.simulator.place_limit_order(
                    symbol, side, limit_price, amount, 
                    expires_at=datetime.now() + timedelta(seconds=self.order_ttl_seconds)
                )
                
                # Enrich with metadata NOT stored in DB core schema but useful for local logic
                order['type'] = order_type
                if signal_id: order['signal_id'] = signal_id
                
                self.pending_orders[order['order_id']] = order
                
                # Audit Log
                self.db.log_audit('ORDER_PLACED', cause=order_type, details=order, mode=self.mode)
                return order
                
            else: # LIVE
                market = self.exchange.market(symbol)
                limit_price = self.exchange.price_to_precision(symbol, limit_price)
                
                logger.info(f"[LIVE] Placing {side} limit order: {symbol} @ {limit_price}")
                
                # Exchange Call
                order = self.exchange.create_limit_order(symbol, side, amount, limit_price)
                
                # Standardize
                order_data = {
                    'order_id': order['id'],
                    'symbol': symbol,
                    'side': side,
                    'price': limit_price,
                    'amount': amount,
                    'status': 'pending',
                    'created_at': datetime.now(),
                    'expires_at': datetime.now() + timedelta(seconds=self.order_ttl_seconds),
                    'type': order_type,
                    'signal_id': signal_id
                }
                
                self.pending_orders[order['id']] = order_data
                self.db.log_order(order_data)
                self.db.log_audit('ORDER_PLACED', cause=order_type, details=order_data, mode=self.mode)
                
                return order_data
                
        except Exception as e:
            logger.error(f"Failed to place limit order for {symbol}: {e}")
            return None

    def check_order_status(self, order_id: str, current_price: float = None) -> Optional[Dict]:
        """Check status. If Filled, update Position State."""
        try:
            if self.mode == "TEST":
                if not current_price: return None
                
                # Simulator updates DB internally
                filled = self.simulator.simulate_fill(order_id, current_price)
                
                if filled:
                    # Sync Local State
                    if order_id in self.pending_orders:
                        local_order = self.pending_orders.pop(order_id)
                        
                        # Logic: Did we open or close?
                        order_type = local_order.get('type', 'entry')
                        
                        if order_type == 'entry':
                            # Sync current_position from simulator
                            # Simulator already created position in its memory.
                            # We just grab it.
                            symbol = local_order['symbol']
                            sim_pos = self.simulator.get_position(symbol)
                            if sim_pos:
                                self.current_position = sim_pos
                                logger.info(f"[TEST] Position synced from simulator: {sim_pos['position_id']}")
                        
                        elif order_type == 'exit':
                            # Sync close
                            self.current_position = None
                            logger.info(f"[TEST] Position closed in simulator. Cleared local.")
                            # Simulator handled DB update for closed position.
                            
                    return self.simulator.filled_orders[-1] # Return the filled order data
                
                return None

            else: # LIVE
                order = self.exchange.fetch_order(order_id)
                if order['status'] == 'closed': # Filled
                    if order_id in self.pending_orders:
                        local_order = self.pending_orders.pop(order_id)
                        local_order['status'] = 'filled'
                        local_order['filled_at'] = datetime.now()
                        self.db.update_order(local_order)
                        
                        if local_order.get('type') == 'entry':
                            self._create_position_from_order(local_order, order)
                        else:
                            self._colose_position_logic_live(order)
                            
                    return order
                elif order['status'] == 'canceled':
                     if order_id in self.pending_orders: self.pending_orders.pop(order_id)
                     self.db.update_order_status(order_id, 'canceled', self.mode)
                     
                return order

        except Exception as e:
            logger.error(f"Error checking order {order_id}: {e}")
            return None

    def _create_position_from_order(self, order_data, exchange_order):
        # Only used in LIVE mode
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
        logger.info(f"[LIVE] Position created: {position['position_id']}")

    def _colose_position_logic_live(self, exchange_order):
        # Only used in LIVE mode
        if self.current_position:
            pos = self.current_position
            exit_price = float(exchange_order['average'])
            pos['status'] = 'closed'
            pos['exit_price'] = exit_price
            pos['exit_time'] = datetime.now()
            qty = pos['quantity']
            
            pnl = (exit_price - pos['entry_price']) * qty if pos['side'] == 'long' else (pos['entry_price'] - exit_price) * qty
            pos['pnl'] = pnl
            
            self.db.log_position(pos, self.mode) # Logs full closed pos
            self.current_position = None
            logger.info(f"[LIVE] Position closed. PnL: {pnl}")

    def cancel_expired_orders(self):
        now = datetime.now()
        expired = []
        for oid, odata in self.pending_orders.items():
            expires_at = odata.get('expires_at')
            if expires_at and now > expires_at:
                expired.append(oid)
        
        for oid in expired:
            try:
                order_data = self.pending_orders.get(oid)
                logger.info(f"Canceling expired order {oid}")
                
                if self.mode == "TEST":
                    self.simulator.cancel_order(oid) # Handles Logic + DB
                else:
                    self.exchange.cancel_order(oid, order_data['symbol'])
                    self.db.update_order_status(oid, 'expired', self.mode)
                
                if oid in self.pending_orders:
                    self.pending_orders.pop(oid)
            except Exception as e:
                logger.error(f"Failed to cancel expired {oid}: {e}")

    def close_position_immediate(self, position_id: str, current_price: float, reason: str = 'manual', position_data: Dict = None, signal_id: str = None) -> bool:
        """
        Close position immediately using Aggressive Limit (Marketable Limit).
        """
        try:
            # Locate Position
            pos = None
            if self.current_position and self.current_position.get('position_id') == position_id:
                pos = self.current_position
            elif position_data:
                pos = position_data
            
            if not pos:
                logger.error(f"Position {position_id} not found/active")
                return False
                
            symbol = pos['symbol']
            side = pos['side']
            amount = pos['quantity']
            
            # EXIT SIDE
            exit_side = 'sell' if side == 'buy' else 'buy'
            
            # AGGRESSIVE PRICE (1% buffer)
            # Buy Exit: 1.01 * Price
            # Sell Exit: 0.99 * Price
            if exit_side == 'buy':
                price = current_price * 1.01
            else:
                price = current_price * 0.99
                
            logger.info(f"Closing {position_id} ({side}) via Aggressive {exit_side} @ {price}")
            
            order = self.place_limit_order(symbol, exit_side, price, amount, order_type='exit', signal_id=signal_id)
            return True if order else False
            
        except Exception as e:
            logger.error(f"Immediate close failed: {e}")
            return False

    def sync_state(self, current_prices: Dict[str, float] = None):
        """Minimal Sync: Imports Dashboard requests only."""
        try:
            # 1. New Orders
            table = self.db.test_orders_table if self.mode=="TEST" else self.db.orders_table
            resp = table.scan(FilterExpression='#st = :pending', ExpressionAttributeNames={'#st':'status'}, ExpressionAttributeValues={':pending':'pending'})
            for o in resp.get('Items', []):
                 if o['order_id'] not in self.pending_orders:
                     # Import logic (simplified for brevity, assume dashboard puts correct format)
                     # Convert Decimal -> Float
                     clean_o = {k: float(v) if isinstance(v, Decimal) else v for k,v in o.items()}
                     # Handle timestamps if needed
                     self.pending_orders[clean_o['order_id']] = clean_o
                     if self.mode == "TEST":
                          self.simulator.pending_orders[clean_o['order_id']] = clean_o # Inject into simulator

            # 2. Close Requests
            ptable = self.db.test_positions_table if self.mode=="TEST" else self.db.positions_table
            resp = ptable.scan(FilterExpression='#st = :req', ExpressionAttributeNames={'#st':'status'}, ExpressionAttributeValues={':req':'request_close'})
            for p in resp.get('Items', []):
                sym = p.get('symbol')
                price = current_prices.get(sym) if current_prices else None
                if price:
                    self.close_position_immediate(p['position_id'], price, reason="sync")
                    # Update status to closing
                    self.db.update_position_status(p['position_id'], 'closing', self.mode)

        except Exception as e:
            logger.error(f"Sync State Error: {e}")

    def update_position_pnl(self, symbol: str, current_price: float):
        if self.current_position and self.current_position['symbol'] == symbol:
             pos = self.current_position
             qty = pos['quantity']
             entry = pos['entry_price']
             pnl = (current_price - entry)*qty if pos['side'] == 'long' else (entry - current_price)*qty
             pos['pnl'] = pnl
             self.db.update_position_pnl(pos['position_id'], pnl, current_price, self.mode)
