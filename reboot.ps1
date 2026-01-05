
# Reboot Script for Trading Bot Cluster
# Usage: .\reboot.ps1

$Key = "TradingBotKey_AU.pem"
$User = "ec2-user@13.236.122.229"
$RemoteDir = "~/trading-bot"

Write-Host "--- Trading Bot Cluster Reboot Sequence ---" -ForegroundColor Cyan

# 1. Sync Logic
Write-Host "[1/5] Syncing Configuration and App..."
scp -i $Key config.json "${User}:${RemoteDir}/config.json"
scp -i $Key start_bot.sh "${User}:${RemoteDir}/start_bot.sh"
scp -i $Key -r app "${User}:${RemoteDir}/"
if ($LASTEXITCODE -ne 0) { Write-Error "SCP Failed"; exit 1 }

# 2. Kill Logic
Write-Host "[2/5] Force Killing All Python Processes..."
ssh -i $Key $User "pkill -9 -f python3; pkill -9 -f streamlit"
Write-Host "Kill commands sent."

# 3. Wait Logic
Write-Host "[3/5] Waiting 30 seconds for socket cleanup..."
Start-Sleep -Seconds 30

# 4. Verify Logic
Write-Host "[4/5] Verifying Clean State..."
$Processes = ssh -i $Key $User "pgrep -f python3"
if ($Processes) {
    Write-Warning "Warning: Python processes still running: $Processes"
    # Optional: Retry kill via start_bot.sh later
}
else {
    Write-Host "State is Clean." -ForegroundColor Green
}

# 5. Start Logic
Write-Host "[5/5] Starting Bot Cluster..."
ssh -i $Key $User "cd ${RemoteDir} && chmod +x start_bot.sh && ./start_bot.sh"

Write-Host "--- Reboot Complete ---" -ForegroundColor Cyan
