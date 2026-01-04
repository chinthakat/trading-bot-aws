
import streamlit as st
import json
import os
import sys

# Add app directory to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from persistence import DynamoManager
from page_utils import render_account_summary, render_positions_table, render_orders_table, render_signals_table

st.set_page_config(page_title="Test Account", page_icon="🧪", layout="wide")
st.title("🧪 Test Account (Paper Trading)")

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

# Connect DB
try:
    db = DynamoManager(config)
except Exception as e:
    st.error(f"DB Connection Failed: {e}")
    st.stop()

# --- Render Test Data ONLY ---
render_account_summary(db, "TEST", config)

tab1, tab2, tab3, tab4 = st.tabs(["📋 Test Positions", "📦 Test Orders", "📈 All Signals", "📜 Audit Logs"])

with tab1:
    render_positions_table(db, "TEST")

with tab2:
    render_orders_table(db, "TEST")

with tab3:
    # Note: Signals are currently shared/mixed. 
    # Ideally should filter if we added mode to signals, but for now showing all is safer than none.
    render_signals_table(db.signals_table)

with tab4:
    st.subheader("Action Audit Log")
    try:
        # Fetch logs
        resp = db.test_audit_table.scan()
        items = resp.get('Items', [])
        if items:
            import pandas as pd
            df = pd.DataFrame(items)
            # Format Timestamp
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Sort by time desc
            df = df.sort_values('timestamp', ascending=False)
            
            # Reorder columns
            cols = ['timestamp', 'action', 'cause', 'symbol', 'price', 'details', 'log_id']
            # Only keep cols that exist
            cols = [c for c in cols if c in df.columns]
            
            st.dataframe(df[cols], use_container_width=True)
        else:
            st.info("No audit logs found.")
    except Exception as e:
        st.error(f"Error loading audit logs: {e}")

if st.button("🔄 Refresh"):
    st.rerun()
