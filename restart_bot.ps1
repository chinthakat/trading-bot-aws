Write-Host "Restarting Remote Bot..."
ssh -i TradingBotKey_AU.pem ec2-user@13.236.122.229 "cd /home/ec2-user/trading-bot && pkill -f app/bot.py; sleep 3; rm -f ~/bot_debug.log && nohup python3 -u app/bot.py > ~/bot_debug.log 2>&1 < /dev/null &"
Write-Host "Bot Restarted. Tailing logs (Ctrl+C to exit)..."
Start-Sleep -Seconds 2
ssh -i TradingBotKey_AU.pem ec2-user@13.236.122.229 "tail -f ~/bot_debug.log"
