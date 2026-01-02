import streamlit as st
import time
import os

st.set_page_config(page_title="API Logs", page_icon="📜", layout="wide")

st.title("📜 Bot API Logs")

# Path to log file (It's in the parent directory relative to this page file)
# app/pages/api_logs.py -> app/api_logs.txt? No, bot runs in project root usually.
# If bot runs as `python3 app/bot.py`, it writes to `api_logs.txt` in CWD (project root).
# Streamlit runs from where? Usually project root if run as `streamlit run app/dashboard.py`.
# Let's try root first.

LOG_FILE = "api_logs.txt"

if st.button("Refresh Logs"):
    st.rerun()

try:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            # Show last 200 lines, newest on top?
            lines = lines[-200:]
            lines.reverse()
            
            st.text_area("Log Output (Last 200 lines)", "".join(lines), height=600)
    else:
        st.warning(f"Log file '{LOG_FILE}' not found. Bot might not be running or logging yet.")

except Exception as e:
    st.error(f"Error reading log: {e}")

# Meta info
st.info("Logs are read from 'api_logs.txt' on the server.")
