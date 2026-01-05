
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
    time.sleep(refresh_rate)
    st.rerun()

# --- Main Logic ---

def render_overview():
    st.header("Global Overview")
    
    # Determine Mode
    mode = config['trading'].get('mode', 'LIVE')
    is_paper = mode in ['PAPER', 'TEST']
    
    # Tabs
    # Highlight Active Mode
    title_live = "Live Account" + (" 🟢" if not is_paper else "")
    title_paper = "Paper Trading" + (" 🟢" if is_paper else "")
    
    t_live, t_paper = st.tabs([title_live, title_paper])
    
    # Render Helper
    def show_stats(active_tab):
        if not active_tab:
            st.warning(f"Bot is currently in {mode} mode. Switch config to activate this view.")
            return

        # Account Summary
        account = db.get_account()
        if account:
            c1, c2, c3 = st.columns(3)
            c1.metric("Balance", f"${account.get('balance',0):.2f}")
            c2.metric("Equity", f"${account.get('equity',0):.2f}")
            c3.metric("PnL", f"${account.get('pnl',0):.2f}")
        else:
            st.warning("No Account Data yet.")

        # Active Positions
        st.subheader("Active Positions")
        positions = db.get_active_positions()
        if positions:
            df = pd.DataFrame(positions)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No active positions.")

        # Recent Signals
        st.subheader("Recent Signals")
        signals = db.get_recent_signals(limit=20)
        if signals:
            df = pd.DataFrame(signals)
            st.dataframe(df[['timestamp', 'strategy_name', 'symbol', 'side', 'price', 'status']], use_container_width=True)
        else:
            st.info("No recent signals.")

    with t_live:
        show_stats(not is_paper)
        
    with t_paper:
        show_stats(is_paper)

def render_strategy_tab(strategy_name):
    st.header(f"Strategy: {strategy_name}")
    
    # Sub-Tabs
    tab_chart, tab_pos = st.tabs(["Live Chart", "Strategy Positions"])
    
    with tab_pos:
        st.subheader("Strategy Positions")
        all_pos = db.get_active_positions()
        strat_pos = [p for p in all_pos if p.get('strategy_name') == strategy_name]
        if strat_pos:
            st.dataframe(pd.DataFrame(strat_pos))
        else:
            st.info("No active positions for this strategy.")

    with tab_chart:
        st.subheader("Live Chart")
        symbol = st.selectbox("Select Symbol", config['trading']['symbols'], key=f"sel_{strategy_name}")
        
        candles = db.get_recent_candles(symbol, limit=300)
        if candles:
            df = pd.DataFrame(candles)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # --- Indicator Calculation (On-the-fly) ---
            # Try to match Strategy Params
            strat_conf = config['trading']['active_strategies'].get(strategy_name, {})
            params = strat_conf.get('params', {})
            
            # MA Crossover Specifics
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
            
            # --- Visual Indicators (Backtest View) ---
            # Detect Crossovers in the loaded DF to show "Theoretical" signals
            # This helps user see what the strategy WOULD have done in history
            try:
                # Vectorized crossover detection
                df['prev_fast'] = df['SMA_Fast'].shift(1)
                df['prev_slow'] = df['SMA_Slow'].shift(1)
                
                # Buy: Fast crosses above Slow
                buy_signals = df[(df['prev_fast'] <= df['prev_slow']) & (df['SMA_Fast'] > df['SMA_Slow'])]
                
                # Sell: Fast crosses below Slow
                sell_signals = df[(df['prev_fast'] >= df['prev_slow']) & (df['SMA_Fast'] < df['SMA_Slow'])]
                
                # Plot Buys
                fig.add_trace(go.Scatter(
                    x=buy_signals['timestamp'], y=buy_signals['close'],
                    mode='markers', name='Signal (Buy)',
                    marker=dict(symbol='triangle-up', size=10, color='green')
                ))
                
                # Plot Sells
                fig.add_trace(go.Scatter(
                    x=sell_signals['timestamp'], y=sell_signals['close'],
                    mode='markers', name='Signal (Sell)',
                    marker=dict(symbol='triangle-down', size=10, color='red')
                ))
            except Exception as e:
                pass # Squelch calc errors if data insufficient

            # Executed Signals Overlay (Real)
            signals = db.get_recent_signals(limit=100)
            strat_signals = [s for s in signals if s['strategy_name'] == strategy_name and s['symbol'] == symbol]
            
            for s in strat_signals:
                ts = pd.to_datetime(s['timestamp'], unit='ms')
                color = 'green' if s['side'] == 'BUY' else 'red'
                # Marker position (slightly off price)
                price = s['price']
                fig.add_annotation(
                    x=ts, y=price,
                    text="📢 EXECUTED",
                    showarrow=True,
                    arrowhead=1,
                    arrowcolor=color,
                    # bgcolor="black",
                    opacity=0.8
                )

            # Default Zoom to last 60 candles (1 hour for 1m)
            if len(df) > 60:
                min_x = df['timestamp'].iloc[-60]
                max_x = df['timestamp'].iloc[-1] + pd.Timedelta(minutes=5) # Small buffer forward
                range_x = [min_x, max_x]
            else:
                range_x = None

            fig.update_layout(
                height=600,
                xaxis_rangeslider_visible=False, # Better zoom behavior
                title=f"{symbol} ({config['trading'].get('interval', '1m')})",
                yaxis_title="Price",
                xaxis=dict(range=range_x) if range_x else None
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Waiting for Market Data...")

# --- Tabs ---
# Get Active Strategies from Config
strategies = [name for name, cfg in config['trading']['active_strategies'].items() if cfg['enabled']]
tabs = ["Overview"] + strategies
selected_tab = st.radio("View", tabs, horizontal=True)

if selected_tab == "Overview":
    render_overview()
else:
    render_strategy_tab(selected_tab)
