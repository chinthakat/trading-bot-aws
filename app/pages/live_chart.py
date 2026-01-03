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
        
        # Read last line efficiently
        with open(log_path, 'rb') as f:
            try:
                f.seek(-1024, os.SEEK_END)
            except OSError:
                pass # File smaller than 1024 bytes
            last_lines = f.readlines()
            
        if not last_lines:
             return "🔴", "Offline (Empty logs)", "red"
             
        # Find last line with timestamp
        # Iterate backwards to find a valid line
        last_valid_line = None
        for line in reversed(last_lines):
            decoded = line.decode('utf-8', errors='ignore').strip()
            if "[WS UPDATE]" in decoded:
                last_valid_line = decoded
                break
        
        if not last_valid_line:
            # Fallback to just last line if we can't find tag
             last_valid_line = last_lines[-1].decode('utf-8', errors='ignore').strip()

        # Format: 2026-01-03 01:10:05 [WS UPDATE] ...
        # Or standard log: 2026-01-03 ... [INFO] ...
        # Both start with timestamp YYYY-MM-DD HH:MM:SS
        parts = last_valid_line.split(' [')
        if len(parts) > 0:
            ts_str = parts[0].strip()
            # Try parsing
            try:
                # Handle potential millisecond formatting if present, though bot.py uses %Y-%m-%d %H:%M:%S
                ts_str = ts_str.split(',')[0] # Remove milliseconds if typical logging
                last_active = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                
                diff = (datetime.now() - last_active).total_seconds()
                
                if diff < 120: # 2 mins
                    return "🟢", f"Online (Last beat: {int(diff)}s ago)", "green"
                elif diff < 300: # 5 mins
                    return "🟠", f"Lagging (Last beat: {int(diff)}s ago)", "orange"
                else:
                    return "🔴", f"Offline (Last beat: {int(diff)}s ago)", "red"
            except Exception as e:
                # Fallback if parse fails
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

# === Manual Trading Controls ===
manual_trading_enabled = config['trading'].get('manual_trading_enabled', False)
mode = config['trading'].get('mode', 'TEST')

if manual_trading_enabled:
    st.sidebar.divider()
    st.sidebar.subheader("🎮 Manual Trading")
    st.sidebar.caption(f"Mode: **{mode}**")
    
    col1, col2 = st.sidebar.columns(2)
    
    with col1:
        if st.button("🟢 BUY", use_container_width=True, type="primary"):
            try:
                # Import PositionManager
                sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                from position_manager import PositionManager
                import ccxt
                
                # Get latest price
                latest_items = db.get_price_history(symbol, limit=1)
                if latest_items:
                    current_price = float(latest_items[0]['close'])
                    
                    # Initialize exchange and PositionManager
                    exchange_class = getattr(ccxt, config['exchange']['id'])
                    exchange = exchange_class({
                        'apiKey': os.getenv('BINANCE_API_KEY'),
                        'secret': os.getenv('BINANCE_SECRET'),
                        'enableRateLimit': True,
                        'options': config['exchange']['options']
                    })
                    
                    if config['exchange'].get('testnet'):
                        exchange.set_sandbox_mode(True)
                    
                    pm = PositionManager(exchange, db, config['trading']['risk_management'], mode)
                    
                    # Calculate size and place order
                    if pm.can_open_position(symbol):
                        amount = pm.calculate_position_size(symbol, current_price)
                        if amount:
                            order = pm.place_limit_order(symbol, 'buy', current_price, amount)
                            if order:
                                # Log manual signal
                                db.log_signal({
                                    'symbol': symbol,
                                    'signal': 'BUY',
                                    'algo': 'MANUAL',
                                    'price': current_price,
                                    'timestamp': int(time.time() * 1000)
                                })
                                st.sidebar.success(f"✅ BUY order placed @ ${current_price:.2f}")
                                st.sidebar.caption(f"Order ID: {order.get('order_id', 'N/A')}")
                            else:
                                st.sidebar.error("❌ Order placement returned None")
                        else:
                            st.sidebar.error("❌ Failed to calculate position size")
                    else:
                        st.sidebar.warning("⚠️ Cannot open position (already have one open)")
                else:
                    st.sidebar.error("❌ No price data available")
            except Exception as e:
                st.sidebar.error(f"❌ Error: {str(e)}")
                import traceback
                st.sidebar.code(traceback.format_exc())
    
    with col2:
        if st.button("🔴 SELL", use_container_width=True, type="secondary"):
            try:
                sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                from position_manager import PositionManager
                import ccxt
                
                latest_items = db.get_price_history(symbol, limit=1)
                if latest_items:
                    current_price = float(latest_items[0]['close'])
                    
                    exchange_class = getattr(ccxt, config['exchange']['id'])
                    exchange = exchange_class({
                        'apiKey': os.getenv('BINANCE_API_KEY'),
                        'secret': os.getenv('BINANCE_SECRET'),
                        'enableRateLimit': True,
                        'options': config['exchange']['options']
                    })
                    
                    if config['exchange'].get('testnet'):
                        exchange.set_sandbox_mode(True)
                    
                    pm = PositionManager(exchange, db, config['trading']['risk_management'], mode)
                    
                    if pm.can_open_position(symbol):
                        amount = pm.calculate_position_size(symbol, current_price)
                        if amount:
                            order = pm.place_limit_order(symbol, 'sell', current_price, amount)
                            if order:
                                db.log_signal({
                                    'symbol': symbol,
                                    'signal': 'SELL',
                                    'algo': 'MANUAL',
                                    'price': current_price,
                                    'timestamp': int(time.time() * 1000)
                                })
                                st.sidebar.success(f"✅ SELL order placed @ ${current_price:.2f}")
                                st.sidebar.caption(f"Order ID: {order.get('order_id', 'N/A')}")
                            else:
                                st.sidebar.error("❌ Order placement returned None")
                        else:
                            st.sidebar.error("❌ Failed to calculate position size")
                    else:
                        st.sidebar.warning("⚠️ Cannot open position (already have one open)")
                else:
                    st.sidebar.error("❌ No price data available")
            except Exception as e:
                st.sidebar.error(f"❌ Error: {str(e)}")
                import traceback
                st.sidebar.code(traceback.format_exc())
    
    st.sidebar.caption("⚠️ Orders use exchange minimum quantity")


# === Active Stats Display ===
st.markdown("### 📊 Active Status")
stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)

# 1. Active Position
active_pos = db.get_active_position(mode)
if active_pos and active_pos['symbol'] == symbol:
    side = active_pos['side'].upper()
    entry = float(active_pos['entry_price'])
    qty = float(active_pos['quantity'])
    pnl = float(active_pos.get('pnl', 0))
    
    # Calculate current PnL if we have price
    # We fetch candle data later, but we can do a quick check here or wait?
    # Let's just use what's in DB or wait for the chart data? 
    # DB might be stale if bot updates slowly.
    # Let's display what we have.
    
    color = "normal"
    if pnl > 0: color = "off" # Streamlit metric delta handles color
    
    with stats_col1:
        st.metric("Active Position", f"{side} {qty}", delta=f"{pnl:.2f} USDT", delta_color="normal")
    with stats_col2:
        st.metric("Entry Price", f"{entry:.2f}")
else:
    with stats_col1:
        st.metric("Active Position", "None")
    with stats_col2:
        st.metric("PnL", "0.00")

# 2. Pending Orders
# Scan for pending orders for this symbol
if mode == "TEST":
    o_table = db.test_orders_table
else:
    o_table = db.orders_table

try:
    resp = o_table.scan(
        FilterExpression='symbol = :sym AND #st = :pending',
        ExpressionAttributeNames={'#st': 'status'},
        ExpressionAttributeValues={':sym': symbol, ':pending': 'pending'}
    )
    pending_orders = resp.get('Items', [])
    buy_orders = [o for o in pending_orders if o['side'] == 'buy']
    sell_orders = [o for o in pending_orders if o['side'] == 'sell']
    
    with stats_col3:
        st.metric("Pending Buys", f"{len(buy_orders)}")
    with stats_col4:
        st.metric("Pending Sells", f"{len(sell_orders)}")

except Exception as e:
    st.error(f"Error fetching orders: {e}")

st.divider()


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
    
    # === Trade Event Markers ===
    mode = config['trading'].get('mode', 'TEST')
    
    
    # Determine which tables to query based on mode
    if mode == "TEST":
        positions_table = db.test_positions_table
        orders_table = db.test_orders_table
    else:
        positions_table = db.positions_table
        orders_table = db.orders_table
    
    try:
        # Calculate cutoff time from oldest candle
        min_ts = df['timestamp'].min()
        
        # Get positions (entry points)
        # Use FilterExpression to only get relevant ones if possible, or filter in Python
        position_response = positions_table.scan(
            FilterExpression='symbol = :sym AND entry_time >= :min_ts',
            ExpressionAttributeValues={
                ':sym': symbol,
                ':min_ts': Decimal(str(min_ts))
            }
        )
        positions = position_response.get('Items', [])
        
        # Get filled orders (trade executions)
        order_response = orders_table.scan(
            FilterExpression='symbol = :sym AND #st = :filled AND filled_at >= :min_ts',
            ExpressionAttributeNames={'#st': 'status'},
            ExpressionAttributeValues={
                ':sym': symbol, 
                ':filled': 'filled',
                ':min_ts': Decimal(str(min_ts))
            }
        )
        filled_orders = order_response.get('Items', [])
        
        # Get signals
        signal_response = db.signals_table.scan(
            FilterExpression='symbol = :sym AND #ts >= :min_ts',
            ExpressionAttributeNames={'#ts': 'timestamp'},
            ExpressionAttributeValues={
                ':sym': symbol,
                ':min_ts': Decimal(str(min_ts))
            }
        )
        signals = signal_response.get('Items', [])
        
        # Prepare data containers
        signal_buy_x, signal_buy_y, signal_buy_hover = [], [], []
        signal_sell_x, signal_sell_y, signal_sell_hover = [], [], []
        
        pos_long_x, pos_long_y, pos_long_hover = [], [], []
        pos_short_x, pos_short_y, pos_short_hover = [], [], []
        
        fill_buy_x, fill_buy_y, fill_buy_hover = [], [], []
        fill_sell_x, fill_sell_y, fill_sell_hover = [], [], []

        # Process Signals
        for signal in signals:
            t = pd.to_datetime(int(signal['timestamp']), unit='ms')
            p = float(signal['price'])
            h = f'<b>{signal["signal"]} SIGNAL</b><br>Price: ${p:.2f}<br>Time: {t}<br>Algo: {signal.get("algo", "N/A")}<extra></extra>'
            
            if signal['signal'] == 'BUY':
                signal_buy_x.append(t)
                signal_buy_y.append(p)
                signal_buy_hover.append(h)
            else:
                signal_sell_x.append(t)
                signal_sell_y.append(p)
                signal_sell_hover.append(h)

        # Process Positions
        for pos in positions:
            t = pd.to_datetime(int(pos['entry_time']), unit='ms')
            p = float(pos['entry_price'])
            side = pos['side'].upper()
            h = f'<b>{side} Position</b><br>Price: ${p:.2f}<br>Time: {t}<extra></extra>'
            
            if pos['side'] == 'long':
                pos_long_x.append(t)
                pos_long_y.append(p)
                pos_long_hover.append(h)
            else:
                pos_short_x.append(t)
                pos_short_y.append(p)
                pos_short_hover.append(h)

        # Process Fills
        for order in filled_orders:
            if 'filled_at' in order and order['filled_at']:
                t = pd.to_datetime(int(order['filled_at']), unit='ms')
                p = float(order.get('price', 0))
                side = order['side'].upper()
                h = f'<b>{side} Fill</b><br>Price: ${p:.2f}<br>Time: {t}<extra></extra>'
                
                if order['side'] == 'buy':
                    fill_buy_x.append(t)
                    fill_buy_y.append(p)
                    fill_buy_hover.append(h)
                else:
                    fill_sell_x.append(t)
                    fill_sell_y.append(p)
                    fill_sell_hover.append(h)

        # Helper to add trace
        def add_marker_trace(x, y, hover, name, color, symbol, size=12):
            if x:
                fig.add_trace(go.Scatter(
                    x=x, y=y, mode='markers',
                    marker=dict(size=size, color=color, symbol=symbol, line=dict(width=1, color='black')),
                    name=name, showlegend=True, hovertemplate=hover, hoverinfo='text'
                ))

        # Add Traces
        add_marker_trace(signal_buy_x, signal_buy_y, signal_buy_hover, 'Signal BUY', 'blue', 'star', 12)
        add_marker_trace(signal_sell_x, signal_sell_y, signal_sell_hover, 'Signal SELL', 'orange', 'x', 12)
        
        add_marker_trace(pos_long_x, pos_long_y, pos_long_hover, 'Position LONG', 'green', 'triangle-up', 15)
        add_marker_trace(pos_short_x, pos_short_y, pos_short_hover, 'Position SHORT', 'red', 'triangle-down', 15)
        
        add_marker_trace(fill_buy_x, fill_buy_y, fill_buy_hover, 'Fill BUY', 'lightgreen', 'diamond', 10)
        add_marker_trace(fill_sell_x, fill_sell_y, fill_sell_hover, 'Fill SELL', 'lightcoral', 'diamond', 10)
                
    except Exception as e:
        st.caption(f"⚠️ Could not load trade markers: {e}")

    fig.update_layout(
        title=f"{symbol} Real-Time Bot Stream [{mode} Mode]",
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
