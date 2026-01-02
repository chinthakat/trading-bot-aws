import boto3
import os
import subprocess
import sys
import time

import json

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

config = load_config()
REGION = config['aws']['region']

def get_instance_ip():
    ec2 = boto3.client('ec2', region_name=REGION)
    response = ec2.describe_instances(
        Filters=[
            {'Name': 'tag:Name', 'Values': ['TradingBot']},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )
    reservations = response.get('Reservations', [])
    if not reservations:
        return None
    return reservations[0]['Instances'][0].get('PublicIpAddress')

def fix_key_permissions(key_path):
    if os.name == 'nt': # Windows
        print("Fixing key permissions for Windows (using icacls)...")
        try:
            username = os.getlogin()
            # 1. Reset permissions
            subprocess.run(f'icacls "{key_path}" /reset', shell=True, check=True)
            # 2. Grant Read to current user
            subprocess.run(f'icacls "{key_path}" /grant:r "{username}":(R)', shell=True, check=True)
            # 3. Remove inheritance
            subprocess.run(f'icacls "{key_path}" /inheritance:r', shell=True, check=True)
        except Exception as e:
            print(f"Icacls failed: {e}")
    else:
        os.chmod(key_path, 0o600)

def deploy():
    print("--- Starting Deployment ---")
    
    # Paths
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_path = os.path.join(base_dir, 'TradingBotKey_AU.pem')
    
    if not os.path.exists(key_path):
        print(f"Error: Key file {key_path} not found. Did you run provision.py?")
        return

    # 1. Get IP
    ip = get_instance_ip()
    if not ip:
        print("Error: Could not find running TradingBot instance.")
        return
    print(f"Target IP: {ip}")
    
    # 2. Fix Key Permissions
    try:
        fix_key_permissions(key_path)
    except Exception as e:
        print(f"Warning: Could not fix permissions: {e}")

    # 3. SCP Files
    print("Uploading files...")
    # Using strict host key checking=no to avoid prompt on automated runs (security trade-off ok for this scope)
    files_to_upload = [
        os.path.join(base_dir, "app"), 
        os.path.join(base_dir, "config.json"), 
        os.path.join(base_dir, "requirements.txt")
    ]
    
    # Check for .env
    env_path = os.path.join(base_dir, ".env")
    if os.path.exists(env_path):
        files_to_upload.append(env_path)
    
    scp_cmd = [
        "scp", "-i", key_path, 
        "-o", "StrictHostKeyChecking=no",
        "-r"
    ] + files_to_upload + [f"ec2-user@{ip}:/home/ec2-user/trading-bot/"]
    
    try:
        subprocess.run(scp_cmd, check=True)
        print("Upload complete.")
    except subprocess.CalledProcessError as e:
        print(f"SCP failed: {e}")
        return

    # 4. SSH Commands (Install & Start)
    print("Configuring server...")
    remote_cmds = [
        "cd /home/ec2-user/trading-bot",
        "pip3 install -r requirements.txt",
        # Fix Streamlit path if needed (sed handles if it's already correct or not, safer to just force write)
        "sudo sed -i 's|/usr/local/bin/streamlit|/home/ec2-user/.local/bin/streamlit|g' /etc/systemd/system/trading-dashboard.service",
        "sudo sed -i 's|--server.Headless|--server.headless|g' /etc/systemd/system/trading-dashboard.service",
        "sudo systemctl daemon-reload", 
        "sudo systemctl restart trading-dashboard",
        "sudo systemctl enable trading-dashboard",
    ]
    
    ssh_cmd = [
        "ssh", "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        f"ec2-user@{ip}",
        " && ".join(remote_cmds)
    ]

    try:
        subprocess.run(ssh_cmd, check=True)
        print("Configuration complete.")
    except subprocess.CalledProcessError as e:
        print(f"SSH failed: {e}")
        return

    print("\n---------------------------------------------------")
    print(f"Deployment SUCCESS!")
    print(f"Dashboard: http://{ip}:8501")
    print("To start the trading bot logic:")
    print(f"ssh -i TradingBotKey.pem ec2-user@{ip}")
    print("cd trading-bot")
    print("python3 app/bot.py")
    print("---------------------------------------------------")

if __name__ == "__main__":
    deploy()
