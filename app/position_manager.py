
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
        # Risk Parameters
        risk_mgmt = config.get('risk_management', {})
        self.max_positions = risk_mgmt.get('max_positions', 1)
        self.use_min_quantity = risk_mgmt.get('use_min_quantity', True)
        self.order_ttl_seconds = risk_mgmt.get('order_ttl', 300)
        self.commission_rate = risk_mgmt.get('commission_rate', 0.001)
        self.sl_pct = risk_mgmt.get("sl_pct", 0.02)
        self.tp_pct = risk_mgmt.get("tp_pct", 0.04)
        self.max_slippage_pct = risk_mgmt.get("max_slippage_pct", 0.5) / 100.0 # Config is 0.5, need 0.005
        
        # risk_per_trade might be at root or in risk_mgmt
        self.risk_per_trade = config.get("risk_per_trade", risk_mgmt.get("risk_per_trade", 3.0))
        
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
            self.simulator = PaperTradingSimulator(starting_balance, db=self.db, commission_rate=self.commission_rate)
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
            
    def _sanitize_from_db(self, item):
        """Helper to convert Decimals and hydrate timestamps from DB items."""
        new_item = item.copy()
        for k, v in new_item.items():
            if isinstance(v, Decimal):
                new_item[k] = float(v)
            # Hydrate Timestamps (stored as ms int)
            if k in ['created_at', 'expires_at', 'filled_at', 'entry_time', 'exit_time'] and isinstance(new_item[k], (int, float, Decimal)):
                try:
                    new_item[k] = datetime.fromtimestamp(float(new_item[k]) / 1000.0)
                except: pass
        return new_item

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

            clean_positions = [self._sanitize_from_db(p) for p in existing_positions]
            clean_orders = [self._sanitize_from_db(o) for o in existing_orders]
            
            self.simulator.load_state(clean_positions, clean_orders)
            
        except Exception as e:
            logger.error(f"Failed to restore simulator state: {e}")

    def can_open_position(self, symbol: str) -> bool:
        # 1. Check Local Active Position
        if self.current_position is not None:
             # FIX: Desync Risk - If closing, allow new signal to proceed (flip logic handles wait)
             status = self.current_position.get('status')
             if status in ['request_close', 'closing']:
                 logger.info(f"Position {symbol} is {status}. Allowing new signal check (Flip).")
             else:
                 logger.warning(f"Cannot open position for {symbol}: already have open position (Local)")
                 return False
        
        # 2. Check Simulator/DB State (Source of Truth)
        if self.mode == "TEST":
            sim_pos = self.simulator.get_position(symbol)
            if sim_pos:
                status = sim_pos.get('status')
                if status in ['request_close', 'closing']:
                    pass # Allow
                else:
                    logger.warning(f"Cannot open position for {symbol}: Simulator has open position (Desync prevented)")
                    # Self-heal
                    self.current_position = sim_pos
                    return False
                
        # 3. Check Pending Entry Orders (Specific to symbol)
        # Note: self.pending_orders is a dict of all orders. Filter by symbol.
        pending_entries = [o for oid, o in self.pending_orders.items() if o.get('symbol') == symbol and o.get('type') == 'entry']
        if len(pending_entries) > 0:
             logger.warning(f"Cannot open position for {symbol}: has {len(pending_entries)} pending entry orders")
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
            
            # Risk-Based Sizing
            # 1. Determine Account Balance
            if self.mode == "TEST":
                acct = self.db.get_test_account_balance()
                balance = float(acct['balance']) if acct else 10000.0
            else:
                # Live Balance logic (omitted for MVP, assume fixed or fetch)
                balance = 1000.0 # Placeholder for LIVE
            
            # 2. Calculate Risk Amount (e.g. 3% of Equity)
            risk_amount = balance * (self.risk_per_trade / 100.0)
            
            # 3. Calculate Risk Per Unit (Entry - SL)
            # Long: Price * sl_pct
            risk_per_unit = price * self.sl_pct
            
            if risk_per_unit <= 0:
                return min_amount
                
            qty = risk_amount / risk_per_unit
            
            logger.info(f"[SIZING] Bal: {balance}, Risk%: {self.risk_per_trade}, RiskAmt: {risk_amount}, Price: {price}, SL%: {self.sl_pct}, Risk/Unit: {risk_per_unit}, CalcQty: {qty}")
            
            # 4. Cap at Account Balance (Spot Logic)
            max_qty_cost = balance / price
            if qty > max_qty_cost:
                qty = max_qty_cost * 0.99  # 99% of balance to be safe with fees
                
            # 5. Enforce Min/Max/Precision (FIX: Precision Error)
            amount = self._format_quantity(symbol, qty)
            
            # Reset min amount check ensuring standard float comparison
            if amount < min_amount:
                amount = min_amount
            
            logger.info(f"Calculated Size: Bal=${balance}, Risk=${risk_amount:.2f}, Qty={amount:.6f} (Precision Enforced)")
            
            return amount

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return None

    def _format_quantity(self, symbol, amount):
        market = self.exchange.market(symbol)
        step_size = market['limits']['amount']['min']
        return float(self.exchange.amount_to_precision(symbol, amount))

    def _format_price(self, symbol, price):
        return float(self.exchange.price_to_precision(symbol, price))

    def place_limit_order(self, symbol: str, side: str, current_price: float, amount: float, order_type: str = 'entry', signal_id: str = None) -> Optional[Dict]:
        """
        Unified Place Order.
        Calculates Limit Price (with small offset).
        Delegates to Simulator (TEST) or Exchange (LIVE).
        """
        try:
            # Limit Price Calculation (Use slippage for Marketable Limit)
            offset_pct = self.max_slippage_pct
            limit_price = current_price * (1 + offset_pct) if side == 'buy' else current_price * (1 - offset_pct)
            
            # FIX: Precision Enforced on Limit Price
            limit_price = self._format_price(symbol, limit_price)

            # FIX: Calculate SL/TP based on CURRENT MARKET PRICE (not inflated Limit Price)
            # This minimizes slippage error in risk calc.
            sl_price = None
            tp_price = None
            
            if order_type == 'entry':
                # Use current_price (Market) for cleaner levels
                ref_price = current_price 
                if side == 'buy': # Long
                     sl_price = ref_price * (1 - self.sl_pct)
                     tp_price = ref_price * (1 + self.tp_pct)
                else: # Short
                     sl_price = ref_price * (1 + self.sl_pct)
                     tp_price = ref_price * (1 - self.tp_pct)
                     
                # Round SL/TP
                if sl_price: sl_price = self._format_price(symbol, sl_price)
                if tp_price: tp_price = self._format_price(symbol, tp_price)

            
            if self.mode == "TEST":
                # Simulator handles DB persistence internally now!
                order = self.simulator.place_limit_order(
                    symbol, side, limit_price, amount, 
                    expires_at=datetime.now() + timedelta(seconds=self.order_ttl_seconds)
                )
                
                # Enrich with metadata NOT stored in DB core schema but useful for local logic
                order['type'] = order_type
                if sl_price: order['stop_loss'] = sl_price
                if tp_price: order['take_profit'] = tp_price
                if signal_id: order['signal_id'] = signal_id
                
                self.pending_orders[order['order_id']] = order
                
                # Audit Log
                safe_details = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in order.items()}
                self.db.log_audit('ORDER_PLACED', cause=order_type, details=safe_details, mode=self.mode)
                return order
                
            else: # LIVE
                market = self.exchange.market(symbol)
                # Double check precision (redundant but safe)
                limit_price = float(self.exchange.price_to_precision(symbol, limit_price))
                amount = float(self.exchange.amount_to_precision(symbol, amount))
                
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
                
                if sl_price: order_data['stop_loss'] = sl_price
                if tp_price: order_data['take_profit'] = tp_price
                
                self.pending_orders[order['id']] = order_data
                self.db.log_order(order_data)
                
                # Audit Log Sanitize
                safe_details = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in order_data.items()}
                self.db.log_audit('ORDER_PLACED', cause=order_type, details=safe_details, mode=self.mode)
                
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
            'pnl': 0.0,
            'stop_loss': order_data.get('stop_loss'),
            'take_profit': order_data.get('take_profit')
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
            if side in ['buy', 'long']:
                exit_side = 'sell'
            else:
                exit_side = 'buy'
            
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
            new_orders = resp.get('Items', [])
            if new_orders:
                logger.info(f"Sync found {len(new_orders)} new pending orders")
            for o in new_orders:
                 if o['order_id'] not in self.pending_orders:
                     # Import logic using sanitize
                     clean_o = self._sanitize_from_db(o)
                     self.pending_orders[clean_o['order_id']] = clean_o
                     if self.mode == "TEST":
                          self.simulator.pending_orders[clean_o['order_id']] = clean_o # Inject into simulator

            # 2. Close Requests
            ptable = self.db.test_positions_table if self.mode=="TEST" else self.db.positions_table
            resp = ptable.scan(FilterExpression='#st = :req', ExpressionAttributeNames={'#st':'status'}, ExpressionAttributeValues={':req':'request_close'})
            items = resp.get('Items', [])
            if items:
                logger.info(f"Sync found {len(items)} close requests")
            for p in items:
                sym = p.get('symbol')
                price = current_prices.get(sym) if current_prices else None
                if price:
                    # Pass 'p' as position_data to ensure we have details even if local state is desync
                    self.close_position_immediate(p['position_id'], price, reason="sync", position_data=p)
                    # Update status to closing
                    self.db.update_position_status(p['position_id'], 'closing', self.mode)

        except Exception as e:
            logger.error(f"Sync State Error: {e}")

    def update_position_pnl(self, symbol: str, current_price: float):
        if self.current_position and self.current_position['symbol'] == symbol:
             pos = self.current_position
             qty = pos['quantity']
             entry = pos['entry_price']
             
             # Gross PnL (Price Movement)
             gross_pnl = (current_price - entry)*qty if pos['side'] == 'long' else (entry - current_price)*qty
             
             # FIX: Use Gross PnL for Open Positions in DB
             # Why?
             # 1. 'Balance' (Cash) already has Entry Commission deducted (Futures Model).
             # 2. Deducting Entry Comm again here would double-count it in 'Equity = Balance + OpenPnL'.
             # 3. We also stop deducting 'Estimated Exit Comm' to align with standard 'Open PnL' (Gross) expectations 
             #    and avoid confusion where Equity < Cash immediately upon entry due to future fees.
             
             # net_pnl = gross_pnl - entry_comm - est_exit_comm  <-- OLD (Double Count)
             net_pnl = gross_pnl 
             
             pos['pnl'] = net_pnl
             self.db.update_position_pnl(pos['position_id'], net_pnl, current_price, self.mode)
             
             # Check SL/TP
             sl = pos.get('stop_loss')
             tp = pos.get('take_profit')
             
             if sl or tp:
                 hit_sl = False
                 hit_tp = False
                 
                 if pos['side'] == 'long':
                     if sl and current_price <= float(sl): hit_sl = True
                     if tp and current_price >= float(tp): hit_tp = True
                 else: # short
                     if sl and current_price >= float(sl): hit_sl = True
                     if tp and current_price <= float(tp): hit_tp = True
                     
                 if hit_sl:
                     logger.info(f"Stop Loss triggered for {symbol} @ {current_price} (SL: {sl})")
                     self.close_position_immediate(pos['position_id'], current_price, reason="stop_loss")
                 elif hit_tp:
                     logger.info(f"Take Profit triggered for {symbol} @ {current_price} (TP: {tp})")
                     self.close_position_immediate(pos['position_id'], current_price, reason="take_profit")
