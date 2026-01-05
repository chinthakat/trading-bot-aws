import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
import os
import sys
import json
from decimal import Decimal
from datetime import datetime

# Add app directory to path to import persistence
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from persistence import DynamoManager
from strategy_loader import StrategyLoader

st.set_page_config(
    page_title="Live Candle Chart",
    page_icon="🕯️",
    layout="wide"
)

st.title("🕯️ Live Bot Candles (1m)")

# === Bot Status Indicator ===
def get_bot_status():
    try:
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'api_logs.txt')
        if not os.path.exists(log_path):
            return "🔴", "Offline (No logs)", "red"
        
        with open(log_path, 'rb') as f:
            try:
                f.seek(-1024, os.SEEK_END)
            except OSError:
                pass 
            last_lines = f.readlines()
            
        if not last_lines:
             return "🔴", "Offline (Empty logs)", "red"
             
        # Find last valid line
        last_valid_line = None
        for line in reversed(last_lines):
            decoded = line.decode('utf-8', errors='ignore').strip()
            if "[WS UPDATE]" in decoded or "[HEARTBEAT]" in decoded:
                last_valid_line = decoded
                break
        
        if not last_valid_line:
             last_valid_line = last_lines[-1].decode('utf-8', errors='ignore').strip()

        parts = last_valid_line.split(' [')
        if len(parts) > 0:
            ts_str = parts[0].strip()
            try:
                # Remove microseconds/milliseconds if present (handles . or ,)
                if ',' in ts_str:
                    ts_str = ts_str.split(',')[0]
                elif '.' in ts_str:
                    ts_str = ts_str.split('.')[0]
                    
                last_active = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                diff = (datetime.now() - last_active).total_seconds()
                
                if diff < 120: return "🟢", f"Online (Last beat: {int(diff)}s ago)", "green"
                elif diff < 300: return "🟠", f"Lagging (Last beat: {int(diff)}s ago)", "orange"
                else: return "🔴", f"Offline (Last beat: {int(diff)}s ago)", "red"
            except Exception as e:
                return "⚪", f"Unknown (Parse Error: {e})", "gray"
        return "⚪", "Unknown", "gray"
            
    except Exception as e:
        return "🔴", f"Error check: {e}", "red"

icon, msg, color = get_bot_status()
st.markdown(f"**Status:** {icon} <span style='color:{color}'>{msg}</span>", unsafe_allow_html=True)


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
    return db.get_price_history(symbol, limit=limit)

with st.spinner(f"Fetching {symbol} candles..."):
    items = fetch_bot_data(symbol, limit)

if not items:
    st.warning("No candle data found yet. Wait for the next 1m close...")
    if st.checkbox("Auto-Refresh", value=True):
        time.sleep(refresh_rate)
        st.rerun()
    st.stop()

df = pd.DataFrame(items)

# Clean Data
numeric_cols = ['open', 'high', 'low', 'close', 'volume']
# Add potential indicator columns dynamically
for c in df.columns:
    if c not in numeric_cols and c not in ['symbol', 'timestamp', 'expiry']:
        numeric_cols.append(c)

for col in numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

df = df.dropna(subset=['open', 'high', 'low', 'close'])
if df.empty:
    st.warning("No valid candle data found after cleaning.")
    st.stop()

df['timestamp'] = pd.to_numeric(df['timestamp'])
df['timestamp_dt'] = pd.to_datetime(df['timestamp'], unit='ms')

# === Strategy Tabs ===
active_strategies = config['trading']['active_strategies']
enabled_strategies = [k for k, v in active_strategies.items() if v['enabled']]
# Add 'Overview' or 'Manual' tab if needed? 
# User wanted "Create isolated views for each active strategy."
tabs = st.tabs(enabled_strategies)

# Mode
mode = config['trading'].get('mode', 'TEST')
positions_table = db.test_positions_table if mode == "TEST" else db.positions_table
orders_table = db.test_orders_table if mode == "TEST" else db.orders_table

# Pre-fetch Trade Data (All Strategies)
min_ts = df['timestamp'].min()

try:
    # Positions
    position_response = positions_table.scan(FilterExpression='symbol = :sym AND entry_time >= :min_ts', ExpressionAttributeValues={':sym': symbol, ':min_ts': Decimal(str(min_ts))})
    all_positions = position_response.get('Items', [])

    # Orders (Filled)
    order_response = orders_table.scan(FilterExpression='symbol = :sym AND #st = :filled AND filled_at >= :min_ts', ExpressionAttributeNames={'#st': 'status'}, ExpressionAttributeValues={':sym': symbol, ':filled': 'filled', ':min_ts': Decimal(str(min_ts))})
    all_filled_orders = order_response.get('Items', [])

    # Signals
    signal_response = db.signals_table.scan(FilterExpression='symbol = :sym AND #ts >= :min_ts', ExpressionAttributeNames={'#ts': 'timestamp'}, ExpressionAttributeValues={':sym': symbol, ':min_ts': Decimal(str(min_ts))})
    all_signals = signal_response.get('Items', [])

except Exception as e:
    st.error(f"Error loading trade data: {e}")
    all_positions, all_filled_orders, all_signals = [], [], []

# Render Tabs
for i, strategy_name in enumerate(enabled_strategies):
    with tabs[i]:
        st.subheader(f"{strategy_name} Analysis")
        
        # 1. Get Strategy Config for Plotting
        try:
            # We need to instantiate or get class to read PLOT_CONFIG
            # Quick hack: Load strategy class safely without config
            # Quick hack: Load strategy class safely without config
            StrategyLoader._strategies = {} # Reset
            # Ensure we reload modules if they changed on disk
            import strategies
            import importlib
            importlib.reload(strategies)
            # We might need to reload submodules too if they are imported in strategies/__init__.py
            # But discover_strategies iterates pkgutil. 
            
            StrategyLoader.discover_strategies()
            strat_class = StrategyLoader._strategies.get(strategy_name)
            
            plot_config = getattr(strat_class, 'PLOT_CONFIG', {})
            plot_indicators = plot_config.get('indicators', [])
            plot_colors = plot_config.get('colors', [])
            
        except Exception as e:
            st.caption(f"Could not load plot config: {e}")
            plot_indicators = []
            plot_colors = []

        # 2. Filter Data for this Strategy
        # Signals: direct match on 'algo'
        strat_signals = [s for s in all_signals if s.get('algo') == strategy_name]
        
        # Positions: direct match on 'strategy_name'
        strat_positions = [p for p in all_positions if p.get('strategy_name', 'manual') == strategy_name]
        
        # Orders: direct match on 'strategy_name'
        strat_orders = [o for o in all_filled_orders if o.get('strategy_name', 'manual') == strategy_name]

        # 3. Build Chart
        fig = go.Figure()

        # Candles (Always show)
        fig.add_trace(go.Candlestick(
            x=df['timestamp_dt'],
            open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            name='OHLC'
        ))

        # Indicators (Strategy Specific)
        for idx, col in enumerate(plot_indicators):
            if col in df.columns:
                color = plot_colors[idx % len(plot_colors)]
                fig.add_trace(go.Scatter(
                    x=df['timestamp_dt'], y=df[col],
                    line=dict(color=color, width=1),
                    name=col.upper()
                ))
        
        # Markers
        def add_marker_trace(items, type_label, color, symbol_shape, size=10):
            x, y, hover = [], [], []
            for item in items:
                # Timestamps
                if type_label == 'Signal':
                    ts = pd.to_datetime(int(item['timestamp']), unit='ms')
                    price = float(item['price'])
                    sig_type = item['signal'] # BUY/SELL
                elif type_label == 'Position':
                    ts = pd.to_datetime(int(item['entry_time']), unit='ms')
                    price = float(item['entry_price'])
                    sig_type = item['side'].upper()
                elif type_label == 'Fill':
                    ts = pd.to_datetime(int(item['filled_at']), unit='ms')
                    price = float(item.get('price', 0))
                    sig_type = item['side'].upper()
                
                # Filter by side/color logic happens at caller? 
                # Actually, specialized lists below
                x.append(ts)
                y.append(price)
                hover.append(f"{type_label} {sig_type}<br>{price}")
            
            if x:
                fig.add_trace(go.Scatter(
                    x=x, y=y, mode='markers',
                    marker=dict(size=size, color=color, symbol=symbol_shape, line=dict(width=1, color='black')),
                    name=f"{type_label}s", hovertemplate="%{hovertext}", hovertext=hover
                ))

        # Signals
        sig_buy = [s for s in strat_signals if s['signal'] == 'BUY']
        sig_sell = [s for s in strat_signals if s['signal'] == 'SELL']
        add_marker_trace(sig_buy, 'Signal', 'blue', 'star', 12)
        add_marker_trace(sig_sell, 'Signal', 'orange', 'x', 12)

        # Positions
        pos_long = [p for p in strat_positions if p['side'] == 'long']
        pos_short = [p for p in strat_positions if p['side'] == 'short']
        add_marker_trace(pos_long, 'Position', 'green', 'triangle-up', 15)
        add_marker_trace(pos_short, 'Position', 'red', 'triangle-down', 15)

        # Layout
        fig.update_layout(
            title=f"{symbol} - {strategy_name}",
            yaxis_title="Price",
            height=600,
            template="plotly_white",
            xaxis_rangeslider_visible=False
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # 4. Strategy Specific Stats
        cols = st.columns(4)
        wins = len([p for p in strat_positions if p.get('pnl', 0) > 0 and p['status'] == 'closed'])
        losses = len([p for p in strat_positions if p.get('pnl', 0) < 0 and p['status'] == 'closed'])
        pnl = sum([float(p.get('pnl', 0)) for p in strat_positions])
        
        cols[0].metric("Total PnL", f"${pnl:.2f}")
        cols[1].metric("Trades", len(strat_positions))
        cols[2].metric("Wins", wins)
        cols[3].metric("Losses", losses)

if st.checkbox("Auto-Refresh", value=True):
    time.sleep(refresh_rate)
    st.rerun()
