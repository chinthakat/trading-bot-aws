
# Deploy Script for Trading Bot
# Usage: .\deploy_all.ps1

$Key = "TradingBotKey_AU.pem"
$User = "ec2-user@13.236.122.229"
$RemoteDir = "~/trading-bot"

Write-Host "--- Deploying to AWS ($User) ---" -ForegroundColor Cyan

# 1. App Directory (Recursive)
Write-Host "[1/4] Syncing App Code..."
scp -i $Key -r app "${User}:${RemoteDir}/"
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to copy app/"; exit 1 }

# 2. Config
Write-Host "[2/4] Syncing Config..."
scp -i $Key config.json "${User}:${RemoteDir}/config.json"

# 3. Startup Script
Write-Host "[3/4] Syncing Scripts..."
scp -i $Key start_bot.sh "${User}:${RemoteDir}/start_bot.sh"
scp -i $Key requirements.txt "${User}:${RemoteDir}/requirements.txt"

# 4. Permissions
Write-Host "[4/4] Setting Permissions..."
ssh -i $Key $User "chmod +x ${RemoteDir}/start_bot.sh"

Write-Host "Deployment Complete." -ForegroundColor Green
