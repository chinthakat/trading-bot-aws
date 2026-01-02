import streamlit as st
import json

# Load config to check mode
with open('config.json', 'r') as f:
    config = json.load(f)

mode = config['trading'].get('mode', 'TEST')

st.title("📄 Test Account (Paper Trading)")

if mode != "TEST":
    st.warning("⚠️ Bot is in LIVE mode. This page shows test account data only.")
    st.info("Switch to TEST mode in config.json to use paper trading.")
else:
    st.success("✅ Bot is in TEST mode - Paper trading active")

st.divider()

# This is a simple placeholder - real implementation would query simulator state
st.subheader("Account Summary")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Initial Balance", "$10,000.00")

with col2:
    st.metric("Current Balance", "$10,000.00", help="Cash balance")

with col3:
    st.metric("Total Equity", "$10,000.00", help="Balance + unrealized P&L")

st.divider()

st.subheader("Simulated Positions")
st.info("No open positions")

st.divider()

st.subheader("Trade History")
st.info("No trades yet - Waiting for signals...")

st.divider()

st.markdown("""
### How Paper Trading Works

- **Virtual $10K Balance**: Starts at $10,000 (configurable)
- **Real Price Data**: Uses live market prices from Binance
- **Simulated Fills**: Orders fill instantly when price crosses limit
- **Safe Testing**: Zero financial risk
- **Separate Database**: All data saved to `test_*` tables

### To View Live Data

The bot is currently tracking paper trades in real-time. As signals are generated and orders fill:
1. This dashboard will update with positions
2. P&L will be calculated based on real price movements
3. All trades will be logged to test database tables

**Note**: Full dashboard integration with live simulator data is in progress.
For now, check `bot.log` for paper trading activity:
```
[PAPER] Placed buy limit order: BTC/USDT @ $89500.00 qty=0.00001
[PAPER] ✅ BUY filled: 0.00001 BTC/USDT @ $89500.00 | Balance: $9999.10
```
""")

# Refresh button
if st.button("🔄 Refresh"):
    st.rerun()
