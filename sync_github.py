#!/bin/bash
cd /home/ec2-user/app/rotation
git add journal/ data/ equity_history.json equity_chart.png 2>/dev/null
git commit -m "Update $(date +%Y-%m-%d)" 2>/dev/null
git push
