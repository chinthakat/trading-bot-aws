# Deploying to AWS EC2

The bot and the dashboard run as two systemd services on a single EC2 instance, with DynamoDB
for storage. Everything below assumes you run the commands from the repository root.

The region and the table names come from `config.json` (`aws.region`, currently
`ap-southeast-2`). Change them there rather than in the scripts.

## Prerequisites

1. **AWS account** with permission to create EC2 instances, IAM roles and DynamoDB tables.
2. **AWS credentials** configured locally (`aws configure`).
3. **Binance account** with an API key and secret, placed in a local `.env` file — see
   `.env.example`.
4. **Python dependencies** installed locally: `pip install -r requirements.txt`.

## Method 1: automated (recommended)

### 1. Provision

```bash
python deployment/provision.py
```

This creates the `trades`, `stats`, `prices` and `signals` DynamoDB tables, creates a
`TradingBotSG` security group opening ports 22 and 8501, finds the latest Amazon Linux 2023
AMI, and launches a `t3.micro` tagged `Name=TradingBot`. It prints the instance's public IP
when it is running.

If the key pair `TradingBotKey_AU` does not already exist, the script creates it and writes the
private key to `TradingBotKey_AU.pem` in the repository root. That file is gitignored — back it
up somewhere safe, because AWS will not give it to you again.

> The security group allows SSH and the dashboard from `0.0.0.0/0`. The dashboard has no login,
> and in `LIVE` mode its manual buy/sell buttons build their own ccxt client from the `.env`
> credentials and send orders straight to Binance. Anyone who finds the public IP has
> authenticated access to the exchange account. Narrow the CIDRs to your own IP before leaving
> anything running.

### 2. Create the position and paper-trading tables

`provision.py` does not create these:

```bash
python deployment/create_position_tables.py   # TradingBot_Positions, TradingBot_Orders
python deployment/create_test_tables.py       # TradingBot_Test_Positions, _Test_Orders, _Test_Account
```

`TradingBot_Test_Account` is created for completeness only — `DynamoManager` opens a handle to
it and no code ever reads or writes it. Nothing breaks if you skip it.

### 3. Attach the instance role

```bash
python deployment/attach_iam.py
```

Creates the `TradingBotRole` role and `TradingBotProfile` instance profile and attaches it, so
the instance can reach DynamoDB without static AWS keys on the box.

### 4. Deploy the code

```bash
python deployment/deploy.py
```

Finds the running `TradingBot` instance by tag, fixes the `.pem` permissions (`icacls` on
Windows, `chmod 600` elsewhere), copies `app/`, `config.json`, `requirements.txt` and `.env`
over SCP to `/home/ec2-user/trading-bot/`, installs the dependencies, and restarts and enables
the `trading-dashboard` service.

### 5. Start the bot

`deploy.py` starts the dashboard but not the bot:

```bash
python deployment/restart.py
```

This kills any running `bot.py` and relaunches it under `nohup`, logging to
`trading-bot/bot.log`.

### 6. Open the dashboard

`http://<instance-public-ip>:8501`

## Method 2: manual

1. **Launch the instance**
   - Amazon Linux 2023, `t3.micro`, a key pair you control.
   - Inbound: SSH (22) from your IP, custom TCP 8501 from your IP.
   - Advanced details → User data: paste the contents of `deployment/user_data.sh`. It installs
     Python, creates `/home/ec2-user/trading-bot`, and writes the `trading-dashboard` and
     `trading-bot` systemd units. It deliberately does not start them, because no code is on the
     box yet.

2. **Create the DynamoDB tables** in the region from `config.json`:

   | Table | Partition key | Sort key |
   |---|---|---|
   | `TradingBot_Trades` | `trade_id` (S) | — |
   | `TradingBot_Stats` | `stat_type` (S) | `algo` (S) |
   | `TradingBot_Prices` | `symbol` (S) | `timestamp` (N) |
   | `TradingBot_Signals` | `signal_id` (S) | — |
   | `TradingBot_Positions` | `position_id` (S) | — |
   | `TradingBot_Orders` | `order_id` (S) | — |
   | `TradingBot_Test_Positions` | `position_id` (S) | — |
   | `TradingBot_Test_Orders` | `order_id` (S) | — |
   | `TradingBot_Test_Account` | `account_id` (S) | `timestamp` (N) |

   `TradingBot_Test_Account` is unused by the application code; create it only if you want the
   table set to match `config.json` exactly.

3. **Upload the code**

   ```bash
   scp -i your-key.pem -r app/ config.json requirements.txt .env \
       ec2-user@<instance-public-ip>:/home/ec2-user/trading-bot/
   ```

4. **Install and configure**

   ```bash
   ssh -i your-key.pem ec2-user@<instance-public-ip>
   cd /home/ec2-user/trading-bot
   pip3 install -r requirements.txt
   ```

   If you did not upload a `.env`, export the keys instead:

   ```bash
   export BINANCE_API_KEY="your_key"
   export BINANCE_SECRET="your_secret"
   ```

5. **Start the services**

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now trading-dashboard
   sudo systemctl enable --now trading-bot
   ```

   `user_data.sh` writes the dashboard unit's `ExecStart` as `/usr/local/bin/streamlit`. A
   `pip3 install --user` puts it at `/home/ec2-user/.local/bin/streamlit` instead;
   `deploy.py` rewrites the unit with `sed` to handle this. If you are doing it by hand, check
   with `which streamlit` and edit `/etc/systemd/system/trading-dashboard.service` to match.

## Operations

```bash
# Tail the bot log
ssh -i your-key.pem ec2-user@<ip> 'tail -f trading-bot/bot.log'

# Inspect what is actually in the prices table
python deployment/inspect_db.py

# Empty the prices table
python deployment/clear_prices.py

# Drop and recreate the prices table with the current schema
python deployment/recreate_table.py
```

## Teardown

```bash
python deployment/teardown.py
```

Terminates the `TradingBot` instances, deletes the `TradingBotSG` security group, and deletes
every DynamoDB table listed in `config.json`. This destroys your trade history — export anything
you want to keep first.

Two things it does not clean up:

- It deletes a key pair named `TradingBotKey`, but `provision.py` creates `TradingBotKey_AU`.
  Delete the leftover key pair and the local `.pem` by hand.
- The IAM role and instance profile created by `attach_iam.py` are left in place. `attach_iam.py`
  attaches the AWS-managed `AmazonDynamoDBFullAccess` policy, which is far broader than this bot
  needs; scope it to the specific tables if you keep the role around.
