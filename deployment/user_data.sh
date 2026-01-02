#!/bin/bash
# Update and install dependencies
yum update -y
yum install -y git python3 python3-pip

# Install setup tools to avoid potential issues
pip3 install --upgrade pip setuptools wheel

# Clone the repository (Assuming public or using a token, for this generic script we assume the code is manually copied or pulled from a source accessible)
# Ideally, we pull from S3 or Git. For this setup, we will create the directories and expect code sync.
mkdir -p /home/ec2-user/trading-bot
chown -R ec2-user:ec2-user /home/ec2-user/trading-bot

# Navigate to dir
cd /home/ec2-user/trading-bot

# Create a systemd service for the Dashboard
cat <<EOF > /etc/systemd/system/trading-dashboard.service
[Unit]
Description=Streamlit Dashboard
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/trading-bot
ExecStart=/usr/local/bin/streamlit run app/dashboard.py --server.port 8501 --server.headless true
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Create a systemd service for the Bot
cat <<EOF > /etc/systemd/system/trading-bot.service
[Unit]
Description=Trading Bot Core
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/trading-bot
ExecStart=/usr/bin/python3 app/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Reload daemon
systemctl daemon-reload

# Note: Services are not started yet because code is not there.
# User needs to upload code then run:
# pip3 install -r requirements.txt
# systemctl start trading-dashboard
# systemctl start trading-bot
