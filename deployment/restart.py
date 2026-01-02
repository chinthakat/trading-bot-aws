import boto3
import json
import os
import subprocess
import sys
import time

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def get_instance_ip(region):
    ec2 = boto3.client('ec2', region_name=region)
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

def get_key_file():
    # Prioritize AU key
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    au_key = os.path.join(project_root, "TradingBotKey_AU.pem")
    if os.path.exists(au_key):
        return au_key
        
    for file in os.listdir(project_root):
        if file.endswith('.pem'):
            return os.path.join(project_root, file)
    return None

def main():
    config = load_config()
    region = config['aws']['region']
    
    print(f"--- Restarting Bot in {region} ---")
    
    # Get IP
    ip = get_instance_ip(region)
    if not ip:
        print("Error: No running TradingBot instance found.")
        sys.exit(1)
    print(f"Target IP: {ip}")
    
    # Get Key
    key_file = get_key_file()
    if not key_file:
        print("Error: No .pem key file found in project root.")
        sys.exit(1)
    print(f"Using Key: {os.path.basename(key_file)}")
    
    # Restart Command
    # 1. Kill existing bot
    # 2. Start new one with nohup (background)
    # Note: We cannot chain '&&' after '&'. So we just execute the background command last.
    
    # We construct a shell command string carefully.
    remote_cmd = "cd trading-bot && (pkill -f bot.py || true) && nohup python3 app/bot.py > bot.log 2>&1 &"
    
    ssh_cmd = [
        "ssh",
        "-i", key_file,
        "-o", "StrictHostKeyChecking=no",
        f"ec2-user@{ip}",
        remote_cmd
    ]
    
    try:
        subprocess.run(ssh_cmd, check=True)
        print("\n✅ Bot Restarted Successfully!")
        print(f"Dashboard: http://{ip}:8501")
        print("\nTo follow logs run:")
        print(f"ssh -i {os.path.basename(key_file)} ec2-user@{ip} 'tail -f trading-bot/bot.log'")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Failed to restart bot: {e}")

if __name__ == "__main__":
    main()
