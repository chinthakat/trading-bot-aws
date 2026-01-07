# scripts/

One-off operational and debugging scripts written while building the bot. They are **not** part
of the application and are not unit tests — they talk to the real DynamoDB tables named in
`config.json`.

Run them from the repository root, because they load `config.json` and resolve `app/` relative to
the current working directory:

```bash
python scripts/<name>.py
```

| Script | What it does |
|---|---|
| `cleanup_db.py` | Deletes one position from the test positions table. The position id is **hardcoded** in the file — edit it before running. |
| `cleanup_orders.py` | Scans the test orders table and marks every `pending` order `canceled`. |
| `manual_test_trigger.py` | Writes a synthetic pending BUY order straight into the test orders table, waits 15s, then checks whether the running bot turned it into a position. Used to test the dashboard-to-bot handoff. The limit price is hardcoded and assumes a BTC price near it. |
| `test_ws.py` | Minimal Binance kline WebSocket connection check — subscribes to `btcusdt@kline_1m`, prints ten seconds of messages, exits. Despite the name it is not a pytest test. |
| `verify_full_lifecycle.py` | Walks an order through its whole life in `TEST` mode (place, fill, P&L update, close) against the live tables, printing what happened at each step. Written to investigate `DynamoManager.update_order()` always writing to the live orders table. |

`cleanup_db.py`, `cleanup_orders.py` and `manual_test_trigger.py` mutate real DynamoDB rows.
Read them before running them.
