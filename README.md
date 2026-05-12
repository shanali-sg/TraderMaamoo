<<<<<<< HEAD
Automated swing trading bot for small accounts. Runs on Alpaca free tier with IEX data.

## Strategy

Enter at the close of a quality red candle that touches SMA20 during a Stage 2 uptrend.
Exit at +5R target or after 7 trading days. No stop-loss.

### Entry Conditions
- SMA20 > SMA200 (Stage 2 uptrend)
- SMA20 rising (3-day slope > 0.1%)
- Yesterday was a red candle near SMA20 (within 3%)
- Red candle body ≥ 0.5% of price
- Close in lower half of candle range
- Volume ≥ 80% of 20-day average
- Volume > 200K daily average
- Price > $5

### Exit Rules
- Take-profit limit at +5R from entry
- Time exit at market close after 7 trading days

### Risk Management
- 4 bullets, each risking 2% of account equity
- Fractional shares for exact position sizing
- No stop-loss orders

## Architecture
finviz_screener.py → symbols.txt (Stage 2 universe, earnings excluded)
▼
live.py → Screener → Scoring → Execution → Journal
▼
auditor.py → whitelist.json + audit_report.json (weekly review)

## Files

| File                   | Purpose                                        | Run                  |
|------------------------|------------------------------------------------|----------------------|
| `finviz_screener.py`   | Build daily symbol universe                    | 9:20 AM ET, weekdays |
| `live.py`              | Screen, score, execute trades                  | 9:35 AM ET, weekdays |
| `auditor.py`           | Performance metrics, whitelist, sector weights | Saturday 10:00 AM ET |
| `paper.py`             | Backtest strategy on historical data           | On demand            |
| `diagnose_signal.py`   | Debug individual symbol setups                 | On demand            |
| `protect_positions.py` | Emergency protection for naked positions       | On demand            |

## Key Parameters

| Parameter      | Value                                                     |
|----------------|-----------------------------------------------------------|
| Account        | $458 starting capital                                     |
| Bullets        | 4                                                         |
| Risk per trade | 2% of bullet                                              |
| Target         | +5R                                                       |
| Max hold       | 7 trading days                                            |
| Universe       | ~134 symbols (Stage 2, liquid, no earnings within 5 days) |
| Data           | Alpaca IEX free tier                                      |

## Journal & Audit

Daily trade journals saved to `journal/YYYY-MM-DD.json`.
Weekly audit updates `data/whitelist.json` (proven symbols) and `data/audit_report.json` (performance history).
Whitelist symbols and sector weights feed back into live scoring.

## Setup

```bash
pip install alpaca-py pandas numpy yfinance finvizfinance

export APCA_API_KEY_ID="your_key"
export APCA_API_SECRET_KEY="your_secret"

## Setup

20 9 * * 1-5 cd /path/to/bot && .venv/bin/python finviz_screener.py >> logs/cron_finviz.log 2>&1
35 9 * * 1-5 cd /path/to/bot && .venv/bin/python live.py >> logs/cron.log 2>&1
0 10 * * 6 cd /path/to/bot && .venv/bin/python auditor.py >> logs/cron_auditor.log 2>&1


## Backtest Summary

Period: April 1 - May 11, 2026. 134 symbols. 4 bullets.

Metric        Value
Trades        28
Win Rate      89.3%
Expectancy    +3.28R
Avg Win       +3.99R
Avg Loss      -2.61R
Growth        +55.6%
Max Loss Run  1
Max Drawdown  -3.3%
=======
# TraderMaamoo — Stage 2 Trend-Surfer

Automated swing trading bot. Red candle pullbacks in Stage 2 uptrends. +5R target. 7-day time exit. No stop-loss.

## Live Performance

| Metric | Value |
|--------|-------|
| Start Date | April 1, 2026 |
| Starting Equity | $458 |
| **Current Equity** | **$XXX.XX** |
| **Total Return** | **+XXX%** |

![Equity Chart](equity_chart.png)

## Strategy

- Entry: Quality red candle at SMA20 during Stage 2 uptrend
- Target: +5R take-profit limit
- Exit: 7 trading days (time stop)
- Risk: 2% per bullet, 4 bullets, fractional shares
- Universe: ~130 liquid US stocks, earnings excluded

## Performance (Paper Backtest — Apr 1 to May 11, 2026)

- Win Rate: **89.3%**
- Expectancy: **+3.28R**
- Avg Win: +3.99R
- Max Loss Run: 1
- Max Drawdown: -3.3%

## Copy Trading

Real-time trade alerts via private Telegram channel.  
Every entry, target, and exit posted as it happens.

**[@TraderMaamooAlerts](https://t.me/TraderMaamooAlerts)** — $99/month

*Bot: @traderMaamooBot*
>>>>>>> c2f7da070dd28b3fa79550e721b5795bb3a52b1c
