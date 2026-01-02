import streamlit as st
import pandas as pd
import json
import os
import sys

# Add app directory to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from persistence import DynamoManager

st.set_page_config(page_title="Trading Activity", page_icon="📊", layout="wide")

st.title("📊 Trading Activity")

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

mode = config['trading'].get('mode', 'TEST')

# Mode indicator
if mode == "TEST":
    st.success(f"🧪 **TEST MODE** - Paper Trading (Virtual Balance)")
else:
    st.error(f"⚡ **LIVE MODE** - Real Trading")

st.divider()

# DB Connection
try:
    db = DynamoManager(config)
except Exception as e:
    st.error(f"Failed to connect to DB: {e}")
    st.stop()

# Determine which tables to use based on mode
if mode == "TEST":
    positions_table = db.test_positions_table
    orders_table = db.test_orders_table
else:
    positions_table = db.positions_table
    orders_table = db.orders_table

# === Account Summary ===
st.subheader(f"🏦 Account Summary ({mode})")

# Get P&L Stats
pnl_stats = db.get_account_pnl(mode=mode)

# Calculate Balance (Mock logic for now, or fetch from DB if we persisted account state)
initial_balance = config['trading'].get('test_initial_balance', 10000.0)
current_balance = initial_balance + pnl_stats['closed_pnl'] # Simple approximation
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

# Create tabs
tab1, tab2, tab3 = st.tabs(["📋 All Positions", "📦 All Orders", "📈 Signals"])

# === TAB 1: Positions ===
with tab1:
    st.subheader("Position History")
    
    try:
        response = positions_table.scan()
        positions = response.get('Items', [])
        
        if positions:
            df = pd.DataFrame(positions)
            
            # Convert timestamps
            if 'entry_time' in df.columns:
                df['entry_time'] = pd.to_datetime(df['entry_time'].astype(int), unit='ms')
            if 'exit_time' in df.columns:
                df['exit_time'] = pd.to_datetime(df['exit_time'].astype(int), unit='ms')
            
            # Convert Decimal to float
            numeric_cols = ['entry_price', 'exit_price', 'quantity', 'pnl', 'current_price']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            
            # Sort by entry time, most recent first
            df = df.sort_values('entry_time', ascending=False)
            
            # Separate open and closed
            open_pos = df[df['status'] == 'open']
            closed_pos = df[df['status'] == 'closed']
            
            # Display open positions
            st.markdown("### 🟢 Open Positions")
            if not open_pos.empty:
                display_cols = ['symbol', 'side', 'entry_price', 'quantity', 'entry_time']
                if 'current_price' in open_pos.columns:
                    display_cols.insert(3, 'current_price')
                if 'pnl' in open_pos.columns:
                    display_cols.append('pnl')
                    
                st.dataframe(open_pos[display_cols], use_container_width=True)
            else:
                st.info("No open positions")
            
            st.divider()
            
            # Display closed positions
            st.markdown("### 📜 Closed Positions")
            if not closed_pos.empty:
                display_cols = ['symbol', 'side', 'entry_price', 'exit_price', 'quantity', 'pnl', 'entry_time', 'exit_time']
                st.dataframe(closed_pos[display_cols], use_container_width=True)
                
                # Summary stats
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Closed", len(closed_pos))
                with col2:
                    wins = len(closed_pos[closed_pos['pnl'] > 0])
                    st.metric("Wins", wins)
                with col3:
                    losses = len(closed_pos[closed_pos['pnl'] < 0])
                    st.metric("Losses", losses)
                with col4:
                    win_rate = (wins / len(closed_pos) * 100) if len(closed_pos) > 0 else 0
                    st.metric("Win Rate", f"{win_rate:.1f}%")
            else:
                st.info("No closed positions yet")
                
        else:
            st.info("No position data available")
            
    except Exception as e:
        st.error(f"Error loading positions: {e}")

# === TAB 2: Orders ===
with tab2:
    st.subheader("Order History")
    
    try:
        response = orders_table.scan()
        orders = response.get('Items', [])
        
        if orders:
            df = pd.DataFrame(orders)
            
            # Convert timestamps
            if 'created_at' in df.columns:
                df['created_at'] = pd.to_datetime(df['created_at'].astype(int), unit='ms')
            if 'filled_at' in df.columns:
                df['filled_at'] = pd.to_datetime(df['filled_at'].astype(int), unit='ms')
            if 'expires_at' in df.columns:
                df['expires_at'] = pd.to_datetime(df['expires_at'].astype(int), unit='ms')
            
            # Convert Decimal to float
            numeric_cols = ['price', 'amount', 'fill_price']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            
            # Sort by created time, most recent first
            df = df.sort_values('created_at', ascending=False)
            
            # Status filter
            status_filter = st.multiselect(
                "Filter by status",
                options=['pending', 'filled', 'expired', 'canceled'],
                default=['filled', 'pending']
            )
            
            filtered_df = df[df['status'].isin(status_filter)]
            
            # Display columns based on what's available
            display_cols = ['order_id', 'symbol', 'side', 'price', 'amount', 'status', 'created_at']
            if 'filled_at' in filtered_df.columns:
                display_cols.append('filled_at')
            
            st.dataframe(filtered_df[display_cols], use_container_width=True)
            
            # Summary
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Orders", len(df))
            with col2:
                filled = len(df[df['status'] == 'filled'])
                st.metric("Filled", filled)
            with col3:
                pending = len(df[df['status'] == 'pending'])
                st.metric("Pending", pending)
            with col4:
                expired = len(df[df['status'] == 'expired'])
                st.metric("Expired", expired)
                
        else:
            st.info("No order data available")
            
    except Exception as e:
        st.error(f"Error loading orders: {e}")

# === TAB 3: Signals ===
with tab3:
    st.subheader("Generated Signals")
    
    try:
        # Signals are logged to signals table
        response = db.signals_table.scan()
        signals = response.get('Items', [])
        
        if signals:
            df = pd.DataFrame(signals)
            
            # Convert timestamp
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
            
            # Convert price to float
            if 'price' in df.columns:
                df['price'] = df['price'].astype(float)
            
            # Sort by timestamp, most recent first
            df = df.sort_values('timestamp', ascending=False)
            
            # Display
            display_cols = ['timestamp', 'symbol', 'signal', 'algo', 'price']
            st.dataframe(df[display_cols], use_container_width=True)
            
            # Summary
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Signals", len(df))
            with col2:
                buys = len(df[df['signal'] == 'BUY'])
                st.metric("BUY Signals", buys)
            with col3:
                sells = len(df[df['signal'] == 'SELL'])
                st.metric("SELL Signals", sells)
                
        else:
            st.info("No signals generated yet - waiting for SMA crossovers...")
            
    except Exception as e:
        st.error(f"Error loading signals: {e}")

# Refresh button
st.divider()
if st.button("🔄 Refresh Data"):
    st.rerun()
