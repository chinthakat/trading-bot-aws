from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient
import time
import logging

logging.basicConfig(level=logging.INFO)

def on_message(_, msg):
    print(f"MSG: {msg}")

def on_error(_, error):
    print(f"ERR: {error}")
    
def on_close(_, *args):
    print("CLOSED")

print("Starting MW Test...")
client = SpotWebsocketStreamClient(
    stream_url="wss://stream.binance.com:9443",
    on_message=on_message,
    on_error=on_error,
    on_close=on_close,
    is_combined=True
)
client.subscribe(stream=["btcusdt@kline_1m"])

# Keep alive
for i in range(10):
    print(f"Sleeping {i}...")
    time.sleep(1)

client.stop()
