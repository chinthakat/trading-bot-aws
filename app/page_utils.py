
import streamlit as st
import time
import pandas as pd
import plotly.graph_objects as go
from decimal import Decimal

def render_account_summary(db, mode, config):
    """Render Balance, Equity, P&L Summary."""
    st.subheader(f"🏦 Account Summary")
    
    # Get P&L Stats for specific mode
    pnl_stats = db.get_account_pnl(mode=mode)
    
    # Estimate Balance
    # In a real app, 'balance' should be fetched from an Account/Wallet endpoint or table
    # For now, we mock it based on initial + realized
    if mode == "TEST":
        initial = config['trading'].get('test_initial_balance', 10000.0)
    else:
        initial = 0.0 # Live balance hard to guess without API fetch
        
    current_balance = initial + pnl_stats['closed_pnl']
    equity = current_balance + pnl_stats['open_pnl']
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Equity", f"${equity:,.2f}", delta=f"{pnl_stats['total_pnl']:,.2f}")
    with col2:
        st.metric("Cash Balance", f"${current_balance:,.2f}")
    with col3:
        st.metric("Open P&L", f"${pnl_stats['open_pnl']:,.2f}", 
             delta_color="normal" if pnl_stats['open_pnl'] >= 0 else "inverse")
    with col4:
        win_rate = pnl_stats['win_rate'] * 100
        st.metric("Win Rate", f"{win_rate:.1f}%", help=f"{pnl_stats['win_count']}W - {pnl_stats['loss_count']}L")
        
    st.divider()

def render_positions_table(db, mode):
    """Render Positions with Inline Edit/Close."""
    table = db.test_positions_table if mode == "TEST" else db.positions_table
    st.subheader("Position History")
    
    try:
        response = table.scan()
        positions = response.get('Items', [])
        
        if positions:
            # Data Processing
            df = pd.DataFrame(positions)
            if 'entry_time' in df.columns: 
                df['entry_time'] = pd.to_datetime(df['entry_time'].astype(int), unit='ms')
            if 'exit_time' in df.columns: 
                df['exit_time'] = pd.to_datetime(df['exit_time'].astype(int), unit='ms')
            
            # Convert decimal/float cols
            numeric_cols = ['entry_price', 'exit_price', 'quantity', 'pnl', 'current_price', 'stop_loss', 'take_profit']
            for col in numeric_cols:
                if col in df.columns: 
                    df[col] = df[col].astype(float)
            
            df = df.sort_values('entry_time', ascending=False)
            
            # Include 'request_close' in open positions view
            open_pos = df[df['status'].isin(['open', 'request_close'])].copy()
            closed_pos = df[df['status'] == 'closed']

            # --- Open Positions ---
            st.markdown("### 🟢 Open Positions")
            if not open_pos.empty:
                # Add Action Columns
                open_pos['Close'] = False
                
                # Ensure SL/TP columns exist
                if 'stop_loss' not in open_pos.columns: open_pos['stop_loss'] = 0.0
                if 'take_profit' not in open_pos.columns: open_pos['take_profit'] = 0.0
                
                # Reorder
                cols = ['Close', 'symbol', 'side', 'entry_price', 'current_price', 'quantity', 'pnl', 'stop_loss', 'take_profit', 'entry_time']
                
                # Check column existence (current_price/pnl might be missing if new)
                cols = [c for c in cols if c in open_pos.columns or c == 'Close']

                column_config = {
                    "Close": st.column_config.CheckboxColumn("Close?", help="Check to close position at market", default=False),
                    "symbol": st.column_config.TextColumn("Symbol"),
                    "stop_loss": st.column_config.NumberColumn("Stop Loss", help="Edit to update"),
                    "take_profit": st.column_config.NumberColumn("Take Profit", help="Edit to update"),
                    "pnl": st.column_config.NumberColumn("PnL", format="$%.2f"),
                    "entry_time": st.column_config.DatetimeColumn("Entry Time", format="D MMM, HH:mm"),
                    "status": st.column_config.TextColumn("Status")
                }
                
                # Add status column to view if not there
                if 'status' not in cols: cols.append('status')

                # Render Editor
                edited_df = st.data_editor(
                    open_pos[cols],
                    hide_index=True,
                    column_config=column_config,
                    disabled=['symbol', 'side', 'entry_price', 'current_price', 'quantity', 'pnl', 'entry_time', 'status'],
                    key=f"positions_editor_{mode}"
                )
                
                # 3. Detect Changes
                if not edited_df.equals(open_pos[cols]):
                    for index, row in edited_df.iterrows():
                        # Use safety lookup
                        original_row = open_pos.loc[index] if index in open_pos.index else None
                        if original_row is None: continue 
                        # Note: st.data_editor persistence relies on index matching original DF if we passed subset.
                        # Actually we used reset_index or just direct filtering. 
                        # To be safe, let's assume 'position_id' is needed but we didn't include it in view?
                        # Wait, we need position_id to update DB!
                        # We must include position_id in the DF but maybe hide it? 
                        # Or rely on the index if it matches the original DF index. 
                        # Let's map back via index.
                        
                        # Better approach: Add position_id to visible DF or verify index alignment.
                        # The 'open_pos' df preserves original index. 'edited_df' should too.
                        
                        pos_id = open_pos.loc[index, 'position_id'] # We need to ensure we access the master DF using the index
                        
                        # Check Close
                        if row['Close']:
                            db.update_position_status(pos_id, "request_close", mode)
                            st.toast(f"Closing position {pos_id[:8]}...", icon="🔴")
                            time.sleep(1)
                            st.rerun()
                        
                        # Check Risk Updates
                        # We compare row['stop_loss'] vs original_row['stop_loss']
                        new_sl = row.get('stop_loss')
                        new_tp = row.get('take_profit')
                        old_sl = original_row.get('stop_loss')
                        old_tp = original_row.get('take_profit')
                        
                        # Handle NaNs
                        if pd.isna(new_sl): new_sl = 0.0
                        if pd.isna(new_tp): new_tp = 0.0
                        if pd.isna(old_sl): old_sl = 0.0
                        if pd.isna(old_tp): old_tp = 0.0
                        
                        if new_sl != old_sl or new_tp != old_tp:
                             db.update_position_risk(pos_id, new_sl, new_tp, mode)
                             st.toast(f"Updated Risk for {original_row['symbol']}", icon="💾")
                             # We don't force rerun immediately for risk edits to allow multiple edits? 
                             # Or we should to reflect state? 
                             # Rerun confirms it.
                             time.sleep(1)
                             st.rerun()

            else:
                 st.info("No open positions")
            
            st.divider()
            
            # --- Closed Positions ---
            st.markdown("### 📜 Closed Positions")
            if not closed_pos.empty:
                cols = ['symbol', 'side', 'entry_price', 'exit_price', 'quantity', 'pnl', 'entry_time', 'exit_time']
                if 'pnl' in closed_pos.columns:
                     st.dataframe(closed_pos[cols].style.applymap(
                        lambda v: 'color: green' if (isinstance(v, (int, float)) and v > 0) else 'color: red' if (isinstance(v, (int, float)) and v < 0) else '', 
                        subset=['pnl']
                    ), use_container_width=True)
                else:
                     st.dataframe(closed_pos[cols], use_container_width=True)
            else:
                st.info("No closed positions")

        else:
            st.info("No positions found")
            
    except Exception as e:
        st.error(f"Error: {e}")

def render_orders_table(db, mode):
    """Render Orders table with Inline Cancel functionality."""
    st.subheader("Order History")
    
    table = db.test_orders_table if mode == "TEST" else db.orders_table
    
    try:
        response = table.scan()
        orders = response.get('Items', [])
        
        if orders:
            df = pd.DataFrame(orders)
            
            # Formatting
            for col in ['created_at', 'filled_at', 'expires_at']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col].astype(int), unit='ms')
            for col in ['price', 'amount', 'fill_price']:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            df = df.sort_values('created_at', ascending=False)
            
            # 1. Filter Display
            statuses = st.multiselect("Status", ['pending', 'filled', 'expired', 'canceled'], default=['filled', 'pending'])
            filtered = df[df['status'].isin(statuses)].copy()
            
            # 2. Add 'Cancel' Action Column for Pending items
            # We want to show the 'Cancel' checkbox ONLY for pending rows? 
            # st.data_editor applies schema to whole col. 
            # We'll just ignore clicks on non-pending rows or make them disabled if possible (Streamlit doesn't support row-level disable easily yet).
            # Approach: Add 'Cancel' col to ALL, but logic only respects pending.
            filtered['Cancel'] = False
            
            # Reorder columns: put 'Cancel' first for visibility
            cols = ['Cancel', 'order_id', 'symbol', 'side', 'price', 'amount', 'status', 'created_at']
            if 'filled_at' in filtered.columns: cols.append('filled_at')
            
            # Define column config
            column_config = {
                "Cancel": st.column_config.CheckboxColumn(
                    "Cancel?",
                    help="Check to request cancellation",
                    default=False,
                ),
                "created_at": st.column_config.DatetimeColumn("Created", format="D MMM, HH:mm:ss"),
                "filled_at": st.column_config.DatetimeColumn("Filled", format="D MMM, HH:mm:ss"),
                "price": st.column_config.NumberColumn("Price"),
                "amount": st.column_config.NumberColumn("Amount"),
            }

            # Render Editor
            edited_df = st.data_editor(
                filtered[cols],
                hide_index=True,
                column_config=column_config,
                disabled=['order_id', 'symbol', 'side', 'price', 'amount', 'status', 'created_at', 'filled_at'],
                key=f"orders_editor_{mode}"
            )
            
            # 3. Detect Changes
            # We look for rows where 'Cancel' is True AND status was 'pending'
            # Note: The 'edited_df' contains the NEW state.
            
            if not edited_df.empty:
                # Find rows marked for cancellation
                to_cancel = edited_df[edited_df['Cancel'] == True]
                
                for index, row in to_cancel.iterrows():
                    order_id = row['order_id']
                    original_status = df[df['order_id'] == order_id]['status'].values[0]
                    
                    if original_status == 'pending':
                        db.update_order_status(order_id, "request_cancel", mode)
                        st.toast(f"Cancellation requested for {order_id}", icon="🚫")
                        time.sleep(1) # Give toast time to show
                        st.rerun()
                    elif original_status != 'pending' and row['Cancel']:
                        # If user checks cancel on a filled order, just warn and reset?
                        # Rerun resets the UI state
                        st.warning(f"Cannot cancel order {order_id} (Status: {original_status})")
                        time.sleep(1)
                        st.rerun()

        else:
            st.info("No orders found")
            
    except Exception as e:
        st.error(f"Error loading orders: {e}")

def render_signals_table(signals_table):
    """Render Signals table."""
    st.subheader("Generated Signals")
    try:
        response = signals_table.scan()
        items = response.get('Items', [])
        
        if items:
            df = pd.DataFrame(items)
            
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
            if 'price' in df.columns:
                df['price'] = df['price'].astype(float)
                
            df = df.sort_values('timestamp', ascending=False)
            
            st.dataframe(df[['timestamp', 'symbol', 'signal', 'algo', 'price']], use_container_width=True)
        else:
            st.info("No signals found")
    except Exception as e:
        st.error(f"Error loading signals: {e}")
