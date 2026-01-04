Write-Host "Deploying App Code..."
scp -i TradingBotKey_AU.pem -r app ec2-user@13.236.122.229:~/trading-bot/
scp -i TradingBotKey_AU.pem config.json ec2-user@13.236.122.229:~/trading-bot/
scp -i TradingBotKey_AU.pem requirements.txt ec2-user@13.236.122.229:~/trading-bot/
Write-Host "Deployment Complete."
