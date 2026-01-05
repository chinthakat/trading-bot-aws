import streamlit as st
import pandas as pd
import time
import os
from datetime import datetime

def render_admin(db):
    st.title("System Admin")
    
    # 1. System Status Panel
    st.subheader("System Status")
    status_list = db.get_system_status()
    
    if status_list:
        df_status = pd.DataFrame(status_list)
        
        # Calculate Age
        now_ms = int(datetime.now().timestamp() * 1000)
        df_status['age_seconds'] = (now_ms - df_status['last_heartbeat']) / 1000.0
        
        # Status Logic
        def get_state(row):
            if row['age_seconds'] < 30: return "🟢 Online"
            if row['age_seconds'] < 60: return "🟡 Lagging"
            return "🔴 Offline"
            
        df_status['state'] = df_status.apply(get_state, axis=1)
        
        # Display
        st.dataframe(
            df_status[['component_id', 'state', 'age_seconds', 'metadata']], 
            use_container_width=True,
            column_config={
                "age_seconds": st.column_config.NumberColumn("Last Heartbeat (s)", format="%.1fs")
            }
        )
    else:
        st.info("No system status reported yet.")

    st.divider()

    # 2. Log Viewer
    st.subheader("Log Viewer")
    
    log_options = {
        "Core Service": "logs/core.log", 
        "API Logs": "logs/api_logs.txt", 
        "Dashboard": "logs/dashboard.log"
    }
    
    # Add strategies dynamically if possible, or just standard ones
    # We can list files in logs/ dir?
    try:
        log_files = [f for f in os.listdir("logs") if f.endswith(".log")]
        for f in log_files:
            log_options[f] = f"logs/{f}"
    except: pass

    selected_log = st.selectbox("Select Log File", list(log_options.keys()))
    
    if selected_log:
        log_path = log_options[selected_log]
        if st.button("Refresh Logs"):
            pass # just triggers rerun
            
        try:
            if os.path.exists(log_path):
                # Read last 500 lines efficiently?
                # For small logs, readlines is fine.
                with open(log_path, "r") as f:
                    lines = f.readlines()
                    last_n = lines[-200:]
                    content = "".join(last_n)
                    st.code(content, language="text")
            else:
                st.error(f"Log file not found: {log_path}")
        except Exception as e:
            st.error(f"Error reading log: {e}")
