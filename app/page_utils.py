
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

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

def render_positions_table(positions_table):
    """Render Open and Closed positions."""
    st.subheader("Position History")
    
    try:
        response = positions_table.scan()
        positions = response.get('Items', [])
        
        if positions:
            df = pd.DataFrame(positions)
            
            # Type Conversions
            if 'entry_time' in df.columns:
                df['entry_time'] = pd.to_datetime(df['entry_time'].astype(int), unit='ms')
            if 'exit_time' in df.columns:
                df['exit_time'] = pd.to_datetime(df['exit_time'].astype(int), unit='ms')
            
            numeric_cols = ['entry_price', 'exit_price', 'quantity', 'pnl', 'current_price']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            
            df = df.sort_values('entry_time', ascending=False)
            
            open_pos = df[df['status'] == 'open']
            closed_pos = df[df['status'] == 'closed']
            
            # --- Open Positions ---
            st.markdown("### 🟢 Open Positions")
            if not open_pos.empty:
                cols = ['symbol', 'side', 'entry_price', 'quantity', 'entry_time']
                if 'current_price' in open_pos.columns: cols.insert(3, 'current_price')
                
                # Check if pnl exists and add it
                has_pnl = 'pnl' in open_pos.columns
                if has_pnl: cols.append('pnl')
                
                # Create styled dataframe only if PnL exists
                if has_pnl:
                    st.dataframe(open_pos[cols].style.applymap(
                        lambda v: 'color: green' if (isinstance(v, (int, float)) and v > 0) else 'color: red' if (isinstance(v, (int, float)) and v < 0) else '', 
                        subset=['pnl']
                    ), use_container_width=True)
                else:
                    st.dataframe(open_pos[cols], use_container_width=True)
            else:
                st.info("No open positions")
            
            st.divider()
            
            # --- Closed Positions ---
            st.markdown("### 📜 Closed Positions")
            if not closed_pos.empty:
                cols = ['symbol', 'side', 'entry_price', 'exit_price', 'quantity', 'pnl', 'entry_time', 'exit_time']
                
                # Ensure pnl column handles NaNs gracefully before styling
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
            st.info("No position data found")
            
    except Exception as e:
        st.error(f"Error loading positions: {e}")

def render_orders_table(orders_table):
    """Render Orders table."""
    st.subheader("Order History")
    try:
        response = orders_table.scan()
        orders = response.get('Items', [])
        
        if orders:
            df = pd.DataFrame(orders)
            
            # Timestamps
            for col in ['created_at', 'filled_at', 'expires_at']:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col].astype(int), unit='ms')
                    
            # Floats
            for col in ['price', 'amount', 'fill_price']:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            
            df = df.sort_values('created_at', ascending=False)
            
            # Filter
            statuses = st.multiselect("Status", ['pending', 'filled', 'expired', 'canceled'], default=['filled', 'pending'])
            filtered = df[df['status'].isin(statuses)]
            
            cols = ['order_id', 'symbol', 'side', 'price', 'amount', 'status', 'created_at']
            if 'filled_at' in filtered.columns: cols.append('filled_at')
            
            st.dataframe(filtered[cols], use_container_width=True)
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
