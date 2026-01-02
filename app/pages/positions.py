import streamlit as st
import pandas as pd
from persistence import DynamoManager
import json

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

db = DynamoManager(config)

st.title("📊 Position Management")

# Get account-level P&L
pnl_stats = db.get_account_pnl()

# Display account summary in columns
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total P&L", f"${pnl_stats['total_pnl']:.2f}", 
              help="Total realized + unrealized P&L")

with col2:
    st.metric("Open P&L", f"${pnl_stats['open_pnl']:.2f}",
              help="Unrealized P&L from open positions")

with col3:
    st.metric("Closed P&L", f"${pnl_stats['closed_pnl']:.2f}",
              help="Realized P&L from closed positions")

with col4:
    win_rate_pct = pnl_stats['win_rate'] * 100
    st.metric("Win Rate", f"{win_rate_pct:.1f}%",
              help=f"{pnl_stats['win_count']} wins, {pnl_stats['loss_count']} losses")

st.divider()

# Fetch positions from DynamoDB
try:
    response = db.positions_table.scan()
    positions = response.get('Items', [])
    
    if positions:
        # Separate open and closed positions
        open_positions = [p for p in positions if p.get('status') == 'open']
        closed_positions = [p for p in positions if p.get('status') == 'closed']
        
        # Display open positions
        st.subheader("🟢 Open Positions")
        if open_positions:
            open_df = pd.DataFrame(open_positions)
            
            # Format for display
            if not open_df.empty:
                display_cols = ['symbol', 'side', 'entry_price', 'quantity', 'pnl']
                if 'current_price' in open_df.columns:
                    display_cols.insert(3, 'current_price')
                    
                display_df = open_df[display_cols].copy()
                
                # Convert Decimal to float for display
                for col in ['entry_price', 'quantity', 'pnl']:
                    if col in display_df.columns:
                        display_df[col] = display_df[col].astype(float)
                if 'current_price' in display_df.columns:
                    display_df['current_price'] = display_df['current_price'].astype(float)
                
                # Color code P&L
                def color_pnl(val):
                    color = 'green' if val > 0 else 'red' if val < 0 else 'gray'
                    return f'color: {color}'
                
                styled_df = display_df.style.applymap(color_pnl, subset=['pnl'])
                st.dataframe(styled_df, use_container_width=True)
        else:
            st.info("No open positions")
        
        st.divider()
        
        # Display closed positions
        st.subheader("📜 Closed Positions (Recent)")
        if closed_positions:
            closed_df = pd.DataFrame(closed_positions)
            
            # Sort by exit time, most recent first
            if 'exit_time' in closed_df.columns:
                closed_df = closed_df.sort_values('exit_time', ascending=False)
            
            # Limit to recent 10
            closed_df = closed_df.head(10)
            
            # Format for display
            display_cols = ['symbol', 'side', 'entry_price', 'exit_price', 'quantity', 'pnl']
            display_df = closed_df[display_cols].copy()
            
            # Convert Decimal to float
            for col in ['entry_price', 'exit_price', 'quantity', 'pnl']:
                if col in display_df.columns:
                    display_df[col] = display_df[col].astype(float)
            
            styled_df = display_df.style.applymap(color_pnl, subset=['pnl'])
            st.dataframe(styled_df, use_container_width=True)
        else:
            st.info("No closed positions yet")
    else:
        st.info("No position data available")
        
except Exception as e:
    st.error(f"Error loading positions: {e}")

# Display pending orders
st.divider()
st.subheader("⏳ Pending Orders")

try:
    response = db.orders_table.scan()
    orders = response.get('Items', [])
    
    pending_orders = [o for o in orders if o.get('status') == 'pending']
    
    if pending_orders:
        orders_df = pd.DataFrame(pending_orders)
        display_cols = ['order_id', 'symbol', 'side', 'price', 'amount', 'status']
        display_df = orders_df[display_cols].copy()
        
        # Convert Decimal to float
        for col in ['price', 'amount']:
            if col in display_df.columns:
                display_df[col] = display_df[col].astype(float)
        
        st.dataframe(display_df, use_container_width=True)
    else:
        st.info("No pending orders")
        
except Exception as e:
    st.error(f"Error loading orders: {e}")

# Refresh button
if st.button("🔄 Refresh Data"):
    st.rerun()
