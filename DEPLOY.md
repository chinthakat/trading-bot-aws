# Deploying to AWS EC2

## Prerequisites
1. **AWS Account** with permissions to create EC2 instances and DynamoDB tables.
2. **Binance Account** with API Key and Secret.
3. **AWS CLI / Credentials** configured locally (`aws configure`).
4. **EC2 Key Pair**: Ensure you have created a Key Pair in your AWS Console (region `us-east-1` by default) and downloaded the `.pem` file.

## Method 1: Automated Deployment (Recommended)

1. **Run the Provisioning Script**:
    ```bash
    python deployment/provision.py
    ```
    This script will:
    - Create necessary DynamoDB tables.
    - Create a Security Group allowing SSH and Dashboard access.
    - Launch an EC2 instance.
    - **Output the Public IP** and next steps.

## Quick Start (Australia Deployment)

**Region**: `ap-southeast-2` (Sydney)
**Instance IP**: `3.27.93.22`
**Key File**: `TradingBotKey_AU.pem`

### Automated Code Deployment

1. **Run Deploy Script**:
    ```bash
    python deployment/deploy.py
    ```

### Manual Steps (Fallback)

1. **Upload Code**:
    ```bash
    scp -i "TradingBotKey_AU.pem" -r app/ config.json requirements.txt ec2-user@3.106.128.59:/home/ec2-user/trading-bot/
    ```

2. **Connect & Install**:
    ```bash
    ssh -i "TradingBotKey_AU.pem" ec2-user@3.106.128.59
    ```
    *Inside the SSH session:*
    ```bash
    cd /home/ec2-user/trading-bot
    pip3 install -r requirements.txt
    ```

3. **Start Dashboard**:
    ```bash
    cd /home/ec2-user/trading-bot
    sudo systemctl daemon-reload
    sudo systemctl start trading-dashboard
    sudo systemctl enable trading-dashboard
    ```

4. **Run Bot**:
    [http://3.106.128.59:8501](http://3.106.128.59:8501)
    
    To run the core bot logic:
    ```bash
    python3 app/bot.py
    ```

## Manual Provisioning

1. **Launch EC2 Instance**:
    - Go to EC2 Console -> Launch Instance.
    - OS: **Amazon Linux 2023** (or Ubuntu).
    - Instance Type: **t3.micro** (Free Tier eligible).
    - Key Pair: Create or select an existing one (for SSH access).
    - **Network Settings**:
        - Allow SSH traffic from your IP.
        - **IMPORTANT**: Allow Custom TCP Rule for Port **8501** (Source: Anywhere 0.0.0.0/0) to access the Dashboard.
    - **Advanced Details -> User Data**: Copy the contents of `deployment/user_data.sh`.

2. **DynamoDB Tables**:
    - Manually create the following tables in DynamoDB (us-east-1):
        - `TradingBot_Trades` (Partition Key: `trade_id`)
        - `TradingBot_Stats` (Partition Key: `stat_type`, Sort Key: `algo`)
        - `TradingBot_Prices` (Partition Key: `symbol`)
        - `TradingBot_Signals` (Partition Key: `signal_id`)

## Step 2: Upload Code

1. **Connect via SSH**:
    ```bash
    ssh -i "your-key.pem" ec2-user@<your-ec2-public-ip>
    ```

2. **Copy Files**:
    - You can use SCP or Git. 
    - **SCP Example** (run from your local machine):
        ```bash
        scp -i "your-key.pem" -r app/ config.json requirements.txt ec2-user@<your-ec2-public-ip>:/home/ec2-user/trading-bot/
        ```

## Step 3: Install & Start

1. **Install Dependencies** (on EC2):
    ```bash
    cd /home/ec2-user/trading-bot
    pip3 install -r requirements.txt
    ```

2. **Configure Secrets**:
    - Create the `.env` file or export variables:
        ```bash
        export BINANCE_API_KEY="your_key"
        export BINANCE_SECRET="your_secret"
        ```

3. **Start Services**:
    ```bash
    sudo systemctl start trading-dashboard
    sudo systemctl enable trading-dashboard
    # Start bot in a screen or as service
    # python3 app/bot.py
    ```

## Step 4: Access Dashboard

Open your browser and navigate to:
`http://<YOUR-EC2-PUBLIC-IP>:8501`
