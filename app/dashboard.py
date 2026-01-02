import streamlit as st
import pandas as pd
import json
import boto3
import time
from datetime import datetime
import os
import sys

# Add app directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from persistence import DynamoManager

# Page Config
st.set_page_config(
    page_title="Crypto Bot Dashboard",
    page_icon="📈",
    layout="wide"
)

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)

config = load_config()

# Helper: DynamoDB Connection
# Re-using persistence logic slightly modified for st caching usually, but here direct import
# Note: Streamlit re-runs script on interaction
try:
    db = DynamoManager(config)
    db_connected = True
except Exception as e:
    st.error(f"Failed to connect to DynamoDB: {e}")
    db_connected = False

# Sidebar: Controls
st.sidebar.title("Configuration")

# Trading Status
st.sidebar.subheader("Status")
if st.sidebar.button("Refresh Data"):
    st.rerun()

# Config Editor
st.sidebar.markdown("---")
st.sidebar.subheader("Strategy Config")

# Enable/Disable Strategies
active_strategies = config['trading']['active_strategies']
for name, settings in active_strategies.items():
    st.sidebar.markdown(f"**{name}**")
    enabled = st.sidebar.checkbox("Enabled", value=settings['enabled'], key=f"{name}_enabled")
    
    # Params
    params = settings['params']
    new_params = {}
    for p_key, p_val in params.items():
        new_params[p_key] = st.sidebar.number_input(f"{p_key}", value=p_val, key=f"{name}_{p_key}")
    
    # Update Config Object
    config['trading']['active_strategies'][name]['enabled'] = enabled
    config['trading']['active_strategies'][name]['params'] = new_params

if st.sidebar.button("Save Configuration"):
    save_config(config)
    st.sidebar.success("Configuration saved! Restart bot to apply.")

# Main Content
st.title("🤖 Binance Day Trading Bot")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Recent Trades")
    if db_connected:
        trades = db.get_trades(limit=20)
        if trades:
            df_trades = pd.DataFrame(trades)
            # Convert decimal to float for display
            df_trades['price'] = df_trades['price'].astype(float)
            df_trades['amount'] = df_trades['amount'].astype(float)
            df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'], unit='ms')
            
            st.dataframe(df_trades[['timestamp', 'symbol', 'action', 'price', 'amount', 'algo']])
        else:
            st.info("No trades found.")
    else:
        st.warning("DB Not Connected")

with col2:
    st.subheader("Performance / Stats")
    # Placeholder for PnL chart
    # In a real app we would query the 'stats' table
    st.markdown("Total PnL: **$0.00** (Not Implemented yet in data)")
    
    st.subheader("Live Price (Mock/Latest)")
    # Since we don't have a persistent stream in the dashboard, we can just show last price from DB if available
    # or just leave blank for now.
    st.info("Real-time plotting requires reading from Prices table or Stream.")
    
    if db_connected:
        # Try to scan prices just to see if we have any
        try:
            # Full scan is bad practice in prod, but for MVP/Debug:
            # Actually persistence.log_price logs to 'prices' table.
            # Let's just try to get a few.
            response = db.prices_table.scan(Limit=50)
            items = response.get('Items', [])
            if items:
                df_prices = pd.DataFrame(items)
                df_prices['price'] = df_prices['price'].astype(float)
                df_prices['timestamp'] = pd.to_datetime(df_prices['timestamp'], unit='ms')
                df_prices = df_prices.sort_values('timestamp')
                
                st.line_chart(df_prices.set_index('timestamp')['price'])
            else:
                st.text("No price data yet.")
        except Exception as e:
            st.text(f"Could not load prices: {e}")

st.markdown("---")
st.markdown("### System Logs")
st.text("To view logs, check AWS CloudWatch or the running EC2 shell.")
