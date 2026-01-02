import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
import os
import sys
import json
from decimal import Decimal

# Add app directory to path to import persistence
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from persistence import DynamoManager

st.set_page_config(
    page_title="Live Candle Chart",
    page_icon="🕯️",
    layout="wide"
)

st.title("🕯️ Live Bot Candles (1m)")

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

# Sidebar
symbols = config['trading']['symbols']
symbol = st.sidebar.selectbox("Symbol", symbols)
limit = st.sidebar.slider("Candles to Load", 50, 500, 100)
refresh_rate = st.sidebar.slider("Refresh Rate (sec)", 5, 60, 5)

# DB Connection
try:
    db = DynamoManager(config)
except Exception as e:
    st.error(f"Failed to connect to DB: {e}")
    st.stop()

# Helper to fetch data
@st.cache_data(ttl=3) 
def fetch_bot_data(symbol, limit):
    # We reuse get_price_history but it now returns candle dicts
    return db.get_price_history(symbol, limit=limit)

with st.spinner(f"Fetching {symbol} candles..."):
    items = fetch_bot_data(symbol, limit)

if items:
    df = pd.DataFrame(items)
    
    # Filter for valid candle rows only (must have open, high, low, close)
    required_cols = ['open', 'high', 'low', 'close']
    if not set(required_cols).issubset(df.columns):
        # Identify rows that might be missing these columns? 
        # Actually, if the DataFrame columns don't exist, it means NO row has them (or they are NaNs).
        # We need to drop rows where these are NaN if columns exist, OR stop if columns don't exist.
        
        # If columns missing entirely, we can't plot candles.
        # But we might have mixed data where some items have it.
        # DynamoDB scans usually return all keys found across items? No, it returns list of dicts.
        # Pandas constructor will make columns for all keys found.
        
        # Check if columns exist at least
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.warning(f"Waiting for Candle Data... (Received data missing: {missing})")
            if st.checkbox("Auto-Refresh", value=True):
                 time.sleep(refresh_rate)
                 st.rerun()
            st.stop()
            
    # Drop rows with NaN in required columns (clean mixed data)
    df = df.dropna(subset=required_cols)
    
    if df.empty:
        st.warning("No valid candle data found yet. (Old price data ignored)")
        if st.checkbox("Auto-Refresh", value=True):
             time.sleep(refresh_rate)
             st.rerun()
        st.stop()

    # Process Types
    # DynamoDB Decimals -> Float
    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(float)
            
    df['timestamp'] = pd.to_numeric(df['timestamp'])
    df['timestamp_dt'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # Identify Indicator Columns (e.g. sma_10, sma_100)
    ignore = numeric_cols + ['symbol', 'timestamp', 'timestamp_dt', 'expiry']
    indicators = [c for c in df.columns if c not in ignore]
    for col in indicators:
         df[col] = df[col].astype(float)

    # Plot
    fig = go.Figure()

    # Candlestick Trace
    fig.add_trace(go.Candlestick(
        x=df['timestamp_dt'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='OHLC'
    ))

    # Indicators
    colors = ['orange', 'blue', 'purple', 'black']
    for i, col in enumerate(indicators):
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=df['timestamp_dt'],
            y=df[col],
            line=dict(color=color, width=1),
            name=col.upper()
        ))

    fig.update_layout(
        title=f"{symbol} Real-Time Bot Stream",
        yaxis_title="Price (USDT)",
        xaxis_rangeslider_visible=False,
        height=700,
        template="plotly_white" # Easier to read candles
    )

    st.plotly_chart(fig, use_container_width=True)
    
    if st.checkbox("Auto-Refresh", value=True):
        time.sleep(refresh_rate)
        st.rerun()

else:
    st.warning("No candle data found yet. Wait for the next 1m close...")
