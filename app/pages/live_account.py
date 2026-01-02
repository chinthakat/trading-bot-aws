
import streamlit as st
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from persistence import DynamoManager
from page_utils import render_account_summary, render_positions_table, render_orders_table, render_signals_table

st.set_page_config(page_title="Live Account", page_icon="💰", layout="wide")
st.title("💰 Live Account")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

try:
    db = DynamoManager(config)
except Exception as e:
    st.error(f"DB Connection Failed: {e}")
    st.stop()

# Alert if not in Live Mode
if config['trading'].get('mode') != 'LIVE':
    st.warning("⚠️ Bot is currently in **TEST** mode. Real trading is PAUSED.")

# --- Render Live Data ONLY ---
render_account_summary(db, "LIVE", config)

tab1, tab2, tab3 = st.tabs(["📋 Real Positions", "📦 Real Orders", "📈 All Signals"])

with tab1:
    render_positions_table(db, "LIVE")

with tab2:
    render_orders_table(db, "LIVE")

with tab3:
    render_signals_table(db.signals_table)

if st.button("🔄 Refresh"):
    st.rerun()
