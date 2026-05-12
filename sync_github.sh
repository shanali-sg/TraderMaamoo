#!/bin/bash

# Push code to private repo
cd ~/app/rotation
git add journal/ data/ 2>/dev/null
git commit -m "Update $(date +%Y-%m-%d)" 2>/dev/null
git push origin main 2>&1 | tail -1

# Sync public-facing files to public repo
cp README.md equity_chart.png equity_history.json ~/trader-maamoo-public/
cd ~/trader-maamoo-public
git add .
git commit -m "Update $(date +%Y-%m-%d)" 2>/dev/null
git push origin main 2>&1 | tail -1
