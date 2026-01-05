
import streamlit as st
import pandas as pd
import json
import plotly.graph_objects as go
import time
import os
import sys

# Add app directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from services.db_service import SharedDbService
from admin_view import render_admin # Moved to app root

# Page Config
st.set_page_config(layout="wide", page_title="Trading Bot [SharedMem]", page_icon="⚡")

# Initialize DB
try:
    db = SharedDbService()
    st.sidebar.success("Connected to /dev/shm Shared DB")
except Exception as e:
    st.error(f"DB Connection Failed: {e}")
    st.stop()

# Helper: Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
def load_config():
    with open(CONFIG_PATH, 'r') as f: return json.load(f)
config = load_config()

# --- Sidebar ---
st.sidebar.header("Control Panel")
if st.sidebar.button("Refresh"): st.rerun()

# Auto Refresh
refresh_rate = st.sidebar.select_slider("Refresh Rate", options=[1, 5, 10, 30, 60], value=5)
# time.sleep(refresh_rate) ... actually streamlit handles this differently or we rely on loop?
# For now manual or simple rerun loop.
if st.sidebar.checkbox("Auto Refresh"):
    # time.sleep(refresh_rate) # Removed as fragments handle their own refresh
    st.rerun() # Keep for full page refresh if needed for non-fragment content

# --- Main Logic ---

@st.fragment(run_every=5)
def render_overview_content(mode):
     # Account Summary
    account = db.get_account()
    if account:
        # Metrics Calculation
        initial_balance = config['trading'].get('test_initial_balance', 10000.0) if mode in ['PAPER', 'TEST'] else 0.0
        equity = account.get('equity', 0)
        balance = account.get('balance', 0)
        
        total_pnl = equity - initial_balance if initial_balance > 0 else 0.0
        # For Live, Total PnL might be harder without initial ref. Use generic PnL if available.
        
        # History for Change %
        history = db.get_account_history(limit=1440) # Last 24h
        
        def get_pct_change(minutes):
            if not history: return 0.0
            cutoff = pd.Timestamp.now() - pd.Timedelta(minutes=minutes)
            # Find closest history point
            # timestamp is ms int
            cutoff_ts = cutoff.timestamp() * 1000
            
            # Simple search
            past_val = equity
            for h in history:
                if h['timestamp'] >= cutoff_ts:
                     past_val = h['equity']
                     break # Found earliest point in window
            
            if past_val == 0: return 0.0
            return ((equity - past_val) / past_val) * 100.0

        change_24h = get_pct_change(1440)
        change_1h = get_pct_change(60)

        # Row 1
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Available Cash", f"${balance:,.2f}")
        c2.metric("Total Equity", f"${equity:,.2f}", delta=f"{change_24h:.2f}% (24h)")
        c3.metric("Total PnL", f"${total_pnl:,.2f}", delta=f"{change_1h:.2f}% (1h)")
        c4.metric("Total Fees", f"${account.get('total_fees', 0):.2f}")
    else:
        st.warning("No Account Data yet.")

    # Active Positions
    st.subheader("Active Positions")
    positions = db.get_active_positions()
    if positions:
        df = pd.DataFrame(positions)
        st.dataframe(df, width='stretch')
    else:
        st.info("No active positions.")

    # Recent Signals
    st.subheader("Recent Signals")
    signals = db.get_recent_signals(limit=20)
    if signals:
        df = pd.DataFrame(signals)
        st.dataframe(df[['timestamp', 'strategy_name', 'symbol', 'side', 'price', 'status']], width='stretch')
    else:
        st.info("No recent signals.")

def render_overview():
    st.header("Global Overview")
    
    # Determine Mode
    mode = config['trading'].get('mode', 'LIVE')
    is_paper = mode in ['PAPER', 'TEST']
    
    # Tabs
    title_live = "Live Account" + (" 🟢" if not is_paper else "")
    title_paper = "Paper Trading" + (" 🟢" if is_paper else "")
    
    t_live, t_paper = st.tabs([title_live, title_paper])
    
    with t_live:
        if not is_paper:
            render_overview_content(mode)
        else:
            st.warning(f"Bot is in {mode} mode. Live view disabled.")
        
    with t_paper:
        if is_paper:
            render_overview_content(mode)
        else:
            st.warning("Bot is in LIVE mode. Paper view disabled.")

@st.fragment(run_every=5)
def render_strategy_details(strategy_name, symbol):
    # 1. Fetch Positions for this strategy
    st.subheader("Strategy Positions")
    all_pos = db.get_active_positions()
    strat_pos = [p for p in all_pos if p.get('strategy_name') == strategy_name]
    if strat_pos:
        st.dataframe(pd.DataFrame(strat_pos), width='stretch')
    else:
        st.info("No active positions for this strategy.")

    st.divider()

    # 2. Fetch Signals for this strategy/symbol
    st.subheader("Strategy Signals")
    signals = db.get_recent_signals(limit=50)
    # Filter by algo/strategy_name and symbol
    strat_sigs = [s for s in signals if (s.get('strategy_name') == strategy_name or s.get('algo') == strategy_name) and s.get('symbol') == symbol]
    
    if strat_sigs:
        df_sig = pd.DataFrame(strat_sigs)
        # Display key columns
        cols = ['timestamp', 'side', 'price', 'status']
        # robust select
        final_cols = [c for c in cols if c in df_sig.columns]
        st.dataframe(df_sig[final_cols], width='stretch')
    else:
        st.info(f"No recent signals for {symbol} in {strategy_name}.")

@st.fragment(run_every=5)
def render_strategy_chart(strategy_name, symbol):
    # Fetch Chart Data
    st.subheader("Live Chart")
    candles = db.get_recent_candles(symbol, limit=300)
    if candles:
        df = pd.DataFrame(candles)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # --- Indicator Calculation (On-the-fly) ---
        strat_conf = config['trading']['active_strategies'].get(strategy_name, {})
        params = strat_conf.get('params', {})
        short_p = params.get('short_period', 10)
        long_p = params.get('long_period', 100)
        
        # Calculate SMAs
        import ta
        df['SMA_Fast'] = ta.trend.sma_indicator(df['close'], window=short_p)
        df['SMA_Slow'] = ta.trend.sma_indicator(df['close'], window=long_p)
        
        # --- Plotting ---
        fig = go.Figure()
        
        # Candlestick
        fig.add_trace(go.Candlestick(
            x=df['timestamp'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            name='Price'
        ))
        
        # SMAs
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['SMA_Fast'], mode='lines', name=f'SMA {short_p}', line=dict(color='orange', width=1)))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['SMA_Slow'], mode='lines', name=f'SMA {long_p}', line=dict(color='blue', width=1)))
        
        # Signals Visualization (Backtest/Theoretical)
        try:
            df['prev_fast'] = df['SMA_Fast'].shift(1)
            df['prev_slow'] = df['SMA_Slow'].shift(1)
            buy_signals = df[(df['prev_fast'] <= df['prev_slow']) & (df['SMA_Fast'] > df['SMA_Slow'])]
            sell_signals = df[(df['prev_fast'] >= df['prev_slow']) & (df['SMA_Fast'] < df['SMA_Slow'])]
            
            fig.add_trace(go.Scatter(x=buy_signals['timestamp'], y=buy_signals['close'], mode='markers', name='Signal (Buy)', marker=dict(symbol='triangle-up', size=10, color='green')))
            fig.add_trace(go.Scatter(x=sell_signals['timestamp'], y=sell_signals['close'], mode='markers', name='Signal (Sell)', marker=dict(symbol='triangle-down', size=10, color='red')))
        except: pass

        # Executed Signals Overlay (Real)
        signals = db.get_recent_signals(limit=100)
        strat_signals = [s for s in signals if s['strategy_name'] == strategy_name and s['symbol'] == symbol]
        for s in strat_signals:
            ts = pd.to_datetime(s['timestamp'], unit='ms')
            color = 'green' if s['side'] == 'BUY' else 'red'
            fig.add_annotation(x=ts, y=s['price'], text="📢 EXECUTED", showarrow=True, arrowhead=1, arrowcolor=color, opacity=0.8)

        # Default Zoom and Dynamic Y-Axis Scaling
        range_x = None
        range_y = None
        
        if len(df) > 60:
            # 1. Define X-Window (Last 60 candles)
            min_x = df['timestamp'].iloc[-60]
            max_x = df['timestamp'].iloc[-1] + pd.Timedelta(minutes=5)
            range_x = [min_x, max_x]
            
            # 2. Calculate Y-Range based on visible data
            mask = (df['timestamp'] >= min_x)
            subset = df.loc[mask]
            
            if not subset.empty:
                # Get Min/Max of Price
                y_min = subset['low'].min()
                y_max = subset['high'].max()
                
                # Check Indicators if they are outliers (Optional, stick to price for clarity)
                # Apply Buffer (e.g., 10% of the range)
                diff = y_max - y_min
                if diff == 0: diff = y_max * 0.01 # Fallback for flat line
                
                padding = diff * 0.2 # 20% padding
                range_y = [y_min - padding, y_max + padding]

        fig.update_layout(
            height=600, 
            xaxis_rangeslider_visible=False, 
            title=f"{symbol} ({config['trading'].get('interval', '1m')})", 
            yaxis_title="Price",
            xaxis=dict(range=range_x) if range_x else None,
            yaxis=dict(range=range_y, autorange=False) if range_y else None
        )

        st.plotly_chart(fig)
    else:
        st.warning("Waiting for Market Data...")

def render_strategy_tab(strategy_name, symbol):
    st.header(f"Strategy: {strategy_name}")
    
    # Render Auto-Refreshing Content
    tab_chart, tab_details = st.tabs(["Live Chart", "Positions & Signals"])
    
    with tab_chart:
        render_strategy_chart(strategy_name, symbol)
        
    with tab_details:
        render_strategy_details(strategy_name, symbol)

# --- Sidebar Navigation ---
st.sidebar.header("Navigation")

# Heartbeat
import os
db.update_heartbeat('dashboard', 'online', {'pid': os.getpid()})

# Get Active Strategies from Config
strategies = [name for name, cfg in config['trading']['active_strategies'].items() if cfg['enabled']]
tabs = ["Overview"] + strategies + ["Admin"]
selected_tab = st.sidebar.radio("View", tabs)

# Symbol Selection (Global for Strategy Views)
symbol = None
if selected_tab not in ["Overview", "Admin"]:
    st.sidebar.divider()
    symbol = st.sidebar.selectbox("Select Symbol", config['trading']['symbols'], index=0)

# --- Main Content ---
if selected_tab == "Overview":
    render_overview()
elif selected_tab == "Admin":
    render_admin(db)
else:
    if symbol:
        render_strategy_tab(selected_tab, symbol)
    else:
        st.warning("Please select a symbol.")
