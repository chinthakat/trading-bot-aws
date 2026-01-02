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
            # Fix: Ensure timestamp is numeric
            df_trades['timestamp'] = pd.to_numeric(df_trades['timestamp'])
            df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'], unit='ms')
            
            st.dataframe(df_trades[['timestamp', 'symbol', 'action', 'price', 'amount', 'algo']])
        else:
            st.info("No trades found.")
    else:
        st.warning("DB Not Connected")

with col2:
    st.subheader("Performance / Stats")
    st.markdown("Total PnL: **$0.00** (Not Implemented yet in data)")
    
    st.markdown("---")
    st.subheader("Price Analysis")
    
    if db_connected:
        # Symbol Selector
        # Ideally fetch unique symbols from DB or config
        symbols = config['trading']['symbols']
        selected_symbol = st.selectbox("Select Symbol", symbols)
        
        # Date Range / Limit selector
        limit = st.slider("History Check (datapoints)", 50, 500, 200)
        
        if st.button("Load Graph"):
            with st.spinner("Fetching data..."):
                try:
                    prices = db.get_price_history(selected_symbol, limit=limit)
                    
                    if prices:
                        df = pd.DataFrame(prices)
                        df['price'] = df['price'].astype(float)
                        # Fix: Ensure timestamp is numeric (handle Decimal/String from DB)
                        df['timestamp'] = pd.to_numeric(df['timestamp'])
                        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                        df = df.set_index('timestamp')
                        
                        # Calculate Indicators on the fly
                        import ta
                        
                        # Moving Averages (matching config if possible, or generic)
                        # We use the defaults from config for the 'MA_Crossover' strategy
                        ma_params = config['trading']['active_strategies']['MA_Crossover']['params']
                        short_window = ma_params['short_period']
                        long_window = ma_params['long_period']
                        
                        df[f'SMA_{short_window}'] = ta.trend.sma_indicator(df['price'], window=short_window)
                        df[f'SMA_{long_window}'] = ta.trend.sma_indicator(df['price'], window=long_window)
                        
                        # Filter down to relevant columns for clean chart
                        chart_data = df[['price', f'SMA_{short_window}', f'SMA_{long_window}']]
                        
                        st.line_chart(chart_data)
                        
                        # Show latest values
                        latest = df.iloc[-1]
                        st.metric("Latest Price", f"${latest['price']:.2f}")
                        st.text(f"SMA {short_window}: {latest[f'SMA_{short_window}']:.2f}")
                        st.text(f"SMA {long_window}: {latest[f'SMA_{long_window}']:.2f}")
                        
                    else:
                        st.warning(f"No price data found for {selected_symbol}.")
                        
                except Exception as e:
                    st.error(f"Error loading graph: {e}")
    else:
        st.warning("DB Not Connected - Cannot plot graphs.")

st.markdown("---")
st.markdown("### System Logs")
st.text("To view logs, check AWS CloudWatch or the running EC2 shell.")
